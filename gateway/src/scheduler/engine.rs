use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use chrono::Timelike;
use chrono_tz::Tz;
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
    heartbeat_active_start: Option<String>,
    heartbeat_active_end: Option<String>,
    heartbeat_timezone: String,
}

impl SchedulerEngine {
    pub fn new(
        store: Arc<JobStore>,
        fire_tx: mpsc::Sender<FiredJob>,
        tick_interval_ms: u64,
        heartbeat_active_start: Option<String>,
        heartbeat_active_end: Option<String>,
        heartbeat_timezone: String,
    ) -> Self {
        Self {
            store,
            fire_tx,
            tick_interval_ms,
            heartbeat_active_start,
            heartbeat_active_end,
            heartbeat_timezone,
        }
    }

    /// Check if the current time is within heartbeat active hours.
    /// Returns true if active_hours are not configured (always active).
    fn is_in_active_hours(
        active_start: Option<&str>,
        active_end: Option<&str>,
        timezone: &str,
    ) -> bool {
        let (start_str, end_str) = match (active_start, active_end) {
            (Some(s), Some(e)) => (s, e),
            _ => return true,
        };

        let parse_hm = |s: &str| -> Option<(u32, u32)> {
            let parts: Vec<&str> = s.split(':').collect();
            if parts.len() != 2 {
                return None;
            }
            let h = parts[0].parse::<u32>().ok()?;
            let m = parts[1].parse::<u32>().ok()?;
            Some((h, m))
        };

        let (sh, sm) = match parse_hm(start_str) {
            Some(v) => v,
            None => return true,
        };
        let (eh, em) = match parse_hm(end_str) {
            Some(v) => v,
            None => return true,
        };

        let tz: Tz = match timezone.parse() {
            Ok(t) => t,
            Err(_) => return true,
        };

        let now = chrono::Utc::now().with_timezone(&tz);
        let now_minutes = now.hour() * 60 + now.minute();
        let start_minutes = sh * 60 + sm;
        let end_minutes = eh * 60 + em;

        if start_minutes <= end_minutes {
            // Normal range: e.g., 09:00 to 22:00
            now_minutes >= start_minutes && now_minutes < end_minutes
        } else {
            // Overnight range: e.g., 22:00 to 06:00
            now_minutes >= start_minutes || now_minutes < end_minutes
        }
    }

    /// Returns true if a heartbeat job should be allowed to fire right now.
    fn heartbeat_allowed(&self) -> bool {
        Self::is_in_active_hours(
            self.heartbeat_active_start.as_deref(),
            self.heartbeat_active_end.as_deref(),
            &self.heartbeat_timezone,
        )
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
            // Skip heartbeat jobs outside active hours
            if job.job_type == JobType::Heartbeat && !self.heartbeat_allowed() {
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
            // Skip heartbeat jobs outside active hours
            if job.job_type == JobType::Heartbeat && !self.heartbeat_allowed() {
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
        let engine = Arc::new(SchedulerEngine::new(
            store.clone(),
            tx,
            tick_ms,
            None,
            None,
            "UTC".to_string(),
        ));
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

    // ----- test_is_in_active_hours ---------------------------------------------
    #[test]
    fn test_is_in_active_hours() {
        // No start/end configured -> always active
        assert!(SchedulerEngine::is_in_active_hours(None, None, "UTC"));
        assert!(SchedulerEngine::is_in_active_hours(Some("09:00"), None, "UTC"));
        assert!(SchedulerEngine::is_in_active_hours(None, Some("22:00"), "UTC"));

        // Invalid format -> falls back to true
        assert!(SchedulerEngine::is_in_active_hours(
            Some("bad"),
            Some("22:00"),
            "UTC"
        ));
        assert!(SchedulerEngine::is_in_active_hours(
            Some("09:00"),
            Some("bad"),
            "UTC"
        ));

        // Invalid timezone -> falls back to true
        assert!(SchedulerEngine::is_in_active_hours(
            Some("09:00"),
            Some("22:00"),
            "Invalid/Zone"
        ));

        // Normal range 00:00 to 23:59 covers the full day -> always in range
        assert!(SchedulerEngine::is_in_active_hours(
            Some("00:00"),
            Some("23:59"),
            "UTC"
        ));

        // Range 00:00 to 00:00 (start == end) -> wrap-around logic covers full day
        // (now_minutes >= 0 || now_minutes < 0 is always true since start_minutes == end_minutes
        //  and the else branch triggers: now >= 0 is always true)
        // Actually start == end triggers the normal branch where now >= 0 && now < 0 is false.
        // This is a degenerate case: active window of zero minutes.
        assert!(!SchedulerEngine::is_in_active_hours(
            Some("00:00"),
            Some("00:00"),
            "UTC"
        ));
    }

    // ----- test_heartbeat_skipped_outside_active_hours ---------------------------
    #[tokio::test]
    async fn test_heartbeat_skipped_outside_active_hours() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test_jobs.json");
        let store = Arc::new(JobStore::new(&path));
        store.load().await.unwrap();
        let (tx, mut rx) = mpsc::channel(32);

        // Create an engine with an active hours window that is impossible:
        // start == end means zero-minute window, so heartbeats will always be skipped.
        let engine = Arc::new(SchedulerEngine::new(
            store.clone(),
            tx,
            1000,
            Some("00:00".to_string()),
            Some("00:00".to_string()),
            "UTC".to_string(),
        ));

        // Insert a heartbeat job that is due now.
        let hb_job = make_job_with(
            "hb1",
            JobSchedule::Every { interval_secs: 60 },
            JobType::Heartbeat,
            false,
            true,
        );
        // Insert a regular user job that is also due now.
        let user_job = make_job_with(
            "usr1",
            JobSchedule::At {
                timestamp_ms: 1_000_000_000_000,
            },
            JobType::User,
            true,
            true,
        );

        store.insert(hb_job).await.unwrap();
        store.insert(user_job).await.unwrap();

        engine.tick().await.unwrap();

        // Only the user job should have fired; heartbeat should be skipped.
        let mut fired_ids = Vec::new();
        while let Ok(f) = rx.try_recv() {
            fired_ids.push(f.job.id.clone());
        }
        assert_eq!(fired_ids.len(), 1);
        assert_eq!(fired_ids[0], "usr1");

        // Heartbeat job should still be in the store, untouched.
        let hb = store.get("hb1").await.expect("heartbeat job should still exist");
        assert!(hb.last_fired_at.is_none());

        std::mem::forget(dir);
    }
}
