use serde::{Deserialize, Serialize};

/// Permission levels control what actions an agent can take
/// depending on which channel the message originated from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum PermissionLevel {
    /// Blog widget, public web — chat only, no tools, no private data
    Public = 0,
    /// Telegram/QQ/Discord private chat — full tools, memory, file access within sandbox
    Authenticated = 1,
    /// Desktop app, designated admin users — unrestricted
    Admin = 2,
}

impl PermissionLevel {
    pub fn can_execute_tools(&self) -> bool {
        *self >= PermissionLevel::Authenticated
    }

    pub fn can_access_memory(&self) -> bool {
        *self >= PermissionLevel::Authenticated
    }

    pub fn can_modify_config(&self) -> bool {
        *self >= PermissionLevel::Admin
    }

    pub fn can_access_filesystem(&self) -> bool {
        *self >= PermissionLevel::Authenticated
    }
}
