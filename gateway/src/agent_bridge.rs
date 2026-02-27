use std::collections::HashMap;
use std::sync::Arc;

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

use koclaw_common::message::IncomingMessage;

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
    /// Base64-encoded audio data (WAV) — sent with "audio" type chunks
    #[serde(default)]
    pub data: Option<String>,
    /// Audio format (e.g. "wav") — sent with "audio" type chunks
    #[serde(default)]
    pub format: Option<String>,
    /// Expression tags extracted from response — sent with "done" chunks
    #[serde(default)]
    pub expressions: Option<Vec<String>>,
}

/// Pending response senders keyed by session_id.
type PendingResponses = Arc<RwLock<HashMap<String, mpsc::Sender<AgentResponseChunk>>>>;

/// Bridge to the Python Agent process via WebSocket.
///
/// The bridge maintains a single WebSocket connection to the Agent.
/// When `chat()` is called, it sends a request and registers a response
/// channel keyed by session_id. The background receiver task dispatches
/// incoming chunks to the appropriate waiting caller.
pub struct AgentBridge {
    agent_url: String,
    sender: Arc<Mutex<Option<futures_util::stream::SplitSink<
        tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>
        >,
        Message
    >>>>,
    pending: PendingResponses,
}

impl AgentBridge {
    pub fn new(agent_url: String) -> Self {
        Self {
            agent_url,
            sender: Arc::new(Mutex::new(None)),
            pending: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Connect to the Python Agent WebSocket server.
    pub async fn connect(&self) -> Result<()> {
        info!(url = %self.agent_url, "Connecting to Agent...");

        let (ws_stream, _) = connect_async(&self.agent_url)
            .await
            .with_context(|| format!("Failed to connect to Agent at {}", self.agent_url))?;

        let (sender, mut receiver) = ws_stream.split();
        *self.sender.lock().await = Some(sender);

        // Clone pending map for the receiver task
        let pending = self.pending.clone();

        // Spawn a task to handle incoming messages from agent
        tokio::spawn(async move {
            while let Some(msg) = receiver.next().await {
                match msg {
                    Ok(Message::Text(text)) => {
                        debug!(text = %text, "Received from Agent");
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

            // Connection lost — clean up all pending senders
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

    /// Check if the bridge is connected.
    pub async fn is_connected(&self) -> bool {
        self.sender.lock().await.is_some()
    }
}
