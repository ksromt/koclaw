use std::str::FromStr;

use chrono::TimeZone;
use chrono_tz::Tz;
use cron::Schedule;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A scheduled job managed by the Koclaw scheduler engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SchedulerJob {
    /// UUID v4 short (first 8 hex chars).
    pub id: String,
    /// Human-readable label.
    pub name: String,
    /// Target channel type (e.g., "Telegram", "Discord").
    pub channel: String,
    /// User or chat ID for delivery.
    pub target_id: String,
    /// Session ID for Agent context continuity.
    pub session_id: String,
    /// User ID of the creator.
    pub created_by: String,
    /// Reminder text or job description sent when the job fires.
    pub message: String,
    /// When to fire.
    pub schedule: JobSchedule,
    /// Creation timestamp in Unix milliseconds.
    pub created_at: u64,
    /// Last time the job fired, in Unix milliseconds. Used for recurring jobs.
    pub last_fired_at: Option<u64>,
    /// If true, the job is deleted after a single execution.
    pub delete_after_run: bool,
    /// Whether the job is active.
    pub enabled: bool,
    /// Classification of the job.
    pub job_type: JobType,
}

/// When a job should fire.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum JobSchedule {
    /// One-shot at a specific Unix-ms timestamp.
    At { timestamp_ms: u64 },
    /// Recurring at a fixed interval.
    Every { interval_secs: u64 },
    /// Cron expression (5-field) with a timezone name (IANA, e.g. "Asia/Tokyo").
    Cron { expression: String, timezone: String },
}

/// Classification of a scheduler job.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum JobType {
    /// Created by a user via chat command.
    User,
    /// Internal heartbeat / keep-alive ping.
    Heartbeat,
    /// System-level maintenance task.
    System,
}

impl SchedulerJob {
    /// Create a new scheduler job with a generated short UUID.
    pub fn new(
        name: impl Into<String>,
        channel: impl Into<String>,
        target_id: impl Into<String>,
        session_id: impl Into<String>,
        created_by: impl Into<String>,
        message: impl Into<String>,
        schedule: JobSchedule,
        delete_after_run: bool,
        job_type: JobType,
    ) -> Self {
        let full_uuid = Uuid::new_v4().to_string();
        // Take first 8 hex chars (skip the first dash position is at index 8, so simple slice works).
        let short_id = full_uuid[..8].to_string();

        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock before epoch")
            .as_millis() as u64;

        Self {
            id: short_id,
            name: name.into(),
            channel: channel.into(),
            target_id: target_id.into(),
            session_id: session_id.into(),
            created_by: created_by.into(),
            message: message.into(),
            schedule,
            created_at: now_ms,
            last_fired_at: None,
            delete_after_run,
            enabled: true,
            job_type,
        }
    }

    /// Compute the next fire time in Unix milliseconds.
    ///
    /// - `At`: returns the timestamp if the job has not yet fired.
    /// - `Every`: returns `anchor + interval_secs * 1000` where anchor is
    ///   `last_fired_at` or `created_at`.
    /// - `Cron`: parses the 5-field expression, converts to the crate's 7-field
    ///   format, and computes the next occurrence in the given timezone.
    pub fn next_fire_time(&self) -> Option<u64> {
        match &self.schedule {
            JobSchedule::At { timestamp_ms } => {
                if self.last_fired_at.is_some() {
                    None
                } else {
                    Some(*timestamp_ms)
                }
            }
            JobSchedule::Every { interval_secs } => {
                let anchor = self.last_fired_at.unwrap_or(self.created_at);
                interval_secs
                    .checked_mul(1000)
                    .and_then(|ms| anchor.checked_add(ms))
            }
            JobSchedule::Cron {
                expression,
                timezone,
            } => cron_next_fire(expression, timezone, self.last_fired_at),
        }
    }

    /// Returns `true` if the job should fire at the given wall-clock time (Unix ms).
    pub fn is_due(&self, now_ms: u64) -> bool {
        match self.next_fire_time() {
            Some(t) => t <= now_ms,
            None => false,
        }
    }
}

/// Parse a 5-field cron expression and compute the next occurrence after "now"
/// in the given IANA timezone.  Returns Unix milliseconds, or `None` on parse
/// failure / no upcoming occurrence.
fn cron_next_fire(expression: &str, timezone: &str, last_fired_at: Option<u64>) -> Option<u64> {
    // The `cron` crate expects 7 fields: sec min hour dom month dow year.
    // Users provide 5 fields:       min hour dom month dow.
    // Prepend "0" (seconds) and append "*" (year).
    let seven_field = format!("0 {} *", expression.trim());

    let schedule = Schedule::from_str(&seven_field).ok()?;
    let tz: Tz = timezone.parse().ok()?;

    // Determine the "after" point: either last_fired_at or current wall-clock.
    let after = match last_fired_at {
        Some(ms) => {
            let secs = (ms / 1000) as i64;
            let nanos = ((ms % 1000) * 1_000_000) as u32;
            tz.timestamp_opt(secs, nanos).single()?
        }
        None => chrono::Utc::now().with_timezone(&tz),
    };

    let next = schedule.after(&after).next()?;
    u64::try_from(next.timestamp_millis()).ok()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: build a minimal job for testing with a given schedule.
    fn make_job(schedule: JobSchedule) -> SchedulerJob {
        SchedulerJob {
            id: "abcd1234".into(),
            name: "test-job".into(),
            channel: "Telegram".into(),
            target_id: "12345".into(),
            session_id: "sess-1".into(),
            created_by: "user-1".into(),
            message: "hello".into(),
            schedule,
            created_at: 1_700_000_000_000, // 2023-11-14 ~22:13 UTC
            last_fired_at: None,
            delete_after_run: false,
            enabled: true,
            job_type: JobType::User,
        }
    }

    #[test]
    fn test_job_serialization_roundtrip() {
        let job = SchedulerJob::new(
            "morning-alarm",
            "Discord",
            "chan-99",
            "sess-2",
            "user-42",
            "Wake up!",
            JobSchedule::Cron {
                expression: "30 9 * * *".into(),
                timezone: "Asia/Tokyo".into(),
            },
            true,
            JobType::User,
        );

        let json = serde_json::to_string(&job).expect("serialize");
        let restored: SchedulerJob = serde_json::from_str(&json).expect("deserialize");

        assert_eq!(restored.name, "morning-alarm");
        assert_eq!(restored.channel, "Discord");
        assert_eq!(restored.target_id, "chan-99");
        assert_eq!(restored.message, "Wake up!");
        assert!(restored.delete_after_run);
        assert_eq!(restored.job_type, JobType::User);
        assert!(restored.enabled);

        // Schedule should round-trip as Cron variant.
        match &restored.schedule {
            JobSchedule::Cron {
                expression,
                timezone,
            } => {
                assert_eq!(expression, "30 9 * * *");
                assert_eq!(timezone, "Asia/Tokyo");
            }
            _ => panic!("expected Cron schedule"),
        }
    }

    #[test]
    fn test_at_schedule_next_fire_time() {
        let job = make_job(JobSchedule::At {
            timestamp_ms: 1_700_000_060_000,
        });

        // Not yet fired -> returns the target timestamp.
        assert_eq!(job.next_fire_time(), Some(1_700_000_060_000));

        // After firing, next_fire_time should return None.
        let mut fired = job;
        fired.last_fired_at = Some(1_700_000_060_000);
        assert_eq!(fired.next_fire_time(), None);
    }

    #[test]
    fn test_at_schedule_is_due() {
        let job = make_job(JobSchedule::At {
            timestamp_ms: 1_700_000_060_000,
        });

        // Before target time.
        assert!(!job.is_due(1_700_000_000_000));
        // Exactly at target time.
        assert!(job.is_due(1_700_000_060_000));
        // After target time.
        assert!(job.is_due(1_700_000_120_000));
    }

    #[test]
    fn test_every_schedule_next_fire_time() {
        // Interval: every 300 seconds (5 minutes).
        let mut job = make_job(JobSchedule::Every { interval_secs: 300 });

        // No last_fired_at -> anchors on created_at.
        assert_eq!(
            job.next_fire_time(),
            Some(1_700_000_000_000 + 300 * 1000)
        );

        // After firing once, anchor shifts to last_fired_at.
        job.last_fired_at = Some(1_700_000_300_000);
        assert_eq!(
            job.next_fire_time(),
            Some(1_700_000_300_000 + 300 * 1000)
        );
    }

    #[test]
    fn test_cron_next_fire_time() {
        // "0 9 * * *" = every day at 09:00, Asia/Tokyo (UTC+9).
        let mut job = make_job(JobSchedule::Cron {
            expression: "0 9 * * *".into(),
            timezone: "Asia/Tokyo".into(),
        });

        // Anchor: 2023-11-15 00:00:00 UTC = 2023-11-15 09:00:00 JST.
        // Set last_fired_at to 2023-11-15 00:00:00 UTC so the "after" point
        // is exactly 09:00 JST on the 15th; the *next* occurrence should be
        // 09:00 JST on the 16th = 2023-11-16 00:00:00 UTC.
        job.last_fired_at = Some(1_700_006_400_000); // 2023-11-15 00:00:00 UTC

        let next = job.next_fire_time().expect("should compute next fire time");

        // 2023-11-16 00:00:00 UTC = 1_700_092_800_000 ms
        assert_eq!(next, 1_700_092_800_000);
    }

    #[test]
    fn test_job_type_serde() {
        // Each variant round-trips through JSON.
        for variant in [JobType::User, JobType::Heartbeat, JobType::System] {
            let json = serde_json::to_string(&variant).expect("serialize");
            let restored: JobType = serde_json::from_str(&json).expect("deserialize");
            assert_eq!(restored, variant);
        }

        // Verify exact JSON representations.
        assert_eq!(serde_json::to_string(&JobType::User).unwrap(), "\"User\"");
        assert_eq!(
            serde_json::to_string(&JobType::Heartbeat).unwrap(),
            "\"Heartbeat\""
        );
        assert_eq!(
            serde_json::to_string(&JobType::System).unwrap(),
            "\"System\""
        );
    }
}
