//! Lightweight HTTP server for Live2D models, audio assets, and persona config.
//!
//! Serves static files from a configurable directory so Desktop/Web clients
//! can download Live2D model files on first load (cached by browser).

use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::Result;
use axum::Router;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;
use tracing::info;

/// Start an HTTP server that serves static files from a directory.
pub async fn start_static_server(host: &str, port: u16, root: PathBuf) -> Result<()> {
    let app = Router::new()
        .nest_service("/", ServeDir::new(&root))
        .layer(CorsLayer::permissive());

    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    info!(%addr, root = %root.display(), "Static file server starting");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
