use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};

use crate::agent_bridge::AgentBridge;

/// Routes incoming messages from channels to the agent and back.
///
/// The Router is the central message hub:
/// 1. Receives incoming messages from channels
/// 2. Checks permission levels
/// 3. Forwards to the Agent via AgentBridge
/// 4. Collects streaming responses
/// 5. Sends complete response back through the originating channel
pub struct Router {
    bridge: Arc<AgentBridge>,
    channels: RwLock<HashMap<ChannelType, Arc<dyn Channel>>>,
}

impl Router {
    pub fn new(bridge: Arc<AgentBridge>) -> Self {
        Self {
            bridge,
            channels: RwLock::new(HashMap::new()),
        }
    }

    /// Register a channel for sending responses back.
    pub async fn register_channel(&self, channel: Arc<dyn Channel>) {
        let channel_type = channel.channel_type();
        self.channels.write().await.insert(channel_type, channel);
        info!(%channel_type, "Channel registered in router");
    }

    /// Send a response back through the originating channel.
    async fn send_response(
        &self,
        channel_type: ChannelType,
        target_id: &str,
        text: &str,
        reply_to: Option<&str>,
    ) -> Result<()> {
        let channels = self.channels.read().await;
        if let Some(channel) = channels.get(&channel_type) {
            let msg = OutgoingMessage {
                channel: channel_type,
                target_id: target_id.to_string(),
                text: Some(text.to_string()),
                attachments: Vec::new(),
                reply_to: reply_to.map(String::from),
            };
            channel.send_message(&msg).await?;
        } else {
            warn!(%channel_type, "No channel registered for response delivery");
        }
        Ok(())
    }
}

impl MessageRouter for Router {
    fn route(&self, message: IncomingMessage) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            info!(
                channel = %message.channel,
                user = %message.user_id,
                session = %message.session_id,
                "Routing message"
            );

            // Step 1: Permission enforcement
            let text = match &message.text {
                Some(t) => t.clone(),
                None if !message.attachments.is_empty() => {
                    // Allow attachment-only messages for multimodal
                    String::new()
                }
                None => {
                    debug!("Empty message with no attachments, ignoring");
                    return Ok(());
                }
            };

            // Check for tool execution permission
            if text.starts_with('/') && !message.permission.can_execute_tools() {
                warn!(
                    user = %message.user_id,
                    permission = ?message.permission,
                    "Tool execution denied"
                );
                self.send_response(
                    message.channel,
                    &message.session_id.replace("tg:", "").replace("qq:", ""),
                    "Permission denied: tool execution requires Authenticated or Admin level.",
                    Some(&message.id),
                )
                .await?;
                return Ok(());
            }

            // Step 2: Forward to Agent
            if !self.bridge.is_connected().await {
                warn!("Agent not connected, cannot process message");
                self.send_response(
                    message.channel,
                    &message.session_id.replace("tg:", "").replace("qq:", ""),
                    "Agent is currently unavailable. Please try again later.",
                    Some(&message.id),
                )
                .await?;
                return Ok(());
            }

            let mut rx = match self.bridge.chat(&message).await {
                Ok(rx) => rx,
                Err(e) => {
                    error!(error = %e, "Failed to send to Agent");
                    return Err(e);
                }
            };

            // Step 3: Collect streaming response
            let mut full_response = String::new();
            while let Some(chunk) = rx.recv().await {
                match chunk.msg_type.as_str() {
                    "text_chunk" => {
                        if let Some(content) = &chunk.content {
                            full_response.push_str(content);
                        }
                    }
                    "done" => {
                        debug!(session = %message.session_id, "Agent response complete");
                        break;
                    }
                    "error" => {
                        let err_msg = chunk.content.unwrap_or_else(|| "Unknown error".to_string());
                        error!(error = %err_msg, "Agent returned error");
                        full_response = format!("Error: {err_msg}");
                        break;
                    }
                    other => {
                        debug!(msg_type = other, "Unknown chunk type from Agent");
                    }
                }
            }

            // Step 4: Send response back through originating channel
            if !full_response.is_empty() {
                // Extract the chat/channel ID from session_id (e.g., "tg:12345" → "12345")
                let target_id = message
                    .session_id
                    .split_once(':')
                    .map(|(_, id)| id)
                    .unwrap_or(&message.session_id);

                self.send_response(
                    message.channel,
                    target_id,
                    &full_response,
                    Some(&message.id),
                )
                .await?;
            }

            Ok(())
        })
    }
}
