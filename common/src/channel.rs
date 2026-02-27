use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::message::{IncomingMessage, OutgoingMessage};
use crate::permission::PermissionLevel;

/// Boxed future type alias for dyn-compatible async traits.
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Identifies which channel a message belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ChannelType {
    Telegram,
    QQ,
    Discord,
    WebSocket,
    WebPublic,
}

impl std::fmt::Display for ChannelType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ChannelType::Telegram => write!(f, "telegram"),
            ChannelType::QQ => write!(f, "qq"),
            ChannelType::Discord => write!(f, "discord"),
            ChannelType::WebSocket => write!(f, "websocket"),
            ChannelType::WebPublic => write!(f, "web-public"),
        }
    }
}

/// Trait for message routing — receives incoming messages from channels.
pub trait MessageRouter: Send + Sync {
    fn route(&self, message: IncomingMessage) -> BoxFuture<'_, Result<()>>;
}

/// Trait that all communication channels must implement.
///
/// To add a new channel:
/// 1. Add a variant to `ChannelType`
/// 2. Implement this trait
/// 3. Register in the channel registry (config-driven)
///
/// No existing code needs to be modified.
pub trait Channel: Send + Sync {
    /// Start listening for messages on this channel.
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>>;

    /// Send a message through this channel.
    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>>;

    /// The type of this channel.
    fn channel_type(&self) -> ChannelType;

    /// Default permission level for messages from this channel.
    fn default_permission(&self) -> PermissionLevel;
}
