use thiserror::Error;

#[derive(Error, Debug)]
pub enum KoclawError {
    #[error("channel error ({channel}): {message}")]
    Channel { channel: String, message: String },

    #[error("encryption error: {0}")]
    Encryption(String),

    #[error("authentication error: {0}")]
    Auth(String),

    #[error("permission denied: {action} requires {required:?}, got {actual:?}")]
    PermissionDenied {
        action: String,
        required: crate::permission::PermissionLevel,
        actual: crate::permission::PermissionLevel,
    },

    #[error("agent error: {0}")]
    Agent(String),

    #[error("configuration error: {0}")]
    Config(String),

    #[error("not found: {0}")]
    NotFound(String),
}
