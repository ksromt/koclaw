// Suppress dead_code warnings to work around rustc 1.93.1 ICE in check_mod_deathness
#![allow(dead_code)]

use anyhow::Result;
use tracing::{error, info};

mod agent_bridge;
mod config;
mod router;

use config::KoclawConfig;

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration
    let config = match KoclawConfig::load() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Configuration error: {e}");
            eprintln!("Copy config.example.toml to config.toml and configure it.");
            std::process::exit(1);
        }
    };

    // Initialize logging
    let env_filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new(&config.gateway.log_level));

    tracing_subscriber::fmt()
        .with_env_filter(env_filter)
        .init();

    info!("Koclaw Gateway v{}", env!("CARGO_PKG_VERSION"));
    info!(
        host = %config.gateway.host,
        port = %config.gateway.port,
        "Starting gateway"
    );

    // Connect to Python Agent
    let bridge = agent_bridge::AgentBridge::new(config.gateway.agent_url.clone());
    match bridge.connect().await {
        Ok(()) => info!("Agent bridge connected"),
        Err(e) => {
            error!(error = %e, "Failed to connect to Agent (will retry on demand)");
        }
    }

    // Start enabled channels
    if let Some(ref tg) = config.channels.telegram {
        if tg.enabled {
            match tg.resolve_token() {
                Ok(token) => {
                    info!(mode = %tg.mode, "Starting Telegram channel");
                    // TODO: Start Telegram polling/webhook
                    let _ = token; // used in channel start
                }
                Err(e) => error!(error = %e, "Telegram channel config error"),
            }
        }
    }

    if let Some(ref qq) = config.channels.qq {
        if qq.enabled {
            info!("Starting QQ channel");
            // TODO: Start QQ bot
        }
    }

    if let Some(ref dc) = config.channels.discord {
        if dc.enabled {
            info!("Starting Discord channel");
            // TODO: Start Discord bot
        }
    }

    info!("Koclaw Gateway ready");

    // Keep running until Ctrl+C
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");

    Ok(())
}
