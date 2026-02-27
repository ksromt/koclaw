# Core Traits Design

This document defines the core trait abstractions that form the backbone of Koclaw's extensible architecture. Every major subsystem -- channels, providers, tools, memory backends, and message routing -- is defined as a trait, allowing new implementations to be added without modifying existing code.

---

## Table of Contents

- [Design Principles](#design-principles)
- [Channel Trait](#channel-trait)
- [MessageRouter Trait](#messagerouter-trait)
- [Provider Trait](#provider-trait)
- [Tool Trait](#tool-trait)
- [MemoryBackend Trait](#memorybackend-trait)
- [Supporting Types](#supporting-types)
- [Adding New Implementations](#adding-new-implementations)
- [Extension Points](#extension-points)

---

## Design Principles

All traits in Koclaw follow these principles:

1. **Send + Sync** -- All trait objects are safe to share across async tasks and threads. This is required because the Gateway is built on tokio and handles messages concurrently.

2. **Async-first** -- All I/O-bound methods return futures. The Gateway runtime is fully async.

3. **Error propagation via Result** -- All fallible operations return `anyhow::Result<T>` at the application layer or `Result<T, KoclawError>` for domain-specific errors.

4. **Config-driven registration** -- Implementations are registered at startup based on the TOML configuration file. No hardcoded lists of implementations.

5. **Minimal trait surface** -- Each trait defines the minimum set of methods required. Optional behavior is handled through default implementations or feature detection methods.

---

## Channel Trait

The `Channel` trait defines the interface for all communication channels (Telegram, QQ, Discord, WebSocket, etc.). Each channel is responsible for receiving messages from its platform, normalizing them into `IncomingMessage`, and sending `OutgoingMessage` responses back.

### Definition

**File:** `common/src/channel.rs`

```rust
use std::sync::Arc;
use anyhow::Result;
use crate::message::{IncomingMessage, OutgoingMessage};
use crate::permission::PermissionLevel;

/// Identifies which channel a message belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ChannelType {
    Telegram,
    QQ,
    Discord,
    WebSocket,
    WebPublic,
}

/// Trait that all communication channels must implement.
///
/// To add a new channel:
/// 1. Add a variant to `ChannelType`
/// 2. Implement this trait
/// 3. Register in the channel registry (config-driven)
///
/// No existing code needs to be modified.
pub trait Channel: Send + Sync {
    /// Start listening for messages on this channel.
    ///
    /// This method is called once at startup. It should spawn background tasks
    /// (e.g., a polling loop or webhook listener) that receive messages from
    /// the external platform and forward them to the router.
    ///
    /// The `router` parameter is an `Arc<dyn MessageRouter>` that the channel
    /// uses to forward received messages into the Gateway's routing pipeline.
    ///
    /// This method should return `Ok(())` once the background listener is
    /// running. It should NOT block indefinitely.
    fn start(
        &self,
        router: Arc<dyn MessageRouter>,
    ) -> impl std::future::Future<Output = Result<()>> + Send;

    /// Send a message through this channel.
    ///
    /// The Gateway calls this method when it has a response to deliver.
    /// The implementation is responsible for formatting the message
    /// appropriately for its platform (e.g., Markdown for Telegram,
    /// rich cards for QQ).
    fn send_message(
        &self,
        msg: &OutgoingMessage,
    ) -> impl std::future::Future<Output = Result<()>> + Send;

    /// The type of this channel.
    ///
    /// Used for routing responses back through the correct channel
    /// and for logging/metrics.
    fn channel_type(&self) -> ChannelType;

    /// Default permission level for messages from this channel.
    ///
    /// This determines what capabilities are available to users
    /// communicating through this channel. Individual users may
    /// have overridden permission levels (e.g., admin users on Telegram).
    fn default_permission(&self) -> PermissionLevel;
}
```

### Implementation Example: Telegram

```rust
// channels/src/telegram.rs

use std::sync::Arc;
use anyhow::Result;
use koclaw_common::channel::{Channel, ChannelType, MessageRouter};
use koclaw_common::message::OutgoingMessage;
use koclaw_common::permission::PermissionLevel;

pub struct TelegramChannel {
    token: String,
}

impl TelegramChannel {
    pub fn new(token: String) -> Self {
        Self { token }
    }
}

impl Channel for TelegramChannel {
    async fn start(&self, _router: Arc<dyn MessageRouter>) -> Result<()> {
        // Start polling loop or webhook listener
        tracing::info!("Telegram channel started");
        Ok(())
    }

    async fn send_message(&self, _msg: &OutgoingMessage) -> Result<()> {
        // Call Telegram Bot API: POST /sendMessage
        Ok(())
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::Telegram
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}
```

### Channel Lifecycle

```
Gateway Startup
      |
      v
  Load config.toml
      |
      v
  For each enabled channel:
      |
      +---> Construct channel instance (e.g., TelegramChannel::new(token))
      |
      +---> Call channel.start(router) -- spawns background listener
      |
      v
  All channels running
      |
      v
  On incoming message:
      |
      +---> Channel normalizes to IncomingMessage
      +---> Channel calls router.route(message)
      +---> Router forwards to Agent
      +---> Agent response returned
      +---> Router calls channel.send_message(response)
      |
      v
  On shutdown (Ctrl+C):
      |
      +---> Drop all channel instances (cleanup)
```

---

## MessageRouter Trait

The `MessageRouter` trait defines the interface for the central message routing component. It receives normalized `IncomingMessage` objects from channels and is responsible for permission checking, forwarding to the Agent, and returning responses.

### Definition

**File:** `common/src/channel.rs`

```rust
/// Trait for message routing -- receives incoming messages from channels.
pub trait MessageRouter: Send + Sync {
    /// Route an incoming message through the pipeline.
    ///
    /// This method:
    /// 1. Checks the message's permission level
    /// 2. Applies rate limiting
    /// 3. Forwards to the Agent via the bridge
    /// 4. Collects the Agent's response
    /// 5. Sends the response back through the originating channel
    ///
    /// Returns Ok(()) on success. Errors are logged and, where possible,
    /// communicated back to the user as error messages.
    fn route(
        &self,
        message: IncomingMessage,
    ) -> impl std::future::Future<Output = Result<()>> + Send;
}
```

### Implementation

**File:** `gateway/src/router.rs`

```rust
use anyhow::Result;
use koclaw_common::message::IncomingMessage;
use koclaw_common::channel::MessageRouter;

/// Routes incoming messages from channels to the agent and back.
pub struct Router {
    // agent_bridge: AgentBridge,
    // channel_registry: ChannelRegistry,
}

impl Router {
    pub fn new() -> Self {
        Self {}
    }
}

impl MessageRouter for Router {
    async fn route(&self, message: IncomingMessage) -> Result<()> {
        tracing::info!(
            channel = %message.channel,
            user = %message.user_id,
            "Routing message"
        );

        // 1. Check permissions
        // 2. Apply rate limiting
        // 3. Forward to agent
        // 4. Return response through channel

        Ok(())
    }
}
```

---

## Provider Trait

The `Provider` trait defines the interface for LLM provider integrations. Each provider wraps a specific LLM API (Claude, OpenAI, DeepSeek, Ollama) and provides a uniform generation interface.

**Note:** Provider implementations live in the Python Agent layer, but the trait is defined in Rust for type-safe bridge communication. The Rust definition serves as the protocol contract.

### Definition

```rust
use anyhow::Result;
use serde::{Deserialize, Serialize};

/// Request sent to an LLM provider.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentRequest {
    /// Conversation messages (system, user, assistant turns)
    pub messages: Vec<ConversationMessage>,
    /// Model name override (optional; falls back to config default)
    pub model: Option<String>,
    /// Maximum tokens to generate
    pub max_tokens: Option<u32>,
    /// Temperature for sampling (0.0 - 2.0)
    pub temperature: Option<f32>,
    /// Available tools for this request
    pub tools: Vec<ToolSchema>,
    /// Whether to stream the response
    pub stream: bool,
}

/// Response from an LLM provider.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentResponse {
    /// Generated text content
    pub text: String,
    /// Tool calls requested by the model
    pub tool_calls: Vec<ToolCall>,
    /// Token usage statistics
    pub usage: TokenUsage,
    /// Which model was actually used
    pub model: String,
}

/// LLM Provider routing (delegates to Python Agent for actual inference).
///
/// Implementations live in the Python Agent layer. This trait definition
/// serves as the interface contract between Gateway and Agent.
pub trait Provider: Send + Sync {
    /// Generate a response from the LLM.
    ///
    /// For streaming responses, this returns the full accumulated response.
    /// Use `generate_stream` for incremental chunks.
    fn generate(
        &self,
        request: &AgentRequest,
    ) -> impl std::future::Future<Output = Result<AgentResponse>> + Send;

    /// Whether this provider supports streaming token output.
    fn supports_streaming(&self) -> bool;

    /// Whether this provider supports vision (image) input.
    fn supports_vision(&self) -> bool;

    /// Whether this provider supports tool use / function calling.
    fn supports_tools(&self) -> bool;

    /// The name of this provider (e.g., "claude", "openai", "deepseek").
    fn provider_name(&self) -> &str;

    /// The default model for this provider.
    fn default_model(&self) -> &str;
}
```

### Provider Selection Logic

The Agent selects a provider based on the following priority:

1. **Per-request override** -- If the request specifies a model, use the provider that serves that model.
2. **Per-channel default** -- Configuration can specify a preferred provider per channel.
3. **Global default** -- The first provider listed in config is the default.
4. **Capability matching** -- If the request includes images, only providers with `supports_vision() == true` are eligible.

---

## Tool Trait

The `Tool` trait defines the interface for executable tools that the Agent can invoke. Tools are sandboxed -- they execute within a restricted environment that limits filesystem access and command execution.

### Definition

```rust
use anyhow::Result;
use serde::{Deserialize, Serialize};
use crate::permission::PermissionLevel;

/// Arguments passed to a tool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolArgs {
    /// Tool-specific arguments as a JSON object
    pub args: serde_json::Value,
}

/// Result of tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResult {
    /// Output text or data
    pub output: String,
    /// Whether the execution succeeded
    pub success: bool,
    /// Error message if execution failed
    pub error: Option<String>,
}

/// JSON Schema for tool arguments.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSchema {
    /// Tool name (unique identifier)
    pub name: String,
    /// Human-readable description
    pub description: String,
    /// JSON Schema defining the expected arguments
    pub parameters: serde_json::Value,
}

/// Sandbox constraints for tool execution.
pub struct Sandbox {
    /// Root directory for filesystem access
    pub root: std::path::PathBuf,
    /// Allowed shell commands (empty = none allowed)
    pub allowed_commands: Vec<String>,
    /// Maximum execution time in seconds
    pub timeout_seconds: u64,
}

/// Executable tool with sandbox constraints.
///
/// Tools are invoked by the Agent when the LLM requests function calls.
/// Each tool declares its required permission level -- the Router
/// checks this before allowing execution.
pub trait Tool: Send + Sync {
    /// Execute the tool within the given sandbox.
    ///
    /// The sandbox enforces filesystem and command restrictions.
    /// If the tool attempts to access resources outside the sandbox,
    /// the execution is terminated and an error is returned.
    fn execute(
        &self,
        args: &ToolArgs,
        sandbox: &Sandbox,
    ) -> impl std::future::Future<Output = Result<ToolResult>> + Send;

    /// The unique name of this tool.
    fn name(&self) -> &str;

    /// The JSON Schema describing this tool's arguments.
    fn schema(&self) -> &ToolSchema;

    /// The minimum permission level required to execute this tool.
    ///
    /// Tools that access the filesystem or execute commands typically
    /// require `Authenticated` or `Admin`. Read-only tools like
    /// web search may be available at `Public` level.
    fn required_permission(&self) -> PermissionLevel;
}
```

### Built-in Tools (Planned)

| Tool          | Permission    | Description                                  |
|---------------|---------------|----------------------------------------------|
| `web_search`  | Public        | Search the web and return results            |
| `read_file`   | Authenticated | Read a file from the sandbox workspace       |
| `write_file`  | Authenticated | Write a file to the sandbox workspace        |
| `shell_exec`  | Authenticated | Execute an allowed shell command             |
| `list_files`  | Authenticated | List files in the sandbox workspace          |
| `memory_search` | Authenticated | Search conversation memory                 |
| `config_set`  | Admin         | Modify agent configuration at runtime        |

---

## MemoryBackend Trait

The `MemoryBackend` trait defines the interface for persistent memory storage. All data is encrypted at rest using per-user derived keys, ensuring that only authenticated sessions from a given user can access their memories.

### Definition

```rust
use anyhow::Result;
use serde::{Deserialize, Serialize};

/// An encrypted blob stored in the memory backend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EncryptedBlob {
    /// Encrypted data (ChaCha20-Poly1305 ciphertext)
    pub ciphertext: Vec<u8>,
    /// Nonce used for encryption (12 bytes)
    pub nonce: Vec<u8>,
}

/// A memory entry returned from search results.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    /// Storage key
    pub key: String,
    /// Encrypted value
    pub value: EncryptedBlob,
    /// Timestamp when this entry was stored
    pub created_at: u64,
    /// Timestamp when this entry was last accessed
    pub accessed_at: u64,
    /// Relevance score (for search results, 0.0 - 1.0)
    pub relevance: Option<f64>,
}

/// Memory backend (encrypted at rest).
///
/// Implementations store conversation history, user preferences,
/// and agent-generated knowledge. All data is encrypted before
/// storage using keys derived from the user's identity.
///
/// Implementations:
/// - `SqliteMemory` -- Embedded SQLite database (default)
/// - `PostgresMemory` -- PostgreSQL for multi-user deployments
/// - `InMemoryBackend` -- Volatile storage for testing
pub trait MemoryBackend: Send + Sync {
    /// Store an encrypted value at the given key.
    ///
    /// If the key already exists, the value is overwritten.
    fn store(
        &self,
        key: &str,
        value: &EncryptedBlob,
    ) -> impl std::future::Future<Output = Result<()>> + Send;

    /// Retrieve an encrypted value by key.
    ///
    /// Returns `None` if the key does not exist.
    fn retrieve(
        &self,
        key: &str,
    ) -> impl std::future::Future<Output = Result<Option<EncryptedBlob>>> + Send;

    /// Search for entries matching a query string.
    ///
    /// The search is performed over encrypted metadata or
    /// pre-computed search indices. The returned entries are
    /// still encrypted -- the caller must decrypt them.
    ///
    /// `limit` controls the maximum number of results returned.
    fn search(
        &self,
        query: &str,
        limit: usize,
    ) -> impl std::future::Future<Output = Result<Vec<MemoryEntry>>> + Send;

    /// Delete an entry by key.
    ///
    /// Returns `true` if the entry existed and was deleted,
    /// `false` if the key was not found.
    fn delete(
        &self,
        key: &str,
    ) -> impl std::future::Future<Output = Result<bool>> + Send;

    /// List all keys matching a prefix.
    ///
    /// Useful for iterating over a user's conversation sessions.
    fn list_keys(
        &self,
        prefix: &str,
    ) -> impl std::future::Future<Output = Result<Vec<String>>> + Send;
}
```

### Encryption Flow

```
Plaintext Memory Data
        |
        v
    Serialize (serde_json)
        |
        v
    Derive key: HKDF-SHA256(user_identity_key, "memory-v1")
        |
        v
    Encrypt: ChaCha20-Poly1305(plaintext, derived_key, random_nonce)
        |
        v
    Store: EncryptedBlob { ciphertext, nonce }
        |
        v
    MemoryBackend.store(key, encrypted_blob)
```

---

## Supporting Types

### PermissionLevel

**File:** `common/src/permission.rs`

```rust
/// Permission levels control what actions an agent can take
/// depending on which channel the message originated from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum PermissionLevel {
    /// Blog widget, public web -- chat only, no tools, no private data
    Public = 0,
    /// Telegram/QQ/Discord private chat -- full tools, memory, file access within sandbox
    Authenticated = 1,
    /// Desktop app, designated admin users -- unrestricted
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
```

### KoclawError

**File:** `common/src/error.rs`

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum KoclawError {
    #[error("channel error ({channel}): {message}")]
    Channel { channel: String, message: String },

    #[error("encryption error: {0}")]
    Encryption(String),

    #[error("authentication error: {0}")]
    Auth(String),

    #[error("permission denied: {action} requires {required:?}, got {actual:?}")]
    PermissionDenied {
        action: String,
        required: PermissionLevel,
        actual: PermissionLevel,
    },

    #[error("agent error: {0}")]
    Agent(String),

    #[error("configuration error: {0}")]
    Config(String),

    #[error("not found: {0}")]
    NotFound(String),
}
```

### IncomingMessage / OutgoingMessage

**File:** `common/src/message.rs`

```rust
/// A message received from any channel, normalized to a common format.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomingMessage {
    pub id: String,                        // Unique message ID
    pub channel: ChannelType,              // Source channel
    pub user_id: String,                   // Channel-specific user ID
    pub display_name: Option<String>,      // Sender display name
    pub text: Option<String>,              // Text content
    pub attachments: Vec<Attachment>,       // Media attachments
    pub permission: PermissionLevel,       // Permission level
    pub session_id: String,                // Session ID
    pub timestamp: u64,                    // Unix milliseconds
}

/// A message to send back through a channel.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutgoingMessage {
    pub channel: ChannelType,              // Target channel
    pub target_id: String,                 // Target user/chat ID
    pub text: Option<String>,              // Text content
    pub attachments: Vec<Attachment>,       // Media to send
    pub reply_to: Option<String>,          // Reply to specific message
}

/// Media attachment (image, voice, file).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Attachment {
    pub attachment_type: AttachmentType,   // Image, Voice, Video, File
    pub url: String,                       // URL or local path
    pub mime_type: Option<String>,         // MIME type
    pub file_name: Option<String>,         // File name
    pub size: Option<u64>,                 // Size in bytes
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AttachmentType {
    Image,
    Voice,
    Video,
    File,
}
```

---

## Adding New Implementations

### Adding a New Channel

To add support for a new messaging platform (e.g., Slack):

**Step 1: Add a variant to `ChannelType`**

```rust
// common/src/channel.rs
pub enum ChannelType {
    Telegram,
    QQ,
    Discord,
    WebSocket,
    WebPublic,
    Slack,      // <-- Add new variant
}
```

Update the `Display` implementation accordingly.

**Step 2: Create the channel implementation**

```rust
// channels/src/slack.rs
use std::sync::Arc;
use anyhow::Result;
use koclaw_common::channel::{Channel, ChannelType, MessageRouter};
use koclaw_common::message::OutgoingMessage;
use koclaw_common::permission::PermissionLevel;

pub struct SlackChannel {
    token: String,
    signing_secret: String,
}

impl SlackChannel {
    pub fn new(token: String, signing_secret: String) -> Self {
        Self { token, signing_secret }
    }
}

impl Channel for SlackChannel {
    async fn start(&self, router: Arc<dyn MessageRouter>) -> Result<()> {
        // 1. Connect to Slack Events API or Socket Mode
        // 2. Spawn background task to listen for events
        // 3. On message event: normalize to IncomingMessage, call router.route()
        Ok(())
    }

    async fn send_message(&self, msg: &OutgoingMessage) -> Result<()> {
        // Call Slack Web API: chat.postMessage
        Ok(())
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::Slack
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}
```

**Step 3: Add feature flag to channels crate**

```toml
# channels/Cargo.toml
[features]
default = ["telegram"]
telegram = ["dep:reqwest"]
qq = ["dep:reqwest"]
discord = ["dep:reqwest"]
slack = ["dep:reqwest"]   # <-- Add feature flag
```

**Step 4: Register in the module tree**

```rust
// channels/src/lib.rs
#[cfg(feature = "slack")]
pub mod slack;
```

**Step 5: Add configuration**

```toml
# config.toml
[channels.slack]
enabled = true
token_env = "SLACK_BOT_TOKEN"
signing_secret_env = "SLACK_SIGNING_SECRET"
```

**Step 6: Wire up in gateway startup**

The Gateway's startup code reads the config and constructs the appropriate channel instances. No changes to the Router or Agent bridge are needed.

### Adding a New LLM Provider

Provider implementations live in the Python Agent. To add a new provider:

**Step 1: Create provider module**

```python
# agent/koclaw_agent/providers/mistral.py

from koclaw_agent.providers.base import BaseProvider, AgentRequest, AgentResponse

class MistralProvider(BaseProvider):
    def __init__(self, api_key: str, default_model: str = "mistral-large-latest"):
        self.api_key = api_key
        self.default_model = default_model

    async def generate(self, request: AgentRequest) -> AgentResponse:
        # Call Mistral API
        ...

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "mistral"
```

**Step 2: Register in provider router**

```python
# agent/koclaw_agent/llm_router.py
from koclaw_agent.providers.mistral import MistralProvider

PROVIDERS = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "ollama": OllamaProvider,
    "mistral": MistralProvider,  # <-- Add new provider
}
```

**Step 3: Add configuration**

```
MISTRAL_API_KEY=your-mistral-api-key
```

### Adding a New Tool

**Step 1: Implement the Tool trait**

```rust
pub struct CalculatorTool;

impl Tool for CalculatorTool {
    async fn execute(&self, args: &ToolArgs, _sandbox: &Sandbox) -> Result<ToolResult> {
        let expression = args.args["expression"].as_str()
            .ok_or_else(|| anyhow::anyhow!("missing 'expression' argument"))?;

        // Evaluate the expression safely
        let result = evaluate(expression)?;

        Ok(ToolResult {
            output: result.to_string(),
            success: true,
            error: None,
        })
    }

    fn name(&self) -> &str { "calculator" }

    fn schema(&self) -> &ToolSchema {
        // Return JSON Schema for the tool
        &self.schema
    }

    fn required_permission(&self) -> PermissionLevel {
        PermissionLevel::Public  // Safe for all permission levels
    }
}
```

**Step 2: Register the tool in the tool registry**

The tool registry is config-driven. Add the tool name to the enabled tools list in `config.toml`.

---

## Extension Points

Beyond the five core traits, Koclaw provides several additional extension points:

### Middleware Pipeline

The Router supports a middleware pipeline that processes messages before and after they reach the Agent:

```rust
/// Middleware that can inspect and transform messages in the pipeline.
pub trait Middleware: Send + Sync {
    /// Process an incoming message before it reaches the Agent.
    /// Return None to drop the message (e.g., spam filtering).
    fn on_incoming(
        &self,
        message: &mut IncomingMessage,
    ) -> impl std::future::Future<Output = Result<Option<()>>> + Send;

    /// Process an outgoing message before it is sent through a channel.
    fn on_outgoing(
        &self,
        message: &mut OutgoingMessage,
    ) -> impl std::future::Future<Output = Result<()>> + Send;
}
```

Planned middleware:

| Middleware        | Purpose                                              |
|-------------------|------------------------------------------------------|
| `RateLimiter`     | Enforce per-user and per-channel rate limits          |
| `PermissionGuard` | Block messages that exceed their permission level     |
| `InputSanitizer`  | Clean user input before forwarding to Agent           |
| `OutputFilter`    | Strip tool results from Public channel responses      |
| `AuditLogger`     | Log all messages for compliance/debugging             |

### Persona System

The persona system allows the agent to adapt its behavior based on the channel and context:

```rust
/// Defines an agent persona (e.g., Kokoron).
pub trait Persona: Send + Sync {
    /// The system prompt for this persona.
    fn system_prompt(&self, channel: ChannelType) -> String;

    /// The display name for this persona on the given channel.
    fn display_name(&self, channel: ChannelType) -> String;

    /// Personality traits that influence response style.
    fn traits(&self) -> &[PersonalityTrait];
}
```

### Event Hooks

The Gateway emits events at key points in the message lifecycle. Plugins can subscribe to these events for logging, metrics, or custom behavior:

```rust
pub enum GatewayEvent {
    MessageReceived(IncomingMessage),
    MessageRouted { message_id: String, latency_ms: u64 },
    AgentResponseReceived { session_id: String, tokens: u32 },
    MessageSent(OutgoingMessage),
    ChannelConnected(ChannelType),
    ChannelDisconnected(ChannelType),
    AgentBridgeConnected,
    AgentBridgeDisconnected,
    Error(KoclawError),
}
```
