use serde::{Deserialize, Serialize};

use crate::channel::ChannelType;
use crate::permission::PermissionLevel;

/// A message received from any channel, normalized to a common format.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomingMessage {
    /// Unique message ID (from the source channel)
    pub id: String,
    /// Which channel this message came from
    pub channel: ChannelType,
    /// User identifier (channel-specific, e.g., telegram user ID)
    pub user_id: String,
    /// Display name of the sender
    pub display_name: Option<String>,
    /// Text content of the message
    pub text: Option<String>,
    /// Attached media (images, voice, files)
    pub attachments: Vec<Attachment>,
    /// Permission level determined by the channel
    pub permission: PermissionLevel,
    /// Session ID for conversation continuity
    pub session_id: String,
    /// Timestamp (Unix milliseconds)
    pub timestamp: u64,
}

/// A message to send back through a channel.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutgoingMessage {
    /// Target channel
    pub channel: ChannelType,
    /// Target user/chat ID
    pub target_id: String,
    /// Text content (supports channel-specific formatting)
    pub text: Option<String>,
    /// Attached media to send
    pub attachments: Vec<Attachment>,
    /// Reply to a specific message ID (if supported by channel)
    pub reply_to: Option<String>,
}

/// Media attachment (image, voice, file).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Attachment {
    pub attachment_type: AttachmentType,
    /// URL or local file path
    pub url: String,
    /// MIME type
    pub mime_type: Option<String>,
    /// File name
    pub file_name: Option<String>,
    /// File size in bytes
    pub size: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AttachmentType {
    Image,
    Voice,
    Video,
    File,
}
