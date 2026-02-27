//! Tool sandbox for Agent command and filesystem access control.
//!
//! Validates that all filesystem paths stay within a root directory
//! and that only explicitly allowed commands can be executed.

use std::path::{Path, PathBuf};

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};

/// Sandbox configuration for Agent tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxConfig {
    /// Root directory for filesystem access (all paths resolved relative to this)
    pub root: PathBuf,
    /// Allowed shell commands (empty = no commands allowed)
    pub allowed_commands: Vec<String>,
    /// Maximum execution time per tool invocation in seconds
    pub timeout_seconds: u64,
    /// Maximum file size for read/write operations in bytes
    pub max_file_size: u64,
}

impl Default for SandboxConfig {
    fn default() -> Self {
        Self {
            root: PathBuf::from("./workspace"),
            allowed_commands: vec![],
            timeout_seconds: 30,
            max_file_size: 10 * 1024 * 1024, // 10 MB
        }
    }
}

impl SandboxConfig {
    /// Validate that a path is within the sandbox root.
    ///
    /// Returns the normalized path if valid.
    pub fn validate_path(&self, path: &str) -> Result<PathBuf> {
        let requested = self.root.join(path);
        let normalized = normalize_path(&requested);
        let root_normalized = normalize_path(&self.root);

        if !normalized.starts_with(&root_normalized) {
            bail!(
                "Path escape attempt: '{}' resolves outside sandbox root '{}'",
                path,
                self.root.display()
            );
        }

        Ok(normalized)
    }

    /// Check if a command is in the allowlist.
    pub fn validate_command(&self, command: &str) -> Result<()> {
        let base_cmd = command.split_whitespace().next().unwrap_or("");

        if !self.allowed_commands.iter().any(|c| c == base_cmd) {
            bail!(
                "Command '{}' not in sandbox allowlist: {:?}",
                base_cmd,
                self.allowed_commands
            );
        }

        Ok(())
    }
}

/// Normalize a path without requiring it to exist (no canonicalize).
fn normalize_path(path: &Path) -> PathBuf {
    let mut components = Vec::new();
    for component in path.components() {
        match component {
            std::path::Component::ParentDir => {
                components.pop();
            }
            std::path::Component::CurDir => {}
            _ => {
                components.push(component);
            }
        }
    }
    components.iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_sandbox() -> SandboxConfig {
        SandboxConfig {
            root: PathBuf::from("/workspace"),
            allowed_commands: vec!["ls".to_string(), "cat".to_string(), "grep".to_string()],
            timeout_seconds: 30,
            max_file_size: 1024 * 1024,
        }
    }

    #[test]
    fn test_valid_path() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("docs/readme.md");
        assert!(result.is_ok());
        let path = result.unwrap();
        assert!(path.starts_with("/workspace"));
    }

    #[test]
    fn test_path_escape_blocked() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("../../etc/passwd");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("escape"));
    }

    #[test]
    fn test_path_escape_via_dotdot() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("subdir/../../etc/shadow");
        assert!(result.is_err());
    }

    #[test]
    fn test_valid_command() {
        let sandbox = test_sandbox();
        assert!(sandbox.validate_command("ls -la").is_ok());
        assert!(sandbox.validate_command("cat file.txt").is_ok());
        assert!(sandbox.validate_command("grep pattern file").is_ok());
    }

    #[test]
    fn test_blocked_command() {
        let sandbox = test_sandbox();
        assert!(sandbox.validate_command("rm -rf /").is_err());
        assert!(sandbox.validate_command("curl evil.com").is_err());
    }

    #[test]
    fn test_default_sandbox_has_no_commands() {
        let sandbox = SandboxConfig::default();
        assert!(sandbox.validate_command("ls").is_err());
    }
}
