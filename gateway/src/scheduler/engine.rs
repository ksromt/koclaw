use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use tokio::sync::mpsc;

use super::{JobSchedule, JobStore, JobType, SchedulerJob};

/// A job that has fired and needs to be dispatched to the appropriate channel.
#[derive(Debug, Clone)]
pub struct FiredJob {
    pub job: SchedulerJob,
    /// Classification string for downstream handlers: "reminder", "heartbeat",
    /// "system", "cron", or "recurring".
    pub trigger_type: String,
}

/// The scheduler engine: a tokio task that periodically scans the job store and
/// fires any jobs whose `next_fire_time` has arrived.
pub struct SchedulerEngine {
    store: Arc<JobStore>,
    fire_tx: mpsc::Sender<FiredJob>,
    tick_interval_ms: u64,
}

impl SchedulerEngine {
    pub fn new(
        store: Arc<JobStore>,
        fire_tx: mpsc::Sender<FiredJob>,
        tick_interval_ms: u64,
    ) -> Self {
        Self {
            store,
            fire_tx,
            tick_interval_ms,
        }
    }

    /// Start the infinite tick loop.  Runs until the `fire_tx` receiver is
    /// dropped (at which point the engine logs a warning and returns).
    pub async fn start(self: Arc<Self>) {
        let mut interval = tokio::time::interval(Duration::from_millis(self.tick_interval_ms));
        loop {
            interval.tick().await;
            if let Err(e) = self.tick().await {
                tracing::error!(error = %e, "Scheduler tick error");
            }
        }
    }

    /// Scan and fire all currently-overdue jobs.  Used at startup to catch up on
    /// jobs that became due while the system was down.  Returns the number of
    /// jobs that were fired.
    pub async fn fire_overdue(self: &Arc<Self>) -> Result<usize> {
        let now_ms = current_time_ms();
        let jobs = self.store.list().await;
        let mut fired_count = 0;

        for job in jobs {
            if !job.enabled {
                continue;
            }
            if !job.is_due(now_ms) {
                continue;
            }

            let trigger_type = trigger_type_for(&job);
            let fired = FiredJob {
                job: job.clone(),
                trigger_type,
            };

            if self.fire_tx.send(fired).await.is_err() {
                tracing::warn!("Fired job receiver dropped during overdue catch-up");
                return Ok(fired_count);
            }

            fired_count += 1;

            // Post-fire bookkeeping
            if job.delete_after_run {
                self.store.remove(&job.id).await?;
            } else {
                let mut updated = job.clone();
                updated.last_fired_at = Some(now_ms);
                self.store.update(updated).await?;
            }
        }

        Ok(fired_count)
    }

    /// One tick: scan all jobs in the store and fire any that are due.
    async fn tick(&self) -> Result<()> {
        let now_ms = current_time_ms();
        let jobs = self.store.list().await;

        for job in jobs {
            if !job.enabled {
                continue;
            }
            if !job.is_due(now_ms) {
                continue;
            }

            let trigger_type = trigger_type_for(&job);
            let fired = FiredJob {
                job: job.clone(),
                trigger_type,
            };

            if self.fire_tx.send(fired).await.is_err() {
                tracing::warn!("Fired job receiver dropped");
                return Ok(());
            }

            // Post-fire bookkeeping
            if job.delete_after_run {
                self.store.remove(&job.id).await?;
            } else {
                let mut updated = job.clone();
                updated.last_fired_at = Some(now_ms);
                self.store.update(updated).await?;
            }
        }

        Ok(())
    }
}

/// Derive the human-readable trigger type string from a job.
fn trigger_type_for(job: &SchedulerJob) -> String {
    match job.job_type {
        JobType::Heartbeat => "heartbeat".into(),
        JobType::System => "system".into(),
        JobType::User => match &job.schedule {
            JobSchedule::At { .. } => "reminder".into(),
            JobSchedule::Cron { .. } => "cron".into(),
            JobSchedule::Every { .. } => "recurring".into(),
        },
    }
}

/// Current wall-clock time in Unix milliseconds.
fn current_time_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock before epoch")
        .as_millis() as u64
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    /// Shared test setup: creates a temp-dir-backed store, mpsc channel, and
    /// engine.  Returns all three so the test can interact with any of them.
    async fn setup(tick_ms: u64) -> (Arc<SchedulerEngine>, mpsc::Receiver<FiredJob>, Arc<JobStore>) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test_jobs.json");
        let store = Arc::new(JobStore::new(&path));
        store.load().await.unwrap();
        let (tx, rx) = mpsc::channel(32);
        let engine = Arc::new(SchedulerEngine::new(store.clone(), tx, tick_ms));
        // Prevent tempdir from being dropped (which deletes the directory).
        // The dir must outlive the store; `forget` keeps it alive for the test.
        std::mem::forget(dir);
        (engine, rx, store)
    }

    /// Helper: build a job with overridable fields for engine tests.
    fn make_job_with(
        id: &str,
        schedule: JobSchedule,
        job_type: JobType,
        delete_after_run: bool,
        enabled: bool,
    ) -> SchedulerJob {
        SchedulerJob {
            id: id.into(),
            name: format!("job-{id}"),
            channel: "Telegram".into(),
            target_id: "12345".into(),
            session_id: "sess-1".into(),
            created_by: "user-1".into(),
            message: "test message".into(),
            schedule,
            created_at: 1_000_000_000_000,
            last_fired_at: None,
            delete_after_run,
            enabled,
            job_type,
        }
    }

    // ----- test_at_job_fires -------------------------------------------------
    #[tokio::test]
    async fn test_at_job_fires() {
        let (engine, mut rx, store) = setup(1000).await;

        // Create an At job whose timestamp is in the past (i.e., due now).
        let job = make_job_with(
            "at1",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000, // well in the past
            },
            JobType::User,
            true, // delete_after_run
            true,
        );
        store.insert(job).await.unwrap();

        // One tick should fire it.
        engine.tick().await.unwrap();

        // Verify we received the fired job.
        let fired = rx.try_recv().expect("should have received a FiredJob");
        assert_eq!(fired.job.id, "at1");
        assert_eq!(fired.trigger_type, "reminder");

        // Since delete_after_run=true, the job should be gone from the store.
        assert!(store.get("at1").await.is_none());
    }

    // ----- test_every_job_recurs ---------------------------------------------
    #[tokio::test]
    async fn test_every_job_recurs() {
        let (engine, mut rx, store) = setup(1000).await;

        // Every-60s job created far in the past so it's immediately due.
        let job = make_job_with(
            "ev1",
            JobSchedule::Every { interval_secs: 60 },
            JobType::User,
            false, // keep after run
            true,
        );
        store.insert(job).await.unwrap();

        engine.tick().await.unwrap();

        let fired = rx.try_recv().expect("should have received a FiredJob");
        assert_eq!(fired.job.id, "ev1");
        assert_eq!(fired.trigger_type, "recurring");

        // Job should still exist in the store with an updated last_fired_at.
        let updated = store.get("ev1").await.expect("job should still exist");
        assert!(updated.last_fired_at.is_some());
    }

    // ----- test_disabled_job_skipped -----------------------------------------
    #[tokio::test]
    async fn test_disabled_job_skipped() {
        let (engine, mut rx, store) = setup(1000).await;

        // Due job but disabled.
        let job = make_job_with(
            "dis1",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::User,
            true,
            false, // disabled
        );
        store.insert(job).await.unwrap();

        engine.tick().await.unwrap();

        // Nothing should have fired.
        assert!(rx.try_recv().is_err());

        // Job should still be in the store (not deleted).
        assert!(store.get("dis1").await.is_some());
    }

    // ----- test_fire_overdue_catches_up --------------------------------------
    #[tokio::test]
    async fn test_fire_overdue_catches_up() {
        let (engine, mut rx, store) = setup(1000).await;

        // Two overdue jobs.
        let overdue1 = make_job_with(
            "od1",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::User,
            true,
            true,
        );
        let overdue2 = make_job_with(
            "od2",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::System,
            true,
            true,
        );

        // One future job (year ~2100).
        let future_job = make_job_with(
            "fut1",
            JobSchedule::At {
                timestamp_ms: 4_100_000_000_000,
            },
            JobType::User,
            true,
            true,
        );

        store.insert(overdue1).await.unwrap();
        store.insert(overdue2).await.unwrap();
        store.insert(future_job).await.unwrap();

        let count = engine.fire_overdue().await.unwrap();
        assert_eq!(count, 2);

        // Drain the channel to verify both arrived.
        let _ = rx.try_recv().expect("first overdue job");
        let _ = rx.try_recv().expect("second overdue job");

        // Future job should still be in the store.
        assert!(store.get("fut1").await.is_some());

        // Overdue jobs should have been deleted (delete_after_run=true).
        assert!(store.get("od1").await.is_none());
        assert!(store.get("od2").await.is_none());
    }

    // ----- test_trigger_type_mapping -----------------------------------------
    #[tokio::test]
    async fn test_trigger_type_mapping() {
        let (engine, mut rx, store) = setup(1000).await;

        // At + User -> "reminder"
        let at_user = make_job_with(
            "tt1",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::User,
            true,
            true,
        );
        // Every + User -> "recurring"
        let every_user = make_job_with(
            "tt2",
            JobSchedule::Every { interval_secs: 60 },
            JobType::User,
            true,
            true,
        );
        // At + Heartbeat -> "heartbeat"
        let heartbeat = make_job_with(
            "tt3",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::Heartbeat,
            true,
            true,
        );
        // At + System -> "system"
        let system = make_job_with(
            "tt4",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::System,
            true,
            true,
        );

        store.insert(at_user).await.unwrap();
        store.insert(every_user).await.unwrap();
        store.insert(heartbeat).await.unwrap();
        store.insert(system).await.unwrap();

        engine.tick().await.unwrap();

        // Collect all fired jobs. Order from HashMap iteration is non-deterministic,
        // so collect into a vec and sort/search.
        let mut fired_jobs = Vec::new();
        while let Ok(f) = rx.try_recv() {
            fired_jobs.push(f);
        }
        assert_eq!(fired_jobs.len(), 4);

        let find = |id: &str| -> String {
            fired_jobs
                .iter()
                .find(|f| f.job.id == id)
                .unwrap_or_else(|| panic!("expected fired job with id={id}"))
                .trigger_type
                .clone()
        };

        assert_eq!(find("tt1"), "reminder");
        assert_eq!(find("tt2"), "recurring");
        assert_eq!(find("tt3"), "heartbeat");
        assert_eq!(find("tt4"), "system");
    }
}
