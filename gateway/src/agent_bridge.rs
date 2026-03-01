use std::collections::HashMap;
use std::sync::Arc;

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

use koclaw_common::message::IncomingMessage;

use crate::scheduler::{JobSchedule, JobStore, JobType, SchedulerJob};

/// Type alias for the WebSocket sender half.
type WsSender = futures_util::stream::SplitSink<
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
    Message,
>;

/// Request sent from Gateway to Python Agent.
#[derive(Debug, Serialize)]
pub struct AgentRequest {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub session_id: String,
    pub user_id: String,
    pub channel: String,
    pub permission: String,
    pub text: Option<String>,
    pub attachments: Vec<AttachmentPayload>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub system_prompt: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sandbox_root: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub allowed_commands: Vec<String>,
}

/// Additional context for a chat request (persona, sandbox, etc.)
#[derive(Debug, Default)]
pub struct ChatContext {
    pub system_prompt: Option<String>,
    pub sandbox_root: Option<String>,
    pub allowed_commands: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct AttachmentPayload {
    pub attachment_type: String,
    pub url: String,
    pub mime_type: Option<String>,
}

/// Response chunk from Python Agent.
#[derive(Debug, Clone, Deserialize)]
pub struct AgentResponseChunk {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub session_id: Option<String>,
    pub content: Option<String>,
    /// Base64-encoded audio data (WAV) -- sent with "audio" type chunks
    #[serde(default)]
    pub data: Option<String>,
    /// Audio format (e.g. "wav") -- sent with "audio" type chunks
    #[serde(default)]
    pub format: Option<String>,
    /// Expression tags extracted from response -- sent with "done" chunks
    #[serde(default)]
    pub expressions: Option<Vec<String>>,
}

// ---------------------------------------------------------------------------
// Scheduler protocol types
// ---------------------------------------------------------------------------

/// Scheduler trigger message sent from Gateway to Agent.
/// Sent when a scheduled job fires so the Agent can generate a response.
#[derive(Debug, Serialize)]
pub struct SchedulerTriggerMessage {
    #[serde(rename = "type")]
    pub msg_type: String, // always "scheduler_trigger"
    pub session_id: String,
    pub trigger_type: String, // "reminder", "heartbeat", "cron", "recurring", "system"
    pub job_id: String,
    pub message: String,
    pub channel: String,
    pub target_id: String,
    pub permission: String,
}

/// Scheduler request from Agent to Gateway.
/// The Agent sends this when the LLM invokes scheduler tools (create/list/delete).
#[derive(Debug, Deserialize)]
pub struct SchedulerRequest {
    #[serde(rename = "type")]
    pub msg_type: String, // "scheduler_request"
    pub session_id: String,
    pub action: String, // "create", "list", "delete"
    #[serde(default)]
    pub job: Option<serde_json::Value>, // Job data for create
    #[serde(default)]
    pub job_id: Option<String>, // For delete
}

/// Gateway's response to a scheduler request from the Agent.
#[derive(Debug, Serialize)]
pub struct SchedulerResponse {
    #[serde(rename = "type")]
    pub msg_type: String, // "scheduler_response"
    pub session_id: String,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub job_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub jobs: Option<Vec<serde_json::Value>>,
}

/// Pending response senders keyed by session_id.
type PendingResponses = Arc<RwLock<HashMap<String, mpsc::Sender<AgentResponseChunk>>>>;

/// Bridge to the Python Agent process via WebSocket.
///
/// The bridge maintains a single WebSocket connection to the Agent.
/// When `chat()` is called, it sends a request and registers a response
/// channel keyed by session_id. The background receiver task dispatches
/// incoming chunks to the appropriate waiting caller.
///
/// The bridge also handles scheduler requests from the Agent: when the
/// Agent's LLM invokes scheduler tools, it sends `scheduler_request`
/// messages through the WebSocket, which the receiver task intercepts
/// and handles by interacting with the `JobStore`.
pub struct AgentBridge {
    agent_url: String,
    sender: Arc<Mutex<Option<WsSender>>>,
    pending: PendingResponses,
    scheduler_store: Arc<RwLock<Option<Arc<JobStore>>>>,
}

impl AgentBridge {
    pub fn new(agent_url: String) -> Self {
        Self {
            agent_url,
            sender: Arc::new(Mutex::new(None)),
            pending: Arc::new(RwLock::new(HashMap::new())),
            scheduler_store: Arc::new(RwLock::new(None)),
        }
    }

    /// Register the scheduler job store so the bridge can handle
    /// scheduler requests from the Agent.
    pub async fn set_scheduler_store(&self, store: Arc<JobStore>) {
        let mut guard = self.scheduler_store.write().await;
        *guard = Some(store);
    }

    /// Connect to the Python Agent WebSocket server.
    pub async fn connect(&self) -> Result<()> {
        info!(url = %self.agent_url, "Connecting to Agent...");

        let (ws_stream, _) = connect_async(&self.agent_url)
            .await
            .with_context(|| format!("Failed to connect to Agent at {}", self.agent_url))?;

        let (sender, mut receiver) = ws_stream.split();
        *self.sender.lock().await = Some(sender);

        // Clone references for the receiver task
        let pending = self.pending.clone();
        let sender_arc = self.sender.clone();
        let scheduler_store = self.scheduler_store.clone();

        // Spawn a task to handle incoming messages from agent
        tokio::spawn(async move {
            while let Some(msg) = receiver.next().await {
                match msg {
                    Ok(Message::Text(text)) => {
                        debug!(text = %text, "Received from Agent");

                        // Check if this is a scheduler request from the Agent
                        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                            if value.get("type").and_then(|v| v.as_str())
                                == Some("scheduler_request")
                            {
                                if let Ok(req) = serde_json::from_str::<SchedulerRequest>(&text) {
                                    let store_guard = scheduler_store.read().await;
                                    if let Some(store) = store_guard.as_ref() {
                                        handle_scheduler_request(
                                            store,
                                            &sender_arc,
                                            req,
                                        )
                                        .await;
                                    } else {
                                        warn!(
                                            "Scheduler request received but no store configured"
                                        );
                                    }
                                    continue;
                                }
                            }
                        }

                        // Normal response dispatch
                        Self::dispatch_response(&pending, &text).await;
                    }
                    Ok(Message::Close(_)) => {
                        info!("Agent connection closed");
                        break;
                    }
                    Err(e) => {
                        error!(error = %e, "Agent WebSocket error");
                        break;
                    }
                    _ => {}
                }
            }

            // Connection lost -- clean up all pending senders
            let mut map = pending.write().await;
            map.clear();
            warn!("Agent connection lost, cleared pending responses");
        });

        info!("Connected to Agent");
        Ok(())
    }

    /// Dispatch a response chunk from the Agent to the waiting caller.
    async fn dispatch_response(pending: &PendingResponses, text: &str) {
        let chunk: AgentResponseChunk = match serde_json::from_str(text) {
            Ok(c) => c,
            Err(e) => {
                warn!(error = %e, "Failed to parse Agent response");
                return;
            }
        };

        let session_id = match &chunk.session_id {
            Some(id) => id.clone(),
            None => {
                debug!("Agent response has no session_id, ignoring");
                return;
            }
        };

        let is_done = chunk.msg_type == "done" || chunk.msg_type == "error";

        // Send chunk to the waiting caller
        let map = pending.read().await;
        if let Some(tx) = map.get(&session_id) {
            if tx.send(chunk).await.is_err() {
                debug!(session_id, "Response receiver dropped");
            }
        } else {
            debug!(session_id, "No pending handler for session");
        }
        drop(map);

        // If this was the final chunk, remove from pending
        if is_done {
            let mut map = pending.write().await;
            map.remove(&session_id);
        }
    }

    /// Send a chat request to the Agent and get a streaming response receiver.
    ///
    /// The returned receiver yields `AgentResponseChunk`s:
    /// - `text_chunk`: partial text response
    /// - `done`: final chunk, signals completion
    /// - `error`: an error occurred
    pub async fn chat(
        &self,
        message: &IncomingMessage,
        context: ChatContext,
    ) -> Result<mpsc::Receiver<AgentResponseChunk>> {
        let request = AgentRequest {
            msg_type: "chat".to_string(),
            session_id: message.session_id.clone(),
            user_id: message.user_id.clone(),
            channel: message.channel.to_string(),
            permission: format!("{:?}", message.permission),
            text: message.text.clone(),
            attachments: message
                .attachments
                .iter()
                .map(|a| AttachmentPayload {
                    attachment_type: format!("{:?}", a.attachment_type),
                    url: a.url.clone(),
                    mime_type: a.mime_type.clone(),
                })
                .collect(),
            system_prompt: context.system_prompt,
            sandbox_root: context.sandbox_root,
            allowed_commands: context.allowed_commands,
        };

        let json = serde_json::to_string(&request)?;

        // Register a response channel BEFORE sending the request
        let (tx, rx) = mpsc::channel(32);
        {
            let mut map = self.pending.write().await;
            map.insert(message.session_id.clone(), tx);
        }

        // Send the request
        let mut sender_guard = self.sender.lock().await;
        if let Some(sender) = sender_guard.as_mut() {
            if let Err(e) = sender.send(Message::Text(json.into())).await {
                // Remove pending on send failure
                self.pending.write().await.remove(&message.session_id);
                return Err(e).context("Failed to send message to Agent");
            }
        } else {
            self.pending.write().await.remove(&message.session_id);
            anyhow::bail!("Not connected to Agent");
        }

        Ok(rx)
    }

    /// Send a scheduler trigger to the Agent and get a streaming response receiver.
    ///
    /// Used when a scheduled job fires: the Gateway sends the trigger to the Agent
    /// so it can generate an appropriate response (e.g., a reminder message or
    /// heartbeat check-in), which is then delivered to the target channel.
    pub async fn trigger(
        &self,
        trigger_msg: &SchedulerTriggerMessage,
    ) -> Result<mpsc::Receiver<AgentResponseChunk>> {
        let json = serde_json::to_string(trigger_msg)?;

        let (tx, rx) = mpsc::channel(32);
        {
            let mut map = self.pending.write().await;
            map.insert(trigger_msg.session_id.clone(), tx);
        }

        let mut sender_guard = self.sender.lock().await;
        if let Some(sender) = sender_guard.as_mut() {
            if let Err(e) = sender.send(Message::Text(json.into())).await {
                self.pending
                    .write()
                    .await
                    .remove(&trigger_msg.session_id);
                return Err(e).context("Failed to send trigger to Agent");
            }
        } else {
            self.pending
                .write()
                .await
                .remove(&trigger_msg.session_id);
            anyhow::bail!("Not connected to Agent");
        }

        Ok(rx)
    }

    /// Check if the bridge is connected.
    pub async fn is_connected(&self) -> bool {
        self.sender.lock().await.is_some()
    }
}

// ---------------------------------------------------------------------------
// Scheduler request handlers
// ---------------------------------------------------------------------------

/// Handle a scheduler request from the Agent (create/list/delete jobs).
async fn handle_scheduler_request(
    store: &JobStore,
    sender: &Arc<Mutex<Option<WsSender>>>,
    request: SchedulerRequest,
) {
    let response = match request.action.as_str() {
        "create" => handle_scheduler_create(store, &request).await,
        "list" => handle_scheduler_list(store, &request).await,
        "delete" => handle_scheduler_delete(store, &request).await,
        _ => error_response(
            &request.session_id,
            &format!("Unknown scheduler action: {}", request.action),
        ),
    };

    // Send response back to Agent
    let json = match serde_json::to_string(&response) {
        Ok(j) => j,
        Err(e) => {
            error!(error = %e, "Failed to serialize scheduler response");
            return;
        }
    };
    let mut sender_guard = sender.lock().await;
    if let Some(s) = sender_guard.as_mut() {
        if let Err(e) = s.send(Message::Text(json.into())).await {
            error!(error = %e, "Failed to send scheduler response to Agent");
        }
    }
}

async fn handle_scheduler_create(store: &JobStore, req: &SchedulerRequest) -> SchedulerResponse {
    let job_data = match &req.job {
        Some(v) => v,
        None => return error_response(&req.session_id, "Missing job data"),
    };

    let name = job_data
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("unnamed");
    let message = job_data
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let channel = job_data
        .get("channel")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();
    let target_id = job_data
        .get("target_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");

    // Determine schedule from the request
    let schedule = if let Some(delay) = job_data.get("delay_seconds").and_then(|v| v.as_u64()) {
        let now_ms = current_time_ms();
        JobSchedule::At {
            timestamp_ms: now_ms + delay * 1000,
        }
    } else if let Some(cron_expr) = job_data.get("cron").and_then(|v| v.as_str()) {
        let tz = job_data
            .get("timezone")
            .and_then(|v| v.as_str())
            .unwrap_or("Asia/Tokyo");
        JobSchedule::Cron {
            expression: cron_expr.to_string(),
            timezone: tz.to_string(),
        }
    } else if let Some(interval) = job_data.get("interval_secs").and_then(|v| v.as_u64()) {
        JobSchedule::Every {
            interval_secs: interval,
        }
    } else if let Some(ts) = job_data.get("timestamp_ms").and_then(|v| v.as_u64()) {
        JobSchedule::At { timestamp_ms: ts }
    } else {
        return error_response(&req.session_id, "No schedule specified");
    };

    let one_shot = job_data
        .get("one_shot")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let job = SchedulerJob::new(
        name,
        channel,
        target_id,
        &req.session_id,
        "agent", // created_by
        message,
        schedule,
        one_shot, // delete_after_run
        JobType::User,
    );

    let job_id = job.id.clone();
    match store.insert(job).await {
        Ok(()) => SchedulerResponse {
            msg_type: "scheduler_response".into(),
            session_id: req.session_id.clone(),
            success: true,
            job_id: Some(job_id),
            error: None,
            jobs: None,
        },
        Err(e) => error_response(&req.session_id, &e.to_string()),
    }
}

async fn handle_scheduler_list(store: &JobStore, req: &SchedulerRequest) -> SchedulerResponse {
    let jobs = store.list_for_session(&req.session_id).await;
    let job_values: Vec<serde_json::Value> = jobs
        .iter()
        .map(|j| serde_json::to_value(j).unwrap_or_default())
        .collect();

    SchedulerResponse {
        msg_type: "scheduler_response".into(),
        session_id: req.session_id.clone(),
        success: true,
        job_id: None,
        error: None,
        jobs: Some(job_values),
    }
}

async fn handle_scheduler_delete(store: &JobStore, req: &SchedulerRequest) -> SchedulerResponse {
    let job_id = match &req.job_id {
        Some(id) => id,
        None => return error_response(&req.session_id, "Missing job_id"),
    };

    match store.remove(job_id).await {
        Ok(Some(_)) => SchedulerResponse {
            msg_type: "scheduler_response".into(),
            session_id: req.session_id.clone(),
            success: true,
            job_id: Some(job_id.clone()),
            error: None,
            jobs: None,
        },
        Ok(None) => error_response(
            &req.session_id,
            &format!("Job not found: {}", job_id),
        ),
        Err(e) => error_response(&req.session_id, &e.to_string()),
    }
}

fn error_response(session_id: &str, error: &str) -> SchedulerResponse {
    SchedulerResponse {
        msg_type: "scheduler_response".into(),
        session_id: session_id.to_string(),
        success: false,
        job_id: None,
        error: Some(error.to_string()),
        jobs: None,
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

    #[test]
    fn test_scheduler_trigger_message_serialization() {
        let trigger = SchedulerTriggerMessage {
            msg_type: "scheduler_trigger".to_string(),
            session_id: "sess-123".to_string(),
            trigger_type: "reminder".to_string(),
            job_id: "abcd1234".to_string(),
            message: "Wake up!".to_string(),
            channel: "Telegram".to_string(),
            target_id: "12345".to_string(),
            permission: "Admin".to_string(),
        };

        let json = serde_json::to_string(&trigger).expect("serialize");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse");

        assert_eq!(parsed["type"], "scheduler_trigger");
        assert_eq!(parsed["session_id"], "sess-123");
        assert_eq!(parsed["trigger_type"], "reminder");
        assert_eq!(parsed["job_id"], "abcd1234");
        assert_eq!(parsed["message"], "Wake up!");
        assert_eq!(parsed["channel"], "Telegram");
        assert_eq!(parsed["target_id"], "12345");
        assert_eq!(parsed["permission"], "Admin");
    }

    #[test]
    fn test_scheduler_request_deserialization() {
        let json = r#"{
            "type": "scheduler_request",
            "session_id": "sess-456",
            "action": "create",
            "job": {"name": "morning alarm", "delay_seconds": 300}
        }"#;

        let req: SchedulerRequest = serde_json::from_str(json).expect("deserialize");
        assert_eq!(req.msg_type, "scheduler_request");
        assert_eq!(req.session_id, "sess-456");
        assert_eq!(req.action, "create");
        assert!(req.job.is_some());
        assert!(req.job_id.is_none());

        let job_data = req.job.unwrap();
        assert_eq!(job_data["name"], "morning alarm");
        assert_eq!(job_data["delay_seconds"], 300);
    }

    #[test]
    fn test_scheduler_request_deserialization_delete() {
        let json = r#"{
            "type": "scheduler_request",
            "session_id": "sess-789",
            "action": "delete",
            "job_id": "abcd1234"
        }"#;

        let req: SchedulerRequest = serde_json::from_str(json).expect("deserialize");
        assert_eq!(req.action, "delete");
        assert_eq!(req.job_id, Some("abcd1234".to_string()));
        assert!(req.job.is_none());
    }

    #[test]
    fn test_scheduler_request_deserialization_list() {
        let json = r#"{
            "type": "scheduler_request",
            "session_id": "sess-list",
            "action": "list"
        }"#;

        let req: SchedulerRequest = serde_json::from_str(json).expect("deserialize");
        assert_eq!(req.action, "list");
        assert!(req.job.is_none());
        assert!(req.job_id.is_none());
    }

    #[test]
    fn test_scheduler_response_serialization_success() {
        let resp = SchedulerResponse {
            msg_type: "scheduler_response".to_string(),
            session_id: "sess-123".to_string(),
            success: true,
            job_id: Some("abcd1234".to_string()),
            error: None,
            jobs: None,
        };

        let json = serde_json::to_string(&resp).expect("serialize");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse");

        assert_eq!(parsed["type"], "scheduler_response");
        assert_eq!(parsed["success"], true);
        assert_eq!(parsed["job_id"], "abcd1234");
        // error and jobs should be absent (skip_serializing_if)
        assert!(parsed.get("error").is_none());
        assert!(parsed.get("jobs").is_none());
    }

    #[test]
    fn test_scheduler_response_serialization_error() {
        let resp = error_response("sess-err", "Something went wrong");

        let json = serde_json::to_string(&resp).expect("serialize");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse");

        assert_eq!(parsed["success"], false);
        assert_eq!(parsed["error"], "Something went wrong");
        assert!(parsed.get("job_id").is_none());
    }

    #[test]
    fn test_scheduler_response_serialization_with_jobs() {
        let resp = SchedulerResponse {
            msg_type: "scheduler_response".to_string(),
            session_id: "sess-list".to_string(),
            success: true,
            job_id: None,
            error: None,
            jobs: Some(vec![
                serde_json::json!({"id": "j1", "name": "alarm"}),
                serde_json::json!({"id": "j2", "name": "backup"}),
            ]),
        };

        let json = serde_json::to_string(&resp).expect("serialize");
        let parsed: serde_json::Value = serde_json::from_str(&json).expect("parse");

        let jobs = parsed["jobs"].as_array().expect("jobs should be array");
        assert_eq!(jobs.len(), 2);
        assert_eq!(jobs[0]["id"], "j1");
        assert_eq!(jobs[1]["name"], "backup");
    }
}
