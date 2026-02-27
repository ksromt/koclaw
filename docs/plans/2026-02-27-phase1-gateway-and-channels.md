# Phase 1: Gateway Core + Telegram & QQ Channels

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a working Koclaw Gateway that receives messages from Telegram and QQ bots, routes them to a Python Agent (AIKokoron-based), and returns responses — with basic encryption and permission enforcement.

**Architecture:** Rust workspace with 3 crates (common, channels, gateway). The Gateway listens for messages from channel implementations, routes them through a permission-checked pipeline to a Python Agent process via WebSocket, and sends responses back. Each channel is a trait implementation registered at startup via config.

**Tech Stack:** Rust (tokio, serde, reqwest, tokio-tungstenite, chacha20poly1305), Python (FastAPI for Agent bridge), TOML config.

**Prerequisites:**
- Install Rust: `winget install Rustlang.Rustup` or https://rustup.rs
- A Telegram bot token (from @BotFather)
- A QQ bot app (from q.qq.com) — can be deferred if review pending

---

## Task 1: Rust Toolchain Setup & Project Verification

**Files:**
- Verify: `Cargo.toml`, `common/Cargo.toml`, `gateway/Cargo.toml`, `channels/Cargo.toml`

**Step 1: Install Rust toolchain**

Run: `rustup default stable`

**Step 2: Verify project compiles**

Run: `cd D:\personal_development\Koclaw && cargo build`
Expected: Successful compilation with warnings (TODO items)

**Step 3: Run cargo clippy**

Run: `cargo clippy -- -W clippy::all`
Expected: Warnings about unused code (expected at this stage)

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: initial project structure with Rust workspace"
```

---

## Task 2: Configuration System

**Files:**
- Create: `gateway/src/config.rs`
- Create: `config.example.toml`
- Modify: `gateway/src/main.rs`

**Step 1: Write config test**

Create `gateway/tests/config_test.rs`:
```rust
use std::io::Write;
use tempfile::NamedTempFile;

#[test]
fn test_load_config_from_toml() {
    let toml_content = r#"
[gateway]
host = "127.0.0.1"
port = 18789
agent_url = "ws://127.0.0.1:18790"

[channels.telegram]
enabled = true
token = "test-token"
mode = "polling"

[channels.qq]
enabled = false
"#;
    let mut file = NamedTempFile::new().unwrap();
    file.write_all(toml_content.as_bytes()).unwrap();

    // TODO: Test that config loads correctly
    // let config = KoclawConfig::from_file(file.path()).unwrap();
    // assert_eq!(config.gateway.port, 18789);
    // assert!(config.channels.telegram.enabled);
}
```

**Step 2: Implement config structs**

`gateway/src/config.rs`:
```rust
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct KoclawConfig {
    pub gateway: GatewayConfig,
    pub channels: ChannelsConfig,
}

#[derive(Debug, Deserialize)]
pub struct GatewayConfig {
    pub host: String,
    pub port: u16,
    pub agent_url: String,
    pub log_level: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ChannelsConfig {
    pub telegram: Option<TelegramConfig>,
    pub qq: Option<QQConfig>,
    pub discord: Option<DiscordConfig>,
}

#[derive(Debug, Deserialize)]
pub struct TelegramConfig {
    pub enabled: bool,
    pub token: Option<String>,
    pub token_env: Option<String>,
    pub mode: Option<String>, // "polling" or "webhook"
    pub webhook_url: Option<String>,
    pub allowed_users: Option<Vec<i64>>,
}

#[derive(Debug, Deserialize)]
pub struct QQConfig {
    pub enabled: bool,
    pub app_id: Option<String>,
    pub app_id_env: Option<String>,
    pub secret: Option<String>,
    pub secret_env: Option<String>,
    pub sandbox: Option<bool>,
}

#[derive(Debug, Deserialize)]
pub struct DiscordConfig {
    pub enabled: bool,
    pub token: Option<String>,
    pub token_env: Option<String>,
}

impl KoclawConfig {
    pub fn from_file(path: &std::path::Path) -> anyhow::Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let config: Self = toml::from_str(&content)?;
        Ok(config)
    }

    /// Resolve token values: prefer env var over direct value
    pub fn resolve_secret(direct: &Option<String>, env_key: &Option<String>) -> Option<String> {
        if let Some(key) = env_key {
            if let Ok(val) = std::env::var(key) {
                return Some(val);
            }
        }
        direct.clone()
    }
}
```

**Step 3: Create example config**

`config.example.toml`:
```toml
[gateway]
host = "127.0.0.1"
port = 18789
agent_url = "ws://127.0.0.1:18790"
log_level = "info"

[channels.telegram]
enabled = true
# Direct token (not recommended — use token_env instead)
# token = "your-bot-token"
token_env = "TELEGRAM_BOT_TOKEN"
mode = "polling"  # "polling" for dev, "webhook" for production
# webhook_url = "https://your-domain.com/webhook/telegram"
# allowed_users = []  # empty = allow all

[channels.qq]
enabled = false
app_id_env = "QQ_BOT_APP_ID"
secret_env = "QQ_BOT_SECRET"
sandbox = true

[channels.discord]
enabled = false
token_env = "DISCORD_BOT_TOKEN"
```

**Step 4: Wire config into main.rs**

Update `gateway/src/main.rs` to load config on startup.

**Step 5: Commit**

```bash
git add gateway/src/config.rs config.example.toml gateway/tests/
git commit -m "feat(gateway): add TOML configuration system"
```

---

## Task 3: Agent Bridge (Gateway ↔ Python Agent WebSocket)

**Files:**
- Create: `gateway/src/agent_bridge.rs`
- Create: `agent/` directory with Python FastAPI bridge

**Step 1: Design the bridge protocol**

The Gateway communicates with the Python Agent via WebSocket using JSON messages:

```json
// Gateway → Agent (request)
{
  "type": "chat",
  "session_id": "abc123",
  "user_id": "tg:12345",
  "channel": "telegram",
  "permission": "Authenticated",
  "text": "Hello Kokoron",
  "attachments": []
}

// Agent → Gateway (response, streamed)
{
  "type": "text_chunk",
  "session_id": "abc123",
  "content": "Hello! "
}

// Agent → Gateway (done)
{
  "type": "done",
  "session_id": "abc123"
}
```

**Step 2: Implement AgentBridge in Rust**

`gateway/src/agent_bridge.rs` — WebSocket client that connects to the Python Agent,
sends requests, and collects streamed responses.

**Step 3: Create Python Agent stub**

`agent/bridge_server.py` — minimal FastAPI + WebSocket server that:
- Receives chat requests
- Calls LLM (initially hardcoded to echo or simple response)
- Streams response chunks back

This will later be replaced/enhanced with AIKokoron's full pipeline.

**Step 4: Integration test**

Start both Gateway and Agent, send a test message, verify response flows back.

**Step 5: Commit**

```bash
git add gateway/src/agent_bridge.rs agent/
git commit -m "feat(gateway): add WebSocket bridge to Python Agent"
```

---

## Task 4: Telegram Channel — Polling Mode

**Files:**
- Modify: `channels/src/telegram.rs`
- Create: `channels/src/telegram/mod.rs` (if splitting into submodules)

**Step 1: Implement getUpdates polling loop**

The Telegram Bot API polling flow:
1. Call `GET https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id+1}`
2. Parse response → extract messages
3. Convert to `IncomingMessage`
4. Route through `MessageRouter`
5. Collect agent response
6. Call `POST https://api.telegram.org/bot{token}/sendMessage` to reply

**Step 2: Implement sendMessage**

Support text replies with Markdown formatting.

**Step 3: Handle voice messages**

Download voice file → forward as attachment to Agent → Agent transcribes via ASR.

**Step 4: Handle image messages**

Download image → forward as attachment → Agent processes via multimodal LLM.

**Step 5: Test with real Telegram bot**

1. Set `TELEGRAM_BOT_TOKEN` env var
2. Start Gateway with Telegram enabled
3. Send message to bot in Telegram
4. Verify response comes back

**Step 6: Commit**

```bash
git add channels/src/telegram.rs
git commit -m "feat(channel-tg): implement Telegram polling with text/voice/image support"
```

---

## Task 5: QQ Channel — Basic Implementation

**Files:**
- Create: `channels/src/qq.rs`

**Step 1: Implement QQ Bot API client**

QQ Bot uses WebSocket for receiving events and REST for sending messages:
1. Connect to WSS gateway (obtained via `GET /gateway`)
2. Authenticate with app_id + token
3. Listen for message events
4. Convert to `IncomingMessage` → route
5. Send response via REST API

**Step 2: Support text messages in guilds**

**Step 3: Support direct messages**

**Step 4: Test with QQ sandbox bot**

**Step 5: Commit**

```bash
git add channels/src/qq.rs
git commit -m "feat(channel-qq): implement QQ Bot with guild and DM support"
```

---

## Task 6: Permission Enforcement in Router

**Files:**
- Modify: `gateway/src/router.rs`
- Create: `gateway/src/router/permission_guard.rs`

**Step 1: Write permission test**

```rust
#[test]
fn test_public_channel_cannot_execute_tools() {
    let msg = IncomingMessage {
        permission: PermissionLevel::Public,
        // ...
    };
    assert!(!msg.permission.can_execute_tools());
}

#[test]
fn test_authenticated_channel_can_execute_tools() {
    let msg = IncomingMessage {
        permission: PermissionLevel::Authenticated,
        // ...
    };
    assert!(msg.permission.can_execute_tools());
}
```

**Step 2: Implement permission guard in router**

Before forwarding to Agent, check that the message's permission level allows the requested action. The Agent response should also be filtered — tool execution results are stripped for Public channels.

**Step 3: Commit**

```bash
git add gateway/src/router.rs
git commit -m "feat(gateway): add permission enforcement to message router"
```

---

## Task 7: Python Agent Stub (Based on AIKokoron)

**Files:**
- Create: `agent/pyproject.toml`
- Create: `agent/koclaw_agent/__init__.py`
- Create: `agent/koclaw_agent/bridge.py`
- Create: `agent/koclaw_agent/llm_router.py`

**Step 1: Set up Python project**

```toml
[project]
name = "koclaw-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.33",
    "websockets>=14",
    "anthropic>=0.40",
    "openai>=1.57",
]
```

**Step 2: Implement bridge server**

WebSocket server that:
- Receives requests from Gateway
- Routes to appropriate LLM (Claude, OpenAI, DeepSeek, local)
- Streams response chunks back

**Step 3: Implement basic LLM routing**

Reuse patterns from AIKokoron's `agent/stateless_llm/` directory:
- `D:\personal_development\AI_assistant\AIKokoron\src\open_llm_vtuber\agent\stateless_llm\` has existing Claude, OpenAI, Ollama implementations
- Adapt (not copy) the interface pattern, reference the originals

**Step 4: Test end-to-end**

Gateway (Rust) → Agent (Python) → LLM → response flows back to Gateway.

**Step 5: Commit**

```bash
git add agent/
git commit -m "feat(agent): add Python agent with LLM routing bridge"
```

---

## Task 8: Basic Encryption at Rest

**Files:**
- Modify: `common/src/crypto.rs`
- Create: `gateway/src/credential_store.rs`

**Step 1: Implement credential encryption**

Encrypt sensitive config values (bot tokens, API keys) at rest using ChaCha20-Poly1305.
On first run, generate a master key and store it in a user-only-readable file.

**Step 2: Implement encrypted memory storage**

Chat session data stored in SQLite with encrypted blobs.

**Step 3: Test encryption round-trip**

```rust
#[test]
fn test_encrypt_decrypt_roundtrip() {
    let key = generate_key();
    let plaintext = b"sensitive data";
    let ciphertext = encrypt(plaintext, &key).unwrap();
    let decrypted = decrypt(&ciphertext, &key).unwrap();
    assert_eq!(plaintext, &decrypted[..]);
}
```

**Step 4: Commit**

```bash
git add common/src/crypto.rs gateway/src/credential_store.rs
git commit -m "security(gateway): add ChaCha20 encryption for credentials and session data"
```

---

## Task 9: Docker Compose Setup

**Files:**
- Create: `Dockerfile` (multi-stage Rust build)
- Create: `agent/Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Gateway Dockerfile**

Multi-stage build: build with `rust:latest`, run with `debian:bookworm-slim`.

**Step 2: Agent Dockerfile**

Python 3.12 base, uv for dependency management.

**Step 3: Docker Compose**

Two services: gateway + agent, connected via internal network.
Environment variables for bot tokens passed through.

**Step 4: Test full stack with Docker**

```bash
docker compose up --build
```

**Step 5: Commit**

```bash
git add Dockerfile agent/Dockerfile docker-compose.yml
git commit -m "chore: add Docker Compose for full stack deployment"
```

---

## Task 10: End-to-End Integration Test

**Files:**
- Create: `tests/e2e_telegram.rs` (or `tests/e2e.py`)

**Step 1: Manual integration test**

1. Start Gateway + Agent
2. Send message to Telegram bot
3. Verify: message arrives at Gateway → routed to Agent → LLM response → sent back via Telegram
4. Test with image attachment (multimodal)
5. Test with voice message (if ASR available)

**Step 2: Document the test procedure**

Update README with "Getting Started" section.

**Step 3: Final commit**

```bash
git add tests/ README.md
git commit -m "docs: add getting started guide and integration test"
```

---

## Phase 1 Completion Checklist

- [ ] Rust workspace compiles and passes clippy
- [ ] Configuration loaded from TOML file
- [ ] Gateway ↔ Agent WebSocket bridge works
- [ ] Telegram bot responds to text messages
- [ ] QQ bot responds to text messages (if review approved)
- [ ] Permission levels enforced (Public vs Authenticated)
- [ ] Credentials encrypted at rest
- [ ] Docker Compose deployment works
- [ ] Documentation updated

## What Comes Next (Phase 2)

- E2E key exchange (X25519) for transport encryption
- Discord channel implementation
- Voice pipeline integration (ASR/TTS from AIKokoron)
- Memory system with encrypted persistence
- Tool sandbox implementation
- Persona system (Kokoron identity across channels)

## What Comes Next (Phase 3)

- Web SDK (`@koclaw/web-widget`) for shinBlog integration
- Live2D embedding for web
- RAG knowledge base
- Multi-agent orchestration
- Workflow visualization dashboard
