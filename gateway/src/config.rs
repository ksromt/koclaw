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
    #[serde(default)]
    pub scheduler: SchedulerConfig,
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
    pub static_files: Option<StaticFilesConfig>,
}

#[derive(Debug, Deserialize)]
pub struct StaticFilesConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_static_host")]
    pub host: String,
    #[serde(default = "default_static_port")]
    pub port: u16,
    #[serde(default = "default_static_root")]
    pub root: String,
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
    pub websocket: Option<WebSocketConfig>,
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
    /// Telegram user ID of the admin (owner). When matched, the bot recognizes
    /// the user as its master and adjusts conversation accordingly.
    pub admin_user: Option<i64>,
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

impl DiscordConfig {
    pub fn resolve_token(&self) -> Result<String> {
        resolve_secret(&self.token, &self.token_env)
            .context("Discord bot token not configured. Set DISCORD_BOT_TOKEN or token in config")
    }
}

#[derive(Debug, Deserialize)]
pub struct WebSocketConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_ws_host")]
    pub host: String,
    #[serde(default = "default_ws_port")]
    pub port: u16,
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

#[derive(Debug, Deserialize)]
pub struct SchedulerConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_scheduler_storage")]
    pub storage_path: String,
    #[serde(default = "default_tick_interval")]
    pub tick_interval_ms: u64,
    #[serde(default)]
    pub heartbeat: HeartbeatConfig,
}

impl Default for SchedulerConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            storage_path: default_scheduler_storage(),
            tick_interval_ms: default_tick_interval(),
            heartbeat: HeartbeatConfig::default(),
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct HeartbeatConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_heartbeat_interval")]
    pub interval_secs: u64,
    #[serde(default)]
    pub channel: String,
    #[serde(default)]
    pub target_id: String,
    #[serde(default = "default_active_start")]
    pub active_hours_start: String,
    #[serde(default = "default_active_end")]
    pub active_hours_end: String,
    #[serde(default = "default_heartbeat_tz")]
    pub timezone: String,
}

impl Default for HeartbeatConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            interval_secs: default_heartbeat_interval(),
            channel: String::new(),
            target_id: String::new(),
            active_hours_start: default_active_start(),
            active_hours_end: default_active_end(),
            timezone: default_heartbeat_tz(),
        }
    }
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
fn default_ws_host() -> String { "127.0.0.1".to_string() }
fn default_ws_port() -> u16 { 18791 }
fn default_static_host() -> String { "127.0.0.1".to_string() }
fn default_static_port() -> u16 { 18792 }
fn default_static_root() -> String { "./assets".to_string() }
fn default_provider() -> String { "anthropic".to_string() }
fn default_scheduler_storage() -> String { "./data/scheduler_jobs.json".to_string() }
fn default_tick_interval() -> u64 { 1000 }
fn default_heartbeat_interval() -> u64 { 1800 } // 30 minutes
fn default_active_start() -> String { "09:00".to_string() }
fn default_active_end() -> String { "22:00".to_string() }
fn default_heartbeat_tz() -> String { "Asia/Tokyo".to_string() }

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scheduler_config_defaults() {
        let config = SchedulerConfig::default();
        assert!(config.enabled);
        assert_eq!(config.storage_path, "./data/scheduler_jobs.json");
        assert_eq!(config.tick_interval_ms, 1000);
        assert!(!config.heartbeat.enabled);
    }

    #[test]
    fn test_heartbeat_config_defaults() {
        let config = HeartbeatConfig::default();
        assert!(!config.enabled);
        assert_eq!(config.interval_secs, 1800);
        assert!(config.channel.is_empty());
        assert!(config.target_id.is_empty());
        assert_eq!(config.active_hours_start, "09:00");
        assert_eq!(config.active_hours_end, "22:00");
        assert_eq!(config.timezone, "Asia/Tokyo");
    }

    #[test]
    fn test_scheduler_config_from_toml() {
        let toml_str = r#"
            [gateway]
            host = "127.0.0.1"
            port = 18789
            agent_url = "ws://127.0.0.1:18790"

            [channels]

            [scheduler]
            enabled = true
            storage_path = "/tmp/jobs.json"
            tick_interval_ms = 500

            [scheduler.heartbeat]
            enabled = true
            interval_secs = 3600
            channel = "telegram"
            target_id = "12345"
            active_hours_start = "10:00"
            active_hours_end = "20:00"
            timezone = "America/New_York"
        "#;

        let config: KoclawConfig = toml::from_str(toml_str).unwrap();
        assert!(config.scheduler.enabled);
        assert_eq!(config.scheduler.storage_path, "/tmp/jobs.json");
        assert_eq!(config.scheduler.tick_interval_ms, 500);

        let hb = &config.scheduler.heartbeat;
        assert!(hb.enabled);
        assert_eq!(hb.interval_secs, 3600);
        assert_eq!(hb.channel, "telegram");
        assert_eq!(hb.target_id, "12345");
        assert_eq!(hb.active_hours_start, "10:00");
        assert_eq!(hb.active_hours_end, "20:00");
        assert_eq!(hb.timezone, "America/New_York");
    }

    #[test]
    fn test_scheduler_config_missing_uses_defaults() {
        let toml_str = r#"
            [gateway]
            host = "127.0.0.1"
            port = 18789
            agent_url = "ws://127.0.0.1:18790"

            [channels]
        "#;

        let config: KoclawConfig = toml::from_str(toml_str).unwrap();
        assert!(config.scheduler.enabled);
        assert_eq!(config.scheduler.storage_path, "./data/scheduler_jobs.json");
        assert_eq!(config.scheduler.tick_interval_ms, 1000);
        assert!(!config.scheduler.heartbeat.enabled);
        assert_eq!(config.scheduler.heartbeat.interval_secs, 1800);
        assert_eq!(config.scheduler.heartbeat.timezone, "Asia/Tokyo");
    }
}
