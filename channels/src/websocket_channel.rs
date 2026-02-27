//! WebSocket channel for Desktop/Web Live2D clients.
//!
//! Protocol (compatible with AIKokoron frontend):
//!   Client -> Server: `{"type": "text-input", "text": "...", "session_id": "..."}`
//!   Server -> Client: `{"type": "full-text", "text": "..."}`
//!   Keepalive:        `{"type": "ping"}` / `{"type": "pong"}`

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpListener;
use tokio::sync::{mpsc, RwLock};
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

/// WebSocket channel for Desktop/Web clients.
///
/// Runs a TCP listener that upgrades connections to WebSocket.
/// Each connected client is tracked by session ID and can exchange
/// JSON messages following the AIKokoron-compatible protocol.
pub struct WebSocketChannel {
    host: String,
    port: u16,
    /// Active client connections: session_id -> sender
    clients: Arc<RwLock<HashMap<String, mpsc::Sender<String>>>>,
}

impl WebSocketChannel {
    pub fn new(host: String, port: u16) -> Self {
        Self {
            host,
            port,
            clients: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    async fn start_server(&self, router: Arc<dyn MessageRouter>) -> Result<()> {
        let addr = format!("{}:{}", self.host, self.port);
        let listener = TcpListener::bind(&addr).await?;
        info!(addr = %addr, "WebSocket channel listening");

        loop {
            let (stream, peer) = listener.accept().await?;
            let ws_stream = match tokio_tungstenite::accept_async(stream).await {
                Ok(ws) => ws,
                Err(e) => {
                    warn!(%peer, error = %e, "WebSocket handshake failed");
                    continue;
                }
            };
            info!(%peer, "WebSocket client connected");

            let session_id = format!("ws:{}", peer);
            let router = router.clone();
            let clients = self.clients.clone();

            tokio::spawn(async move {
                if let Err(e) =
                    handle_client(ws_stream, peer, session_id, router, clients).await
                {
                    error!(%peer, error = %e, "WebSocket client error");
                }
            });
        }
    }
}

/// Process a single WebSocket client connection.
///
/// Registers the client in the shared map, spawns a sender task that
/// forwards outgoing payloads, and runs the receive loop that parses
/// incoming JSON and routes messages through the `MessageRouter`.
async fn handle_client(
    ws_stream: tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    peer: SocketAddr,
    session_id: String,
    router: Arc<dyn MessageRouter>,
    clients: Arc<RwLock<HashMap<String, mpsc::Sender<String>>>>,
) -> Result<()> {
    let (mut ws_sender, mut ws_receiver) = ws_stream.split();
    let (tx, mut rx) = mpsc::channel::<String>(32);

    // Register client
    clients.write().await.insert(session_id.clone(), tx);

    // Spawn sender task -- forwards outgoing messages to the WebSocket
    let send_session = session_id.clone();
    let send_task = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            if ws_sender.send(Message::Text(msg.into())).await.is_err() {
                break;
            }
        }
        debug!(session = %send_session, "WebSocket sender task ended");
    });

    // Receive loop -- read messages from client
    while let Some(msg) = ws_receiver.next().await {
        match msg {
            Ok(Message::Text(text)) => {
                let text_str: &str = &text;
                let parsed = match serde_json::from_str::<serde_json::Value>(text_str) {
                    Ok(v) => v,
                    Err(e) => {
                        debug!(error = %e, "Ignoring malformed JSON from WebSocket client");
                        continue;
                    }
                };

                let msg_type = parsed["type"].as_str().unwrap_or("");
                match msg_type {
                    "text-input" => {
                        let content = parsed["text"].as_str().unwrap_or("").to_string();
                        let incoming = IncomingMessage {
                            id: uuid_simple(),
                            channel: ChannelType::WebSocket,
                            user_id: peer.to_string(),
                            display_name: None,
                            text: Some(content),
                            attachments: Vec::new(),
                            permission: PermissionLevel::Authenticated,
                            session_id: session_id.clone(),
                            timestamp: std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_secs(),
                        };
                        if let Err(e) = router.route(incoming).await {
                            error!(error = %e, "Failed to route WebSocket message");
                        }
                    }
                    "ping" => {
                        let clients_r = clients.read().await;
                        if let Some(tx) = clients_r.get(&session_id) {
                            let _ = tx.send(r#"{"type":"pong"}"#.to_string()).await;
                        }
                    }
                    _ => {
                        debug!(msg_type, "Unknown WebSocket message type");
                    }
                }
            }
            Ok(Message::Close(_)) => break,
            Err(e) => {
                warn!(%peer, error = %e, "WebSocket receive error");
                break;
            }
            _ => {}
        }
    }

    // Cleanup
    clients.write().await.remove(&session_id);
    send_task.abort();
    info!(%peer, "WebSocket client disconnected");
    Ok(())
}

impl Channel for WebSocketChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.start_server(router))
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        let clients = self.clients.clone();

        Box::pin(async move {
            let clients = clients.read().await;
            if let Some(tx) = clients.get(&target_id) {
                let payload = serde_json::json!({
                    "type": "full-text",
                    "text": text,
                });
                let _ = tx.send(payload.to_string()).await;
            } else {
                warn!(target = %target_id, "No WebSocket client found for response");
            }
            Ok(())
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::WebSocket
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}

/// Simple pseudo-UUID for message IDs.
fn uuid_simple() -> String {
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("ws-{t:x}")
}
