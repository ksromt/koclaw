// Suppress dead_code warnings to work around rustc 1.93.1 ICE in check_mod_deathness
#![allow(dead_code)]

use std::sync::Arc;

use anyhow::Result;
use koclaw_common::channel::Channel;
use tracing::{error, info};

use koclaw_gateway::agent_bridge;
use koclaw_gateway::config::KoclawConfig;
use koclaw_gateway::router;

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
    let bridge = Arc::new(agent_bridge::AgentBridge::new(
        config.gateway.agent_url.clone(),
    ));
    match bridge.connect().await {
        Ok(()) => info!("Agent bridge connected"),
        Err(e) => {
            error!(error = %e, "Failed to connect to Agent (will retry on demand)");
        }
    }

    // Create router with agent bridge
    let router = Arc::new(router::Router::new(bridge));

    // Start enabled channels
    if let Some(ref tg) = config.channels.telegram {
        if tg.enabled {
            match tg.resolve_token() {
                Ok(token) => {
                    info!(mode = %tg.mode, "Starting Telegram channel");
                    let channel = Arc::new(koclaw_channels::telegram::TelegramChannel::new(
                        token,
                        tg.allowed_users.clone(),
                    ));
                    router.register_channel(channel.clone()).await;

                    let channel_router = router.clone();
                    tokio::spawn(async move {
                        if let Err(e) = channel.start(channel_router).await {
                            error!(error = %e, "Telegram channel stopped");
                        }
                    });
                }
                Err(e) => error!(error = %e, "Telegram channel config error"),
            }
        }
    }

    if let Some(ref qq) = config.channels.qq {
        if qq.enabled {
            match (qq.resolve_app_id(), qq.resolve_secret()) {
                (Ok(app_id), Ok(secret)) => {
                    info!(sandbox = qq.sandbox, "Starting QQ channel");
                    let channel = Arc::new(koclaw_channels::qq::QQChannel::new(
                        app_id, secret, qq.sandbox,
                    ));
                    router.register_channel(channel.clone()).await;

                    let channel_router = router.clone();
                    tokio::spawn(async move {
                        if let Err(e) = channel.start(channel_router).await {
                            error!(error = %e, "QQ channel stopped");
                        }
                    });
                }
                (Err(e), _) | (_, Err(e)) => {
                    error!(error = %e, "QQ channel config error");
                }
            }
        }
    }

    if let Some(ref dc) = config.channels.discord {
        if dc.enabled {
            match dc.resolve_token() {
                Ok(token) => {
                    info!("Starting Discord channel");
                    let channel =
                        Arc::new(koclaw_channels::discord::DiscordChannel::new(token));
                    router.register_channel(channel.clone()).await;

                    let channel_router = router.clone();
                    tokio::spawn(async move {
                        if let Err(e) = channel.start(channel_router).await {
                            error!(error = %e, "Discord channel stopped");
                        }
                    });
                }
                Err(e) => error!(error = %e, "Discord channel config error"),
            }
        }
    }

    info!("Koclaw Gateway ready");

    // Keep running until Ctrl+C
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");

    Ok(())
}
