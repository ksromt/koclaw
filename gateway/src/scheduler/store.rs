use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{Context, Result, bail};
use tokio::sync::RwLock;

use super::SchedulerJob;

/// Persistent job store backed by a JSON file.
///
/// All mutations auto-save to disk using atomic write (write to `.tmp`, then
/// rename) to prevent corruption from partial writes or crashes.
pub struct JobStore {
    jobs: RwLock<HashMap<String, SchedulerJob>>,
    storage_path: PathBuf,
}

impl JobStore {
    /// Create a new store instance pointing at `storage_path`.
    ///
    /// Does **not** load from disk — call [`load`](Self::load) to hydrate.
    pub fn new(storage_path: impl Into<PathBuf>) -> Self {
        Self {
            jobs: RwLock::new(HashMap::new()),
            storage_path: storage_path.into(),
        }
    }

    /// Load jobs from the JSON file into memory.
    ///
    /// Creates the parent directory if it does not exist.  If the file is
    /// missing or empty the store starts with zero jobs (no error).
    ///
    /// **Must be called exactly once** before any mutating operations
    /// (`insert`, `remove`, `update`). Concurrent calls are not safe.
    pub async fn load(&self) -> Result<()> {
        if let Some(parent) = self.storage_path.parent() {
            tokio::fs::create_dir_all(parent)
                .await
                .context("create storage directory")?;
        }

        // Clean up stale .tmp file from a previous interrupted save.
        let tmp_path = self.storage_path.with_extension("json.tmp");
        let _ = tokio::fs::remove_file(&tmp_path).await;

        if !self.storage_path.exists() {
            return Ok(());
        }

        let content = tokio::fs::read_to_string(&self.storage_path)
            .await
            .context("read storage file")?;

        if content.trim().is_empty() {
            return Ok(());
        }

        let loaded: HashMap<String, SchedulerJob> =
            serde_json::from_str(&content).context("parse storage JSON")?;

        let mut jobs = self.jobs.write().await;
        *jobs = loaded;
        Ok(())
    }

    /// Atomically persist the in-memory jobs to disk.
    ///
    /// Writes to a `.tmp` sibling first, then renames — so a crash mid-write
    /// never corrupts the real file.
    pub async fn save(&self) -> Result<()> {
        let jobs = self.jobs.read().await;
        let json = serde_json::to_string_pretty(&*jobs).context("serialize jobs")?;
        drop(jobs); // release lock before I/O

        let tmp_path = self.storage_path.with_extension("json.tmp");
        tokio::fs::write(&tmp_path, &json)
            .await
            .context("write tmp file")?;
        tokio::fs::rename(&tmp_path, &self.storage_path)
            .await
            .context("rename tmp -> final")?;
        Ok(())
    }

    /// Insert a job and persist to disk.
    pub async fn insert(&self, job: SchedulerJob) -> Result<()> {
        {
            let mut jobs = self.jobs.write().await;
            jobs.insert(job.id.clone(), job);
        }
        self.save().await
    }

    /// Remove a job by ID. Returns the removed job, or `None` if not found.
    pub async fn remove(&self, job_id: &str) -> Result<Option<SchedulerJob>> {
        let removed = {
            let mut jobs = self.jobs.write().await;
            jobs.remove(job_id)
        };
        if removed.is_some() {
            self.save().await?;
        }
        Ok(removed)
    }

    /// Get a clone of a job by ID.
    pub async fn get(&self, job_id: &str) -> Option<SchedulerJob> {
        let jobs = self.jobs.read().await;
        jobs.get(job_id).cloned()
    }

    /// List all jobs.
    pub async fn list(&self) -> Vec<SchedulerJob> {
        let jobs = self.jobs.read().await;
        jobs.values().cloned().collect()
    }

    /// List jobs belonging to a specific session.
    pub async fn list_for_session(&self, session_id: &str) -> Vec<SchedulerJob> {
        let jobs = self.jobs.read().await;
        jobs.values()
            .filter(|j| j.session_id == session_id)
            .cloned()
            .collect()
    }

    /// Update an existing job (matched by `job.id`) and persist.
    ///
    /// Returns an error if no job with that ID exists.
    pub async fn update(&self, job: SchedulerJob) -> Result<()> {
        {
            let mut jobs = self.jobs.write().await;
            if !jobs.contains_key(&job.id) {
                bail!("job not found: {}", job.id);
            }
            jobs.insert(job.id.clone(), job);
        }
        self.save().await
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::scheduler::{JobSchedule, JobType, SchedulerJob};

    /// Helper: build a job with a given id and session_id.
    fn make_job(id: &str, session_id: &str) -> SchedulerJob {
        SchedulerJob {
            id: id.into(),
            name: format!("job-{id}"),
            channel: "Telegram".into(),
            target_id: "12345".into(),
            session_id: session_id.into(),
            created_by: "user-1".into(),
            message: "hello".into(),
            schedule: JobSchedule::Every { interval_secs: 60 },
            created_at: 1_700_000_000_000,
            last_fired_at: None,
            delete_after_run: false,
            enabled: true,
            job_type: JobType::User,
        }
    }

    #[tokio::test]
    async fn test_insert_and_get() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        let job = make_job("aaa", "sess-1");
        store.insert(job).await.unwrap();

        let got = store.get("aaa").await.expect("job should exist");
        assert_eq!(got.id, "aaa");
        assert_eq!(got.name, "job-aaa");
        assert_eq!(got.session_id, "sess-1");
        assert_eq!(got.job_type, JobType::User);
    }

    #[tokio::test]
    async fn test_remove() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        store.insert(make_job("bbb", "sess-1")).await.unwrap();
        assert!(store.get("bbb").await.is_some());

        let removed = store.remove("bbb").await.unwrap();
        assert!(removed.is_some());
        assert_eq!(removed.unwrap().id, "bbb");

        assert!(store.get("bbb").await.is_none());

        // Removing again returns None.
        let again = store.remove("bbb").await.unwrap();
        assert!(again.is_none());
    }

    #[tokio::test]
    async fn test_list_all() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        store.insert(make_job("c1", "sess-1")).await.unwrap();
        store.insert(make_job("c2", "sess-2")).await.unwrap();
        store.insert(make_job("c3", "sess-1")).await.unwrap();

        let all = store.list().await;
        assert_eq!(all.len(), 3);
    }

    #[tokio::test]
    async fn test_list_for_session() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        store.insert(make_job("d1", "sess-A")).await.unwrap();
        store.insert(make_job("d2", "sess-B")).await.unwrap();
        store.insert(make_job("d3", "sess-A")).await.unwrap();
        store.insert(make_job("d4", "sess-C")).await.unwrap();

        let sess_a = store.list_for_session("sess-A").await;
        assert_eq!(sess_a.len(), 2);
        assert!(sess_a.iter().all(|j| j.session_id == "sess-A"));

        let sess_b = store.list_for_session("sess-B").await;
        assert_eq!(sess_b.len(), 1);
        assert_eq!(sess_b[0].id, "d2");

        let sess_x = store.list_for_session("sess-X").await;
        assert!(sess_x.is_empty());
    }

    #[tokio::test]
    async fn test_persistence_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");

        // --- Store 1: insert jobs ---
        {
            let store = JobStore::new(&path);
            store.load().await.unwrap();
            store.insert(make_job("e1", "sess-1")).await.unwrap();
            store.insert(make_job("e2", "sess-2")).await.unwrap();
        }

        // --- Store 2: fresh instance, same file ---
        {
            let store = JobStore::new(&path);
            store.load().await.unwrap();

            let all = store.list().await;
            assert_eq!(all.len(), 2);

            let e1 = store.get("e1").await.expect("e1 should persist");
            assert_eq!(e1.name, "job-e1");

            let e2 = store.get("e2").await.expect("e2 should persist");
            assert_eq!(e2.session_id, "sess-2");
        }
    }

    #[tokio::test]
    async fn test_update() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        store.insert(make_job("f1", "sess-1")).await.unwrap();

        // Mutate the job and update.
        let mut modified = store.get("f1").await.unwrap();
        modified.message = "updated message".into();
        modified.enabled = false;
        store.update(modified).await.unwrap();

        let got = store.get("f1").await.unwrap();
        assert_eq!(got.message, "updated message");
        assert!(!got.enabled);

        // Verify persistence: new store, same file.
        let store2 = JobStore::new(&path);
        store2.load().await.unwrap();
        let got2 = store2.get("f1").await.unwrap();
        assert_eq!(got2.message, "updated message");
        assert!(!got2.enabled);
    }

    #[tokio::test]
    async fn test_update_nonexistent() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("jobs.json");
        let store = JobStore::new(&path);
        store.load().await.unwrap();

        let phantom = make_job("ghost", "sess-1");
        let result = store.update(phantom).await;
        assert!(result.is_err());
        assert!(
            result
                .unwrap_err()
                .to_string()
                .contains("job not found: ghost")
        );
    }
}
