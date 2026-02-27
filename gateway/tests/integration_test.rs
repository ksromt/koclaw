//! Integration tests for the Koclaw Gateway.
//!
//! Tests the full message pipeline:
//! 1. Mock WebSocket Agent server (echoes messages)
//! 2. AgentBridge connects to mock server
//! 3. Router routes a message through the bridge
//! 4. Mock channel captures the outgoing response

#![allow(dead_code)]

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpListener;
use tokio::sync::RwLock;
use tokio_tungstenite::tungstenite::Message;

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

// --- Mock Channel ---

/// A mock channel that captures outgoing messages for assertions.
struct MockChannel {
    channel_type: ChannelType,
    sent_messages: Arc<RwLock<Vec<OutgoingMessage>>>,
}

impl MockChannel {
    fn new(channel_type: ChannelType) -> Self {
        Self {
            channel_type,
            sent_messages: Arc::new(RwLock::new(Vec::new())),
        }
    }

    fn sent_messages(&self) -> Arc<RwLock<Vec<OutgoingMessage>>> {
        self.sent_messages.clone()
    }
}

impl Channel for MockChannel {
    fn start(&self, _router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        let msg = msg.clone();
        let sent = self.sent_messages.clone();
        Box::pin(async move {
            sent.write().await.push(msg);
            Ok(())
        })
    }

    fn channel_type(&self) -> ChannelType {
        self.channel_type
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}

// --- Mock Agent WebSocket Server ---

/// Start a mock Agent WebSocket server that echoes back text as streaming chunks.
async fn start_mock_agent(addr: SocketAddr) -> Result<()> {
    let listener = TcpListener::bind(addr).await?;

    tokio::spawn(async move {
        while let Ok((stream, _)) = listener.accept().await {
            tokio::spawn(async move {
                let ws_stream = tokio_tungstenite::accept_async(stream)
                    .await
                    .expect("WebSocket handshake failed");

                let (mut write, mut read) = ws_stream.split();

                while let Some(Ok(msg)) = read.next().await {
                    if let Message::Text(text) = msg {
                        // Parse the incoming request
                        let request: serde_json::Value =
                            serde_json::from_str(&text).unwrap_or_default();

                        let session_id = request["session_id"]
                            .as_str()
                            .unwrap_or("unknown")
                            .to_string();
                        let user_text = request["text"]
                            .as_str()
                            .unwrap_or("")
                            .to_string();

                        // Send echo response as a text_chunk
                        let chunk = serde_json::json!({
                            "type": "text_chunk",
                            "session_id": session_id,
                            "content": format!("Echo: {}", user_text)
                        });
                        let _ = write
                            .send(Message::Text(chunk.to_string().into()))
                            .await;

                        // Send done
                        let done = serde_json::json!({
                            "type": "done",
                            "session_id": session_id
                        });
                        let _ = write
                            .send(Message::Text(done.to_string().into()))
                            .await;
                    }
                }
            });
        }
    });

    Ok(())
}

/// Create a test IncomingMessage.
fn make_test_message(
    text: &str,
    channel: ChannelType,
    permission: PermissionLevel,
    session_id: &str,
) -> IncomingMessage {
    IncomingMessage {
        id: "test_msg_1".to_string(),
        channel,
        user_id: "test:user1".to_string(),
        display_name: Some("Test User".to_string()),
        text: Some(text.to_string()),
        attachments: vec![],
        permission,
        session_id: session_id.to_string(),
        timestamp: 1709078400000,
    }
}

// --- Tests ---

#[tokio::test]
async fn test_permission_denies_tool_execution_for_public() {
    // Public users should not be able to execute slash commands
    use koclaw_gateway::agent_bridge::AgentBridge;
    use koclaw_gateway::router::Router;

    // Create bridge (not connected — we're testing permission check before bridge)
    let bridge = Arc::new(AgentBridge::new("ws://127.0.0.1:19999".to_string()));
    let router = Arc::new(Router::new(bridge));

    // Register a mock channel to capture the "permission denied" response
    let mock_channel = Arc::new(MockChannel::new(ChannelType::Telegram));
    let sent = mock_channel.sent_messages();
    router.register_channel(mock_channel).await;

    // Create a slash command from a Public user
    let message = make_test_message(
        "/search something",
        ChannelType::Telegram,
        PermissionLevel::Public,
        "tg:12345",
    );

    // Route it — should be denied
    let result = router.route(message).await;
    assert!(result.is_ok());

    // Check the mock channel received a "Permission denied" response
    let messages = sent.read().await;
    assert_eq!(messages.len(), 1);
    assert!(messages[0]
        .text
        .as_ref()
        .unwrap()
        .contains("Permission denied"));
}

#[tokio::test]
async fn test_agent_unavailable_returns_error_message() {
    use koclaw_gateway::agent_bridge::AgentBridge;
    use koclaw_gateway::router::Router;

    // Create bridge (not connected)
    let bridge = Arc::new(AgentBridge::new("ws://127.0.0.1:19998".to_string()));
    let router = Arc::new(Router::new(bridge));

    let mock_channel = Arc::new(MockChannel::new(ChannelType::Telegram));
    let sent = mock_channel.sent_messages();
    router.register_channel(mock_channel).await;

    // Send a regular message (not a slash command) from an Authenticated user
    let message = make_test_message(
        "Hello",
        ChannelType::Telegram,
        PermissionLevel::Authenticated,
        "tg:12345",
    );

    let result = router.route(message).await;
    assert!(result.is_ok());

    // Should get "Agent is currently unavailable" response
    let messages = sent.read().await;
    assert_eq!(messages.len(), 1);
    assert!(messages[0]
        .text
        .as_ref()
        .unwrap()
        .contains("unavailable"));
}

#[tokio::test]
async fn test_empty_message_ignored() {
    use koclaw_gateway::agent_bridge::AgentBridge;
    use koclaw_gateway::router::Router;

    let bridge = Arc::new(AgentBridge::new("ws://127.0.0.1:19997".to_string()));
    let router = Arc::new(Router::new(bridge));

    let mock_channel = Arc::new(MockChannel::new(ChannelType::Telegram));
    let sent = mock_channel.sent_messages();
    router.register_channel(mock_channel).await;

    // Empty message with no text and no attachments
    let message = IncomingMessage {
        id: "test_msg_empty".to_string(),
        channel: ChannelType::Telegram,
        user_id: "test:user1".to_string(),
        display_name: None,
        text: None,
        attachments: vec![],
        permission: PermissionLevel::Authenticated,
        session_id: "tg:12345".to_string(),
        timestamp: 1709078400000,
    };

    let result = router.route(message).await;
    assert!(result.is_ok());

    // No response should be sent for empty messages
    let messages = sent.read().await;
    assert_eq!(messages.len(), 0);
}

#[tokio::test]
async fn test_full_round_trip_with_mock_agent() {
    use koclaw_gateway::agent_bridge::AgentBridge;
    use koclaw_gateway::router::Router;

    // Start mock agent server on a random port
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener); // Release the port so mock agent can bind to it

    start_mock_agent(addr).await.unwrap();

    // Give the mock server a moment to start
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;

    // Create bridge and connect to mock agent
    let bridge = Arc::new(AgentBridge::new(format!("ws://{}", addr)));
    bridge.connect().await.unwrap();

    let router = Arc::new(Router::new(bridge));

    let mock_channel = Arc::new(MockChannel::new(ChannelType::Telegram));
    let sent = mock_channel.sent_messages();
    router.register_channel(mock_channel).await;

    // Send a regular message from an Authenticated user
    let message = make_test_message(
        "Hello Kokoron!",
        ChannelType::Telegram,
        PermissionLevel::Authenticated,
        "tg:99999",
    );

    let result = router.route(message).await;
    assert!(result.is_ok());

    // Give time for async response processing
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;

    // Check the mock channel received the echo response
    let messages = sent.read().await;
    assert_eq!(messages.len(), 1, "Expected 1 response message");
    let response_text = messages[0].text.as_ref().unwrap();
    assert!(
        response_text.contains("Echo: Hello Kokoron!"),
        "Expected echo response, got: {}",
        response_text
    );
    assert_eq!(messages[0].target_id, "99999"); // Extracted from "tg:99999"
}

#[tokio::test]
async fn test_permission_allows_authenticated_slash_commands() {
    use koclaw_gateway::agent_bridge::AgentBridge;
    use koclaw_gateway::router::Router;

    // Start mock agent
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);

    start_mock_agent(addr).await.unwrap();
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;

    let bridge = Arc::new(AgentBridge::new(format!("ws://{}", addr)));
    bridge.connect().await.unwrap();

    let router = Arc::new(Router::new(bridge));

    let mock_channel = Arc::new(MockChannel::new(ChannelType::Telegram));
    let sent = mock_channel.sent_messages();
    router.register_channel(mock_channel).await;

    // Authenticated user sending a slash command — should be allowed
    let message = make_test_message(
        "/search weather",
        ChannelType::Telegram,
        PermissionLevel::Authenticated,
        "tg:88888",
    );

    let result = router.route(message).await;
    assert!(result.is_ok());

    tokio::time::sleep(std::time::Duration::from_millis(200)).await;

    let messages = sent.read().await;
    assert_eq!(messages.len(), 1);
    assert!(
        messages[0].text.as_ref().unwrap().contains("Echo: /search weather"),
        "Authenticated user slash command should pass through to agent"
    );
}
