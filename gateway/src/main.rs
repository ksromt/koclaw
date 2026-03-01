// Suppress dead_code warnings to work around rustc 1.93.1 ICE in check_mod_deathness
#![allow(dead_code)]

use std::sync::Arc;

use anyhow::Result;
use koclaw_common::channel::Channel;
use tracing::{error, info};

use koclaw_gateway::agent_bridge;
use koclaw_gateway::config::{HeartbeatConfig, KoclawConfig};
use koclaw_gateway::router;
use koclaw_gateway::scheduler;

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

    // Load persona from YAML (falls back to hardcoded default)
    let persona = {
        let persona_path = std::path::Path::new("persona.yaml");
        if persona_path.exists() {
            let yaml =
                std::fs::read_to_string(persona_path).expect("Failed to read persona.yaml");
            let p = koclaw_common::persona::Persona::from_yaml(&yaml)
                .expect("Failed to parse persona.yaml");
            info!(name = %p.name, "Loaded persona from persona.yaml");
            p
        } else {
            info!("No persona.yaml found, using default Kokoron persona");
            koclaw_common::persona::Persona::kokoron()
        }
    };

    // Create router with agent bridge and persona
    let router = Arc::new(router::Router::with_persona(bridge, persona));

    // Start enabled channels
    if let Some(ref tg) = config.channels.telegram {
        if tg.enabled {
            match tg.resolve_token() {
                Ok(token) => {
                    info!(mode = %tg.mode, "Starting Telegram channel");
                    let channel = Arc::new(koclaw_channels::telegram::TelegramChannel::new(
                        token,
                        tg.allowed_users.clone(),
                        tg.admin_user,
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

    if let Some(ref ws) = config.channels.websocket {
        if ws.enabled {
            info!(host = %ws.host, port = %ws.port, "Starting WebSocket channel");
            let channel = Arc::new(
                koclaw_channels::websocket_channel::WebSocketChannel::new(
                    ws.host.clone(),
                    ws.port,
                ),
            );
            router.register_channel(channel.clone()).await;

            let channel_router = router.clone();
            tokio::spawn(async move {
                if let Err(e) = channel.start(channel_router).await {
                    error!(error = %e, "WebSocket channel stopped");
                }
            });
        }
    }

    // Start static file server for Live2D models and assets
    if let Some(ref sf) = config.gateway.static_files {
        if sf.enabled {
            let root = std::path::PathBuf::from(&sf.root);
            let host = sf.host.clone();
            let port = sf.port;
            tokio::spawn(async move {
                if let Err(e) =
                    koclaw_gateway::static_server::start_static_server(&host, port, root).await
                {
                    error!(error = %e, "Static file server stopped");
                }
            });
        }
    }

    // Start scheduler
    if config.scheduler.enabled {
        let job_store = Arc::new(scheduler::JobStore::new(
            &config.scheduler.storage_path,
        ));
        if let Err(e) = job_store.load().await {
            error!(error = %e, "Failed to load scheduler jobs");
        }

        // Ensure heartbeat job exists if configured
        if config.scheduler.heartbeat.enabled {
            ensure_heartbeat_job(&job_store, &config.scheduler.heartbeat).await;
        }

        let (fire_tx, fire_rx) = tokio::sync::mpsc::channel(64);

        let engine = Arc::new(scheduler::SchedulerEngine::new(
            job_store.clone(),
            fire_tx,
            config.scheduler.tick_interval_ms,
            if config.scheduler.heartbeat.enabled {
                Some(config.scheduler.heartbeat.active_hours_start.clone())
            } else {
                None
            },
            if config.scheduler.heartbeat.enabled {
                Some(config.scheduler.heartbeat.active_hours_end.clone())
            } else {
                None
            },
            config.scheduler.heartbeat.timezone.clone(),
        ));

        // Fire overdue jobs from previous shutdown
        match engine.fire_overdue().await {
            Ok(n) if n > 0 => info!(count = n, "Fired overdue jobs from previous shutdown"),
            Ok(_) => {}
            Err(e) => error!(error = %e, "Error firing overdue jobs"),
        }

        // Spawn the tick loop
        let engine_clone = engine.clone();
        tokio::spawn(async move {
            engine_clone.start().await;
        });

        // Spawn fired job consumer (placeholder -- will be implemented in Task 6)
        tokio::spawn(async move {
            let mut rx = fire_rx;
            while let Some(fired) = rx.recv().await {
                info!(
                    job_id = %fired.job.id,
                    trigger = %fired.trigger_type,
                    message = %fired.job.message,
                    "Job fired (handler not yet wired)"
                );
            }
        });

        info!(
            storage = %config.scheduler.storage_path,
            heartbeat = config.scheduler.heartbeat.enabled,
            "Scheduler started"
        );
    }

    info!("Koclaw Gateway ready");

    // Keep running until Ctrl+C
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");

    Ok(())
}

async fn ensure_heartbeat_job(
    store: &scheduler::JobStore,
    hb: &HeartbeatConfig,
) {
    let jobs = store.list().await;
    let has_heartbeat = jobs.iter().any(|j| j.job_type == scheduler::JobType::Heartbeat);

    if !has_heartbeat {
        let job = scheduler::SchedulerJob::new(
            "heartbeat",
            &hb.channel,
            &hb.target_id,
            "system:heartbeat",
            "system",
            "Heartbeat check-in",
            scheduler::JobSchedule::Every {
                interval_secs: hb.interval_secs,
            },
            false, // never delete
            scheduler::JobType::Heartbeat,
        );
        if let Err(e) = store.insert(job).await {
            error!(error = %e, "Failed to create heartbeat job");
        } else {
            info!("Created heartbeat job (every {}s)", hb.interval_secs);
        }
    }
}
