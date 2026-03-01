//! Telegram Bot API channel implementation.
//!
//! Uses the Telegram Bot API via HTTP polling (development) or webhook (production).
//! See docs/channels/telegram.md for setup guide.
//!
//! Telegram Bot API reference: https://core.telegram.org/bots/api

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use serde::Deserialize;
use tracing::{debug, error, info};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{Attachment, AttachmentType, IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

const TELEGRAM_API_BASE: &str = "https://api.telegram.org/bot";
const REJECT_COOLDOWN: Duration = Duration::from_secs(30 * 60); // 30 minutes
const REJECT_MESSAGE: &str = "Sorry, this bot is currently in private mode and not accepting conversations from new users. 🔒";

/// Telegram channel implementation using Bot API.
pub struct TelegramChannel {
    token: String,
    client: reqwest::Client,
    allowed_users: Vec<i64>,
    /// Telegram user ID of the admin/owner — recognized as "shin" (先生).
    admin_user: Option<i64>,
    /// Tracks last rejection reply time per user to avoid spamming.
    rejected_users: Mutex<HashMap<i64, Instant>>,
}

impl TelegramChannel {
    pub fn new(token: String, allowed_users: Vec<i64>, admin_user: Option<i64>) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .expect("Failed to build HTTP client");

        Self {
            token,
            client,
            allowed_users,
            admin_user,
            rejected_users: Mutex::new(HashMap::new()),
        }
    }

    /// Build a Telegram API URL for the given method.
    fn api_url(&self, method: &str) -> String {
        format!("{}{}/{}", TELEGRAM_API_BASE, self.token, method)
    }

    /// Start long-polling for updates.
    pub async fn start_polling(&self, router: Arc<dyn MessageRouter>) -> Result<()> {
        info!("Telegram polling started");
        let mut offset: i64 = 0;

        loop {
            match self.get_updates(offset).await {
                Ok(updates) => {
                    for update in updates {
                        if let Some(new_offset) = update.update_id.checked_add(1) {
                            offset = new_offset;
                        }

                        if let Some(message) = update.message {
                            if let Err(e) = self.process_message(message, &router).await {
                                error!(error = %e, "Failed to process Telegram message");
                            }
                        }
                    }
                }
                Err(e) => {
                    error!(error = %e, "Telegram getUpdates failed");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                }
            }
        }
    }

    /// Call getUpdates to fetch new messages.
    async fn get_updates(&self, offset: i64) -> Result<Vec<TgUpdate>> {
        let url = self.api_url("getUpdates");
        let params = serde_json::json!({
            "offset": offset,
            "timeout": 30,
            "allowed_updates": ["message"]
        });

        let resp: TgApiResponse<Vec<TgUpdate>> = self
            .client
            .post(&url)
            .json(&params)
            .send()
            .await?
            .json()
            .await?;

        if resp.ok {
            Ok(resp.result.unwrap_or_default())
        } else {
            anyhow::bail!(
                "Telegram API error: {}",
                resp.description.unwrap_or_default()
            )
        }
    }

    /// Convert a Telegram message to IncomingMessage and route it.
    async fn process_message(
        &self,
        msg: TgMessage,
        router: &Arc<dyn MessageRouter>,
    ) -> Result<()> {
        let user_id = msg.from.as_ref().map(|u| u.id).unwrap_or(0);

        // Check allowed users — reply once then cooldown for 30 minutes
        if !self.allowed_users.is_empty() && !self.allowed_users.contains(&user_id) {
            let should_reply = {
                let mut rejected = self.rejected_users.lock().unwrap();
                match rejected.get(&user_id) {
                    Some(last_time) if last_time.elapsed() < REJECT_COOLDOWN => false,
                    _ => {
                        rejected.insert(user_id, Instant::now());
                        true
                    }
                }
            };

            if should_reply {
                info!(user_id, "Unauthorized user, sending rejection message");
                self.send_text(&msg.chat.id.to_string(), REJECT_MESSAGE).await.ok();
            } else {
                debug!(user_id, "Unauthorized user in cooldown, ignoring");
            }
            return Ok(());
        }

        let is_admin = self.admin_user.is_some_and(|admin_id| admin_id == user_id);

        // For admin user, set display_name to "shin" so the Router can inject identity context
        let display_name = if is_admin {
            Some("shin".to_string())
        } else {
            msg.from.as_ref().map(|u| {
                let mut name = u.first_name.clone();
                if let Some(ref last) = u.last_name {
                    name.push(' ');
                    name.push_str(last);
                }
                name
            })
        };

        let mut attachments = Vec::new();

        // Handle voice messages
        if let Some(voice) = &msg.voice {
            if let Ok(url) = self.get_file_url(&voice.file_id).await {
                attachments.push(Attachment {
                    attachment_type: AttachmentType::Voice,
                    url,
                    mime_type: voice.mime_type.clone(),
                    file_name: None,
                    size: Some(voice.file_size.unwrap_or(0)),
                });
            }
        }

        // Handle photos (take the largest size)
        if let Some(photos) = &msg.photo {
            if let Some(largest) = photos.last() {
                if let Ok(url) = self.get_file_url(&largest.file_id).await {
                    attachments.push(Attachment {
                        attachment_type: AttachmentType::Image,
                        url,
                        mime_type: Some("image/jpeg".to_string()),
                        file_name: None,
                        size: None,
                    });
                }
            }
        }

        // Handle documents
        if let Some(doc) = &msg.document {
            if let Ok(url) = self.get_file_url(&doc.file_id).await {
                attachments.push(Attachment {
                    attachment_type: AttachmentType::File,
                    url,
                    mime_type: doc.mime_type.clone(),
                    file_name: doc.file_name.clone(),
                    size: Some(doc.file_size.unwrap_or(0)),
                });
            }
        }

        let permission = if is_admin {
            PermissionLevel::Admin
        } else {
            PermissionLevel::Authenticated
        };

        let incoming = IncomingMessage {
            id: msg.message_id.to_string(),
            channel: ChannelType::Telegram,
            user_id: user_id.to_string(),
            display_name,
            text: msg.text.or(msg.caption),
            attachments,
            permission,
            session_id: format!("tg:{}", msg.chat.id),
            timestamp: msg.date as u64,
        };

        router.route(incoming).await
    }

    /// Send a plain text message directly (no LLM involved).
    async fn send_text(&self, chat_id: &str, text: &str) -> Result<()> {
        let url = self.api_url("sendMessage");
        let params = serde_json::json!({
            "chat_id": chat_id,
            "text": text,
        });

        let resp: TgApiResponse<TgMessage> = self
            .client
            .post(&url)
            .json(&params)
            .send()
            .await
            .context("Failed to send rejection message")?
            .json()
            .await?;

        if !resp.ok {
            error!(
                error = resp.description.unwrap_or_default(),
                "Failed to send rejection message"
            );
        }
        Ok(())
    }

    /// Get a download URL for a Telegram file.
    async fn get_file_url(&self, file_id: &str) -> Result<String> {
        let url = self.api_url("getFile");
        let params = serde_json::json!({ "file_id": file_id });

        let resp: TgApiResponse<TgFile> = self
            .client
            .post(&url)
            .json(&params)
            .send()
            .await?
            .json()
            .await?;

        if let Some(file) = resp.result {
            if let Some(path) = file.file_path {
                return Ok(format!(
                    "https://api.telegram.org/file/bot{}/{}",
                    self.token, path
                ));
            }
        }

        anyhow::bail!("Failed to get file URL for {}", file_id)
    }
}

impl Channel for TelegramChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.start_polling(router))
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        // Clone data from msg before entering async block to avoid lifetime issues
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        let reply_to = msg.reply_to.clone();

        Box::pin(async move {
            let url = self.api_url("sendMessage");

            let mut params = serde_json::json!({
                "chat_id": target_id,
                "parse_mode": "Markdown",
            });

            if let Some(ref text) = text {
                params["text"] = serde_json::Value::String(text.clone());
            }

            if let Some(ref reply_to) = reply_to {
                params["reply_to_message_id"] =
                    serde_json::Value::Number(reply_to.parse::<i64>().unwrap_or(0).into());
            }

            let resp: TgApiResponse<TgMessage> = self
                .client
                .post(&url)
                .json(&params)
                .send()
                .await
                .context("Failed to send Telegram message")?
                .json()
                .await?;

            if !resp.ok {
                anyhow::bail!(
                    "Telegram sendMessage failed: {}",
                    resp.description.unwrap_or_default()
                );
            }

            Ok(())
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::Telegram
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}

// --- Telegram API types ---

#[derive(Debug, Deserialize)]
struct TgApiResponse<T> {
    ok: bool,
    result: Option<T>,
    description: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TgUpdate {
    update_id: i64,
    message: Option<TgMessage>,
}

#[derive(Debug, Deserialize)]
struct TgMessage {
    message_id: i64,
    from: Option<TgUser>,
    chat: TgChat,
    date: i64,
    text: Option<String>,
    caption: Option<String>,
    voice: Option<TgVoice>,
    photo: Option<Vec<TgPhotoSize>>,
    document: Option<TgDocument>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct TgUser {
    id: i64,
    first_name: String,
    last_name: Option<String>,
    username: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TgChat {
    id: i64,
}

#[derive(Debug, Deserialize)]
struct TgVoice {
    file_id: String,
    file_size: Option<u64>,
    mime_type: Option<String>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct TgPhotoSize {
    file_id: String,
    width: i32,
    height: i32,
}

#[derive(Debug, Deserialize)]
struct TgDocument {
    file_id: String,
    file_name: Option<String>,
    mime_type: Option<String>,
    file_size: Option<u64>,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct TgFile {
    file_id: String,
    file_path: Option<String>,
}
