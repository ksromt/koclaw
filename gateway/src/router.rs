use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{Attachment, AttachmentType, IncomingMessage, OutgoingMessage};
use koclaw_common::persona::Persona;

use crate::agent_bridge::{AgentBridge, ChatContext};

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
    persona: Persona,
}

impl Router {
    pub fn new(bridge: Arc<AgentBridge>) -> Self {
        Self::with_persona(bridge, Persona::kokoron())
    }

    pub fn with_persona(bridge: Arc<AgentBridge>, persona: Persona) -> Self {
        Self {
            bridge,
            channels: RwLock::new(HashMap::new()),
            persona,
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

    /// Send a proactive message to a specific channel and target.
    ///
    /// Used by the scheduler to deliver reminders and heartbeat notifications.
    /// Unlike `send_response`, this is not in response to an incoming message --
    /// it originates from the scheduler firing a job.
    pub async fn send_proactive_message(
        &self,
        channel_type: ChannelType,
        target_id: &str,
        text: &str,
    ) -> Result<()> {
        // Strip expression tags for non-WebSocket channels
        let clean_text = if channel_type != ChannelType::WebSocket {
            strip_expression_tags(text)
        } else {
            text.to_string()
        };

        let channels = self.channels.read().await;
        if let Some(channel) = channels.get(&channel_type) {
            let msg = OutgoingMessage {
                channel: channel_type,
                target_id: target_id.to_string(),
                text: Some(clean_text),
                attachments: Vec::new(),
                reply_to: None,
            };
            channel.send_message(&msg).await?;
            Ok(())
        } else {
            anyhow::bail!("No channel registered for {:?}", channel_type);
        }
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

            // Build system prompt with identity context for admin users
            let mut system_prompt = self.persona.system_prompt(message.channel);
            if let Some(ref name) = message.display_name {
                if name == "shin" {
                    system_prompt.push_str(
                        "\n\n現在あなたが話している相手はshin先生本人です。\
                         「先生」と直接呼んでください。「shin先生」ではなく「先生」です。"
                    );
                }
            }

            let context = ChatContext {
                system_prompt: Some(system_prompt),
                ..Default::default()
            };

            let mut rx = match self.bridge.chat(&message, context).await {
                Ok(rx) => rx,
                Err(e) => {
                    error!(error = %e, "Failed to send to Agent");
                    return Err(e);
                }
            };

            // Step 3: Collect streaming response + metadata
            let mut full_response = String::new();
            let mut expressions: Vec<String> = Vec::new();
            let mut audio_data: Option<String> = None;
            let mut audio_format: Option<String> = None;

            while let Some(chunk) = rx.recv().await {
                match chunk.msg_type.as_str() {
                    "text_chunk" => {
                        if let Some(content) = &chunk.content {
                            full_response.push_str(content);
                        }
                    }
                    "audio" => {
                        audio_data = chunk.data;
                        audio_format = chunk.format;
                    }
                    "done" => {
                        if let Some(exprs) = chunk.expressions {
                            expressions = exprs;
                        }
                        debug!(
                            session = %message.session_id,
                            expressions = ?expressions,
                            "Agent response complete"
                        );
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
                let target_id = message
                    .session_id
                    .split_once(':')
                    .map(|(_, id)| id)
                    .unwrap_or(&message.session_id);

                // Strip expression tags for non-Live2D channels (Telegram, QQ, Discord).
                // WebSocket clients use these for Live2D animation; others don't.
                if message.channel != ChannelType::WebSocket {
                    full_response = strip_expression_tags(&full_response);
                }

                // For WebSocket clients, include audio attachment if available
                let mut attachments = Vec::new();
                if message.channel == ChannelType::WebSocket {
                    if let Some(audio) = audio_data {
                        attachments.push(Attachment {
                            attachment_type: AttachmentType::Voice,
                            url: audio,
                            mime_type: Some(
                                audio_format.unwrap_or_else(|| "audio/wav".to_string()),
                            ),
                            file_name: None,
                            size: None,
                        });
                    }
                }

                let channels = self.channels.read().await;
                if let Some(channel) = channels.get(&message.channel) {
                    let msg = OutgoingMessage {
                        channel: message.channel,
                        target_id: target_id.to_string(),
                        text: Some(full_response),
                        attachments,
                        reply_to: Some(message.id.clone()),
                    };
                    channel.send_message(&msg).await?;
                } else {
                    warn!(%message.channel, "No channel registered for response delivery");
                }
            }

            Ok(())
        })
    }
}

/// Strip bracketed expression tags (e.g. `[joy]`, `[smile]`, `[wink]`) from text.
///
/// Removes any `[single_word]` pattern where the word is purely alphabetic.
/// This catches both known Live2D expressions and LLM-invented ones.
/// Multi-word brackets like `[see this link]` are left intact.
fn strip_expression_tags(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        if chars[i] == '[' {
            // Look for closing bracket
            if let Some(end) = chars[i + 1..].iter().position(|&c| c == ']') {
                let inner: String = chars[i + 1..i + 1 + end].iter().collect();
                // Strip only single-word alphabetic tags (emotion markers)
                if !inner.is_empty() && inner.chars().all(|c| c.is_ascii_alphabetic()) {
                    i += end + 2; // skip past ']'
                    continue;
                }
            }
        }
        result.push(chars[i]);
        i += 1;
    }

    // Collapse double spaces and trim
    while result.contains("  ") {
        result = result.replace("  ", " ");
    }
    result.trim().to_string()
}
