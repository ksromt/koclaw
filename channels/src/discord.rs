//! Discord channel implementation via WebSocket Gateway.
//!
//! Connects to `wss://gateway.discord.gg/?v=10&encoding=json` using the
//! same Channel trait as Telegram/QQ. Network footprint: single outbound
//! WSS connection on port 443, identical to the Discord desktop client.

use std::sync::Arc;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

const DISCORD_API_BASE: &str = "https://discord.com/api/v10";
const DISCORD_GATEWAY_URL: &str = "wss://gateway.discord.gg/?v=10&encoding=json";

/// Discord Gateway opcodes.
mod opcode {
    pub const DISPATCH: u8 = 0;
    pub const HEARTBEAT: u8 = 1;
    pub const IDENTIFY: u8 = 2;
    pub const RECONNECT: u8 = 7;
    pub const INVALID_SESSION: u8 = 9;
    pub const HELLO: u8 = 10;
    pub const HEARTBEAT_ACK: u8 = 11;
}

/// A Discord Gateway payload.
#[derive(Debug, Deserialize)]
struct GatewayPayload {
    op: u8,
    d: Option<serde_json::Value>,
    s: Option<u64>,
    t: Option<String>,
}

#[derive(Debug, Serialize)]
struct GatewayCommand {
    op: u8,
    d: serde_json::Value,
}

/// Discord message object (subset of fields we care about).
#[derive(Debug, Deserialize)]
struct DiscordMessage {
    id: String,
    channel_id: String,
    content: String,
    author: DiscordUser,
    guild_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DiscordUser {
    id: String,
    username: String,
    bot: Option<bool>,
}

pub struct DiscordChannel {
    token: String,
    http_client: reqwest::Client,
}

impl DiscordChannel {
    pub fn new(token: String) -> Self {
        Self {
            token,
            http_client: reqwest::Client::new(),
        }
    }

    /// Connect to Discord Gateway and listen for events.
    async fn run_gateway(&self, router: Arc<dyn MessageRouter>) -> Result<()> {
        use futures_util::{SinkExt, StreamExt};
        use tokio_tungstenite::tungstenite::Message;

        info!("Connecting to Discord Gateway...");

        let (ws_stream, _) = tokio_tungstenite::connect_async(DISCORD_GATEWAY_URL)
            .await
            .context("Failed to connect to Discord Gateway")?;

        let (mut write, mut read) = ws_stream.split();

        // Step 1: Receive HELLO
        let hello = read
            .next()
            .await
            .ok_or_else(|| anyhow::anyhow!("Gateway closed before HELLO"))?
            .context("Failed to read HELLO")?;

        let hello_payload: GatewayPayload = match hello {
            Message::Text(text) => serde_json::from_str(&text)?,
            _ => anyhow::bail!("Expected text frame for HELLO"),
        };

        if hello_payload.op != opcode::HELLO {
            anyhow::bail!("Expected HELLO (op 10), got op {}", hello_payload.op);
        }

        let heartbeat_interval = hello_payload
            .d
            .as_ref()
            .and_then(|d| d["heartbeat_interval"].as_u64())
            .unwrap_or(41250);

        info!(
            interval_ms = heartbeat_interval,
            "Received HELLO from Discord"
        );

        // Step 2: Send IDENTIFY
        // Intents: GUILD_MESSAGES (1 << 9) | MESSAGE_CONTENT (1 << 15) | DIRECT_MESSAGES (1 << 12)
        let intents = (1 << 9) | (1 << 15) | (1 << 12);
        let identify = GatewayCommand {
            op: opcode::IDENTIFY,
            d: serde_json::json!({
                "token": self.token,
                "intents": intents,
                "properties": {
                    "os": "linux",
                    "browser": "koclaw",
                    "device": "koclaw"
                }
            }),
        };

        write
            .send(Message::Text(serde_json::to_string(&identify)?.into()))
            .await?;

        // Step 3: Spawn heartbeat task
        let heartbeat_interval_dur = std::time::Duration::from_millis(heartbeat_interval);
        let sequence = Arc::new(tokio::sync::Mutex::new(None::<u64>));
        let seq_heartbeat = sequence.clone();

        let write_shared = Arc::new(tokio::sync::Mutex::new(write));
        let write_for_heartbeat = write_shared.clone();

        tokio::spawn(async move {
            let mut interval = tokio::time::interval(heartbeat_interval_dur);
            loop {
                interval.tick().await;
                let seq = *seq_heartbeat.lock().await;
                let hb = GatewayCommand {
                    op: opcode::HEARTBEAT,
                    d: match seq {
                        Some(s) => serde_json::json!(s),
                        None => serde_json::Value::Null,
                    },
                };
                let mut writer = write_for_heartbeat.lock().await;
                if writer
                    .send(Message::Text(serde_json::to_string(&hb).unwrap().into()))
                    .await
                    .is_err()
                {
                    warn!("Heartbeat send failed, connection may be lost");
                    break;
                }
                debug!("Sent heartbeat");
            }
        });

        // Step 4: Event loop
        info!("Discord Gateway connected, listening for events...");

        while let Some(msg) = read.next().await {
            let msg = match msg {
                Ok(Message::Text(text)) => text,
                Ok(Message::Close(_)) => {
                    info!("Discord Gateway connection closed");
                    break;
                }
                Err(e) => {
                    error!(error = %e, "Discord Gateway error");
                    break;
                }
                _ => continue,
            };

            let payload: GatewayPayload = match serde_json::from_str(&msg) {
                Ok(p) => p,
                Err(e) => {
                    warn!(error = %e, "Failed to parse Gateway payload");
                    continue;
                }
            };

            // Update sequence number
            if let Some(s) = payload.s {
                *sequence.lock().await = Some(s);
            }

            match payload.op {
                opcode::DISPATCH => {
                    if let Some(ref event_name) = payload.t {
                        match event_name.as_str() {
                            "MESSAGE_CREATE" => {
                                if let Some(ref data) = payload.d {
                                    self.handle_message(data, &router).await;
                                }
                            }
                            "READY" => {
                                info!("Discord Gateway READY");
                            }
                            _ => {
                                debug!(event = %event_name, "Unhandled Discord event");
                            }
                        }
                    }
                }
                opcode::HEARTBEAT_ACK => {
                    debug!("Heartbeat acknowledged");
                }
                opcode::RECONNECT => {
                    warn!("Discord requested reconnect");
                    break;
                }
                opcode::INVALID_SESSION => {
                    warn!("Invalid session, will reconnect");
                    break;
                }
                _ => {
                    debug!(op = payload.op, "Unhandled Gateway opcode");
                }
            }
        }

        Ok(())
    }

    /// Handle a MESSAGE_CREATE event from Discord.
    async fn handle_message(
        &self,
        data: &serde_json::Value,
        router: &Arc<dyn MessageRouter>,
    ) {
        let msg: DiscordMessage = match serde_json::from_value(data.clone()) {
            Ok(m) => m,
            Err(e) => {
                warn!(error = %e, "Failed to parse Discord message");
                return;
            }
        };

        // Ignore bot messages (including our own)
        if msg.author.bot.unwrap_or(false) {
            return;
        }

        debug!(
            user = %msg.author.username,
            channel_id = %msg.channel_id,
            "Received Discord message"
        );

        let session_id = match &msg.guild_id {
            Some(guild) => format!("dc:{}:{}", guild, msg.channel_id),
            None => format!("dc:dm:{}", msg.channel_id),
        };

        let incoming = IncomingMessage {
            id: msg.id,
            channel: ChannelType::Discord,
            user_id: format!("dc:{}", msg.author.id),
            display_name: Some(msg.author.username),
            text: Some(msg.content),
            attachments: vec![],
            permission: PermissionLevel::Authenticated,
            session_id,
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        };

        if let Err(e) = router.route(incoming).await {
            error!(error = %e, "Failed to route Discord message");
        }
    }

    /// Send a text message to a Discord channel via REST API.
    async fn send_text(
        &self,
        channel_id: &str,
        text: &str,
        reply_to: Option<&str>,
    ) -> Result<()> {
        let url = format!("{}/channels/{}/messages", DISCORD_API_BASE, channel_id);

        let mut body = serde_json::json!({
            "content": text
        });

        if let Some(ref_id) = reply_to {
            body["message_reference"] = serde_json::json!({
                "message_id": ref_id
            });
        }

        let resp = self
            .http_client
            .post(&url)
            .header("Authorization", format!("Bot {}", self.token))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .context("Failed to send Discord message")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            warn!(status = %status, body = %body, "Discord API error");
        }

        Ok(())
    }
}

impl Channel for DiscordChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.run_gateway(router))
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        let reply_to = msg.reply_to.clone();
        Box::pin(async move {
            self.send_text(
                &target_id,
                text.as_deref().unwrap_or(""),
                reply_to.as_deref(),
            )
            .await
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::Discord
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}
