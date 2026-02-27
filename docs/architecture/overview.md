# Koclaw Architecture Overview

## System Architecture

```
                    ┌────────────────────────────────────────────┐
                    │              User Devices                  │
                    │                                            │
                    │  ┌──────────┐ ┌────────┐ ┌──────────────┐ │
                    │  │ Desktop  │ │ Mobile │ │ Web Browser  │ │
                    │  │ (Live2D) │ │ (SNS)  │ │ (Blog Chat)  │ │
                    │  └────┬─────┘ └───┬────┘ └──────┬───────┘ │
                    └───────┼───────────┼─────────────┼─────────┘
                            │           │             │
                    ┌───────▼───────────▼─────────────▼─────────┐
                    │         E2E Encrypted Transport            │
                    │    (X25519 + ChaCha20-Poly1305)            │
                    └───────────────────┬───────────────────────┘
                                        │
┌───────────────────────────────────────▼───────────────────────────────────┐
│                        Koclaw Gateway (Rust)                              │
│                                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │   Channels   │  │  Auth/Crypto │  │   Router    │  │   Sandbox     │  │
│  │             │  │              │  │             │  │               │  │
│  │  Telegram   │  │  E2E Encrypt │  │  Message    │  │  Filesystem   │  │
│  │  QQ         │  │  Key Mgmt    │  │  Routing    │  │  Command      │  │
│  │  Discord    │  │  Session     │  │  Rate Limit │  │  Allowlist    │  │
│  │  WebSocket  │  │  Permissions │  │  Queue      │  │  Permission   │  │
│  │  (Desktop)  │  │              │  │             │  │  Levels       │  │
│  │  (Web SDK)  │  │              │  │             │  │               │  │
│  └──────┬──────┘  └──────────────┘  └──────┬──────┘  └───────────────┘  │
│         │                                   │                             │
│         └───────────────────────────────────┘                             │
│                            │                                              │
│  ┌─────────────────────────▼─────────────────────────────────────────┐   │
│  │                    Agent Bridge (WebSocket/gRPC)                   │   │
│  │              Gateway ←→ Python Agent communication                │   │
│  └─────────────────────────┬─────────────────────────────────────────┘   │
└────────────────────────────┼─────────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────────┐
│                     Koclaw Agent (Python)                                 │
│                                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  LLM Router  │  │  Memory      │  │  Tool Engine │  │  Voice      │  │
│  │              │  │              │  │  (MCP+)      │  │  Pipeline   │  │
│  │  Claude      │  │  Short-term  │  │              │  │             │  │
│  │  OpenAI      │  │  Long-term   │  │  Shell       │  │  ASR        │  │
│  │  DeepSeek    │  │  Encrypted   │  │  Search      │  │  TTS        │  │
│  │  Local/Ollama│  │  RAG Index   │  │  File Ops    │  │  VAD        │  │
│  │              │  │              │  │  Custom      │  │             │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘  │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    Persona System (Kokoron)                      │    │
│  │  Identity / Personality / Per-channel behavior adaptation        │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

## Core Traits (Rust Gateway)

```rust
/// Communication channel (Telegram, QQ, Discord, WebSocket, etc.)
trait Channel: Send + Sync {
    async fn start(&self, router: Arc<MessageRouter>) -> Result<()>;
    async fn send_message(&self, target: &ChannelTarget, msg: &OutgoingMessage) -> Result<()>;
    fn channel_type(&self) -> ChannelType;
    fn permission_level(&self) -> PermissionLevel;
}

/// LLM Provider routing (delegates to Python Agent for actual inference)
trait Provider: Send + Sync {
    async fn generate(&self, request: &AgentRequest) -> Result<AgentResponse>;
    fn supports_streaming(&self) -> bool;
    fn supports_vision(&self) -> bool;
    fn provider_name(&self) -> &str;
}

/// Executable tool with sandbox constraints
trait Tool: Send + Sync {
    async fn execute(&self, args: &ToolArgs, sandbox: &Sandbox) -> Result<ToolResult>;
    fn name(&self) -> &str;
    fn schema(&self) -> &ToolSchema;
    fn required_permission(&self) -> PermissionLevel;
}

/// Memory backend (encrypted at rest)
trait MemoryBackend: Send + Sync {
    async fn store(&self, key: &str, value: &EncryptedBlob) -> Result<()>;
    async fn retrieve(&self, key: &str) -> Result<Option<EncryptedBlob>>;
    async fn search(&self, query: &str, limit: usize) -> Result<Vec<MemoryEntry>>;
}
```

## Permission Levels

| Level | Channels | Capabilities |
|-------|----------|-------------|
| `Public` | Blog widget, public web | Chat only, no tools, no private data, rate limited |
| `Authenticated` | Telegram/QQ/Discord private chat | Full tools, memory, file access within sandbox |
| `Admin` | Desktop app, designated admin users | Unrestricted, config changes, system management |

## Communication Flow

1. User sends message via Channel (e.g., Telegram)
2. Gateway receives → decrypts (E2E) → authenticates → routes
3. Gateway forwards to Agent via WebSocket bridge
4. Agent processes (LLM call, tool execution, memory retrieval)
5. Agent returns response to Gateway
6. Gateway encrypts → sends back through Channel

## Data Flow for E2E Encryption

```
User Device                    Server (Gateway)               Agent
    │                              │                            │
    ├──[user_pubkey]──────────────►│                            │
    │                              │                            │
    │◄──[server_pubkey]────────────┤                            │
    │                              │                            │
    │  (X25519 key exchange)       │                            │
    │  shared_secret derived       │                            │
    │                              │                            │
    ├──[ChaCha20(msg)]────────────►│                            │
    │                              ├──[decrypt]──►[plaintext]───►│
    │                              │◄──[response]───────────────┤
    │◄──[ChaCha20(response)]──────┤                            │
    │                              │                            │
```

Note: In the current design, the Gateway CAN decrypt messages to forward to the Agent.
For true zero-knowledge E2E (server admin cannot read), the Agent must run on trusted
hardware or the encryption must extend to the Agent process. This is a Phase 2+ goal.

## Deployment Topologies

### 1. All-in-One (Development / Personal)
Gateway + Agent on same machine. Simplest setup.

### 2. Split (Production)
Gateway on VPS (always-on for SNS), Agent on local GPU machine (for inference).
Connected via encrypted WebSocket tunnel.

### 3. Hybrid
Gateway on VPS, Agent split: cloud LLM for text, local GPU for voice/vision.
