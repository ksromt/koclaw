//! QQ Bot channel implementation.
//!
//! Uses the QQ Open Platform Bot API.
//! See docs/channels/qq.md for setup guide.
//!
//! QQ Bot API reference: https://bot.q.qq.com/wiki/develop/api-v2/

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use serde::Deserialize;
use tracing::{info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::OutgoingMessage;
use koclaw_common::permission::PermissionLevel;

const QQ_API_BASE: &str = "https://api.sgroup.qq.com";
const QQ_SANDBOX_API_BASE: &str = "https://sandbox.api.sgroup.qq.com";

/// QQ Bot channel implementation.
pub struct QQChannel {
    app_id: String,
    secret: String,
    sandbox: bool,
    client: reqwest::Client,
    access_token: tokio::sync::RwLock<Option<QQAccessToken>>,
}

#[derive(Debug, Clone)]
struct QQAccessToken {
    token: String,
    expires_at: std::time::Instant,
}

impl QQChannel {
    pub fn new(app_id: String, secret: String, sandbox: bool) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("Failed to build HTTP client");

        Self {
            app_id,
            secret,
            sandbox,
            client,
            access_token: tokio::sync::RwLock::new(None),
        }
    }

    fn api_base(&self) -> &str {
        if self.sandbox {
            QQ_SANDBOX_API_BASE
        } else {
            QQ_API_BASE
        }
    }

    /// Obtain or refresh the access token via OAuth2 client credentials.
    async fn ensure_token(&self) -> Result<String> {
        // Check if current token is still valid
        {
            let token = self.access_token.read().await;
            if let Some(ref t) = *token {
                if t.expires_at > std::time::Instant::now() {
                    return Ok(t.token.clone());
                }
            }
        }

        // Request new token
        let resp: QQTokenResponse = self
            .client
            .post("https://bots.qq.com/app/getAppAccessToken")
            .json(&serde_json::json!({
                "appId": self.app_id,
                "clientSecret": self.secret,
            }))
            .send()
            .await
            .context("Failed to request QQ access token")?
            .json()
            .await?;

        let token = resp.access_token;
        let expires_in = resp.expires_in.parse::<u64>().unwrap_or(7200);

        *self.access_token.write().await = Some(QQAccessToken {
            token: token.clone(),
            expires_at: std::time::Instant::now() + Duration::from_secs(expires_in - 60),
        });

        info!("QQ access token refreshed (expires in {}s)", expires_in);
        Ok(token)
    }

    /// Connect to QQ WebSocket gateway for receiving events.
    pub async fn start_websocket(&self, _router: Arc<dyn MessageRouter>) -> Result<()> {
        info!(sandbox = self.sandbox, "QQ channel starting");

        // Get WebSocket gateway URL
        let token = self.ensure_token().await?;
        let gateway_url = self.get_gateway_url(&token).await?;

        info!(url = %gateway_url, "Connecting to QQ WebSocket gateway");

        // TODO: Implement full WebSocket lifecycle:
        // 1. Connect to gateway
        // 2. Send Identify payload with token and intents
        // 3. Handle Dispatch events (AT_MESSAGE_CREATE, DIRECT_MESSAGE_CREATE)
        // 4. Maintain heartbeat
        // 5. Handle reconnection

        warn!("QQ WebSocket gateway connection not yet fully implemented");
        Ok(())
    }

    /// Get the WebSocket gateway URL.
    async fn get_gateway_url(&self, token: &str) -> Result<String> {
        let url = format!("{}/gateway", self.api_base());

        let resp: QQGatewayResponse = self
            .client
            .get(&url)
            .header("Authorization", format!("QQBot {}", token))
            .send()
            .await?
            .json()
            .await?;

        Ok(resp.url)
    }

    /// Send a message to a QQ channel.
    async fn send_channel_message(
        &self,
        channel_id: &str,
        content: &str,
        msg_id: Option<&str>,
    ) -> Result<()> {
        let token = self.ensure_token().await?;
        let url = format!("{}/channels/{}/messages", self.api_base(), channel_id);

        let mut body = serde_json::json!({
            "content": content,
        });

        // msg_id is required when replying to a message
        if let Some(id) = msg_id {
            body["msg_id"] = serde_json::Value::String(id.to_string());
        }

        let resp = self
            .client
            .post(&url)
            .header("Authorization", format!("QQBot {}", token))
            .json(&body)
            .send()
            .await
            .context("Failed to send QQ message")?;

        if !resp.status().is_success() {
            let error_text = resp.text().await.unwrap_or_default();
            anyhow::bail!("QQ send message failed: {}", error_text);
        }

        Ok(())
    }
}

impl Channel for QQChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.start_websocket(router))
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        let reply_to = msg.reply_to.clone();

        Box::pin(async move {
            if let Some(ref text) = text {
                self.send_channel_message(&target_id, text, reply_to.as_deref())
                    .await?;
            }
            Ok(())
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::QQ
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}

// --- QQ API types ---

#[derive(Debug, Deserialize)]
struct QQTokenResponse {
    access_token: String,
    expires_in: String,
}

#[derive(Debug, Deserialize)]
struct QQGatewayResponse {
    url: String,
}
