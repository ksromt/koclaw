use std::path::Path;

use anyhow::{Context, Result};
use serde::Deserialize;

/// Root configuration for the Koclaw Gateway.
#[derive(Debug, Deserialize)]
pub struct KoclawConfig {
    pub gateway: GatewayConfig,
    pub channels: ChannelsConfig,
    #[serde(default)]
    pub providers: ProvidersConfig,
}

#[derive(Debug, Deserialize)]
pub struct GatewayConfig {
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default = "default_agent_url")]
    pub agent_url: String,
    #[serde(default = "default_log_level")]
    pub log_level: String,
    #[serde(default)]
    pub sandbox: SandboxConfig,
}

#[derive(Debug, Deserialize)]
pub struct SandboxConfig {
    #[serde(default = "default_workspace_root")]
    pub workspace_root: String,
    #[serde(default)]
    pub allowed_commands: Vec<String>,
    #[serde(default = "default_max_file_size")]
    pub max_file_size: u64,
}

impl Default for SandboxConfig {
    fn default() -> Self {
        Self {
            workspace_root: default_workspace_root(),
            allowed_commands: vec![],
            max_file_size: default_max_file_size(),
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct ChannelsConfig {
    pub telegram: Option<TelegramConfig>,
    pub qq: Option<QQConfig>,
    pub discord: Option<DiscordConfig>,
}

#[derive(Debug, Deserialize)]
pub struct TelegramConfig {
    #[serde(default)]
    pub enabled: bool,
    pub token: Option<String>,
    pub token_env: Option<String>,
    #[serde(default = "default_polling_mode")]
    pub mode: String,
    pub webhook_url: Option<String>,
    #[serde(default)]
    pub allowed_users: Vec<i64>,
}

impl TelegramConfig {
    /// Resolve the bot token from env var or direct value.
    pub fn resolve_token(&self) -> Result<String> {
        resolve_secret(&self.token, &self.token_env)
            .context("Telegram bot token not configured. Set TELEGRAM_BOT_TOKEN or token in config")
    }
}

#[derive(Debug, Deserialize)]
pub struct QQConfig {
    #[serde(default)]
    pub enabled: bool,
    pub app_id: Option<String>,
    pub app_id_env: Option<String>,
    pub secret: Option<String>,
    pub secret_env: Option<String>,
    #[serde(default = "default_true")]
    pub sandbox: bool,
}

impl QQConfig {
    pub fn resolve_app_id(&self) -> Result<String> {
        resolve_secret(&self.app_id, &self.app_id_env)
            .context("QQ Bot app_id not configured")
    }

    pub fn resolve_secret(&self) -> Result<String> {
        resolve_secret(&self.secret, &self.secret_env)
            .context("QQ Bot secret not configured")
    }
}

#[derive(Debug, Deserialize)]
pub struct DiscordConfig {
    #[serde(default)]
    pub enabled: bool,
    pub token: Option<String>,
    pub token_env: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct ProvidersConfig {
    #[serde(default = "default_provider")]
    pub default: String,
    pub anthropic: Option<ProviderEntry>,
    pub openai: Option<ProviderEntry>,
    pub deepseek: Option<ProviderEntry>,
    pub ollama: Option<ProviderEntry>,
}

#[derive(Debug, Deserialize)]
pub struct ProviderEntry {
    pub api_key_env: Option<String>,
    pub model: Option<String>,
    pub base_url: Option<String>,
}

impl KoclawConfig {
    /// Load configuration from a TOML file.
    pub fn from_file(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .with_context(|| format!("Failed to read config file: {}", path.display()))?;
        let config: Self = toml::from_str(&content)
            .with_context(|| format!("Failed to parse config file: {}", path.display()))?;
        Ok(config)
    }

    /// Load from default locations: ./config.toml, ~/.koclaw/config.toml
    pub fn load() -> Result<Self> {
        let local_path = Path::new("config.toml");
        if local_path.exists() {
            return Self::from_file(local_path);
        }

        if let Some(home) = dirs_path() {
            let home_path = home.join("config.toml");
            if home_path.exists() {
                return Self::from_file(&home_path);
            }
        }

        anyhow::bail!(
            "No config.toml found. Copy config.example.toml to config.toml and configure it."
        )
    }
}

/// Resolve a secret: prefer env var, fall back to direct value.
fn resolve_secret(direct: &Option<String>, env_key: &Option<String>) -> Result<String> {
    if let Some(key) = env_key {
        if let Ok(val) = std::env::var(key) {
            if !val.is_empty() {
                return Ok(val);
            }
        }
    }
    direct
        .clone()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| anyhow::anyhow!("Secret not configured"))
}

fn dirs_path() -> Option<std::path::PathBuf> {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .ok()
        .map(|h| std::path::PathBuf::from(h).join(".koclaw"))
}

// Default value functions for serde
fn default_host() -> String { "127.0.0.1".to_string() }
fn default_port() -> u16 { 18789 }
fn default_agent_url() -> String { "ws://127.0.0.1:18790".to_string() }
fn default_log_level() -> String { "info".to_string() }
fn default_workspace_root() -> String { "./workspace".to_string() }
fn default_max_file_size() -> u64 { 10_485_760 } // 10MB
fn default_polling_mode() -> String { "polling".to_string() }
fn default_true() -> bool { true }
fn default_provider() -> String { "anthropic".to_string() }
