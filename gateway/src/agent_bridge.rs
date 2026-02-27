use std::sync::Arc;

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info};

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
}

#[derive(Debug, Serialize)]
pub struct AttachmentPayload {
    pub attachment_type: String,
    pub url: String,
    pub mime_type: Option<String>,
}

/// Response chunk from Python Agent.
#[derive(Debug, Deserialize)]
pub struct AgentResponseChunk {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub session_id: Option<String>,
    pub content: Option<String>,
}

/// Bridge to the Python Agent process via WebSocket.
pub struct AgentBridge {
    agent_url: String,
    sender: Arc<Mutex<Option<futures_util::stream::SplitSink<
        tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>
        >,
        Message
    >>>>,
}

impl AgentBridge {
    pub fn new(agent_url: String) -> Self {
        Self {
            agent_url,
            sender: Arc::new(Mutex::new(None)),
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

        // Spawn a task to handle incoming messages from agent
        tokio::spawn(async move {
            while let Some(msg) = receiver.next().await {
                match msg {
                    Ok(Message::Text(text)) => {
                        debug!(text = %text, "Received from Agent");
                        // TODO: Route response back to the originating channel
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
        });

        info!("Connected to Agent");
        Ok(())
    }

    /// Send a chat request to the Agent and collect the streamed response.
    pub async fn chat(
        &self,
        message: &IncomingMessage,
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
        };

        let json = serde_json::to_string(&request)?;

        let mut sender_guard = self.sender.lock().await;
        if let Some(sender) = sender_guard.as_mut() {
            sender
                .send(Message::Text(json.into()))
                .await
                .context("Failed to send message to Agent")?;
        } else {
            anyhow::bail!("Not connected to Agent");
        }

        // Create a channel for streaming response chunks
        let (tx, rx) = mpsc::channel(32);

        // TODO: Wire up the receiver from the WebSocket to this channel
        // For now, drop the sender which will signal "done" to the receiver
        drop(tx);

        Ok(rx)
    }

    /// Check if the bridge is connected.
    pub async fn is_connected(&self) -> bool {
        self.sender.lock().await.is_some()
    }
}
