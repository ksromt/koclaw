# Koclaw

**Secure, Cross-Platform AI Agent Framework**

Koclaw is a production-oriented AI Agent framework that bridges conversational AI with real-world messaging platforms through a memory-safe Rust gateway, a flexible Python agent layer, and end-to-end encryption. It provides a unified identity for an AI persona ("Kokoron") across Telegram, QQ, Discord, a desktop companion with Live2D avatar, and embeddable web widgets.

---

## Table of Contents

- [Vision](#vision)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Supported Channels](#supported-channels)
- [Supported LLM Providers](#supported-llm-providers)
- [Security](#security)
- [Comparison with Claw Ecosystem](#comparison-with-claw-ecosystem)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## Vision

Modern AI assistants are fragmented across platforms -- each with its own integration, its own identity, its own security model. Koclaw unifies them:

- **One persona, many channels.** A single AI agent (Kokoron) accessible on Telegram, QQ, Discord, desktop, and the web, with consistent personality and memory.
- **Security by design.** End-to-end encryption ensures that even a compromised server cannot read user messages. Permission levels enforce what the agent can do based on where it is invoked.
- **Extensibility without modification.** Adding a new channel, LLM provider, or tool requires implementing a trait and registering it in config -- no existing code needs to change.
- **Multimodal pipeline.** Text, voice, vision, and document understanding flow through the same framework, powered by the best available models.

---

## Key Features

- **Rust Gateway** -- Memory-safe message routing, authentication, rate limiting, and sandbox enforcement. Zero-cost abstractions for high-throughput message handling.
- **Python Agent Layer** -- LLM orchestration, tool execution, RAG retrieval, and voice pipeline (ASR/TTS), built on patterns from AIKokoron.
- **End-to-End Encryption** -- X25519 key exchange with ChaCha20-Poly1305 session encryption. User private keys never leave the user device.
- **Multi-Channel SNS Integration** -- Telegram, QQ, and Discord with a trait-based architecture that makes adding channels trivial.
- **Desktop Companion** -- Electron/React application with Live2D avatar for an embodied conversational experience.
- **Web Embedding SDK** -- `@koclaw/web-widget` npm package for dropping Kokoron into any website (e.g., shinBlog).
- **Permission-Based Security** -- Three-tier permission model (Public, Authenticated, Admin) tied to channel origin.
- **Config-Driven Architecture** -- TOML configuration with environment variable support. No code changes needed to enable/disable channels or switch providers.
- **Encrypted Memory** -- Conversation history and user memories encrypted at rest using per-user derived keys.
- **Sandboxed Tool Execution** -- Filesystem scope, command allowlists, and permission guards prevent agent misuse.

---

## Architecture

```
                    +--------------------------------------------+
                    |              User Devices                   |
                    |                                             |
                    |  +----------+ +--------+ +--------------+  |
                    |  | Desktop  | | Mobile | | Web Browser  |  |
                    |  | (Live2D) | | (SNS)  | | (Blog Chat)  |  |
                    |  +----+-----+ +---+----+ +------+-------+  |
                    +-------|-----------|--------------|---------+
                            |           |              |
                    +-------v-----------v--------------v---------+
                    |         E2E Encrypted Transport             |
                    |    (X25519 + ChaCha20-Poly1305)             |
                    +-----------------------+---------------------+
                                            |
+-------------------------------------------v-----------------------------------------+
|                        Koclaw Gateway (Rust)                                         |
|                                                                                      |
|  +-------------+  +--------------+  +-------------+  +---------------+               |
|  |  Channels   |  | Auth/Crypto  |  |   Router    |  |   Sandbox     |               |
|  |             |  |              |  |             |  |               |               |
|  |  Telegram   |  | E2E Encrypt  |  | Message     |  | Filesystem    |               |
|  |  QQ         |  | Key Mgmt     |  | Routing     |  | Command       |               |
|  |  Discord    |  | Session      |  | Rate Limit  |  | Allowlist     |               |
|  |  WebSocket  |  | Permissions  |  | Queue       |  | Permission    |               |
|  |  Web SDK    |  |              |  |             |  | Levels        |               |
|  +------+------+  +--------------+  +------+------+  +---------------+               |
|         |                                  |                                          |
|         +----------------------------------+                                          |
|                         |                                                             |
|  +----------------------v------------------------------------------------------+     |
|  |                 Agent Bridge (WebSocket / Protocol Buffers)                  |     |
|  |              Gateway <-> Python Agent communication                         |     |
|  +----------------------+------------------------------------------------------+     |
+--------------------------|---------------------------------------------------------+
                           |
+--------------------------v---------------------------------------------------------+
|                     Koclaw Agent (Python / FastAPI)                                  |
|                                                                                      |
|  +--------------+  +--------------+  +--------------+  +-------------+               |
|  | LLM Router   |  | Memory       |  | Tool Engine  |  | Voice       |               |
|  |              |  |              |  | (MCP+)       |  | Pipeline    |               |
|  | Claude       |  | Short-term   |  |              |  |             |               |
|  | OpenAI       |  | Long-term    |  | Shell        |  | ASR         |               |
|  | DeepSeek     |  | Encrypted    |  | Search       |  | TTS         |               |
|  | Ollama       |  | RAG Index    |  | File Ops     |  | VAD         |               |
|  +--------------+  +--------------+  +--------------+  +-------------+               |
|                                                                                      |
|  +--------------------------------------------------------------------------+       |
|  |                    Persona System (Kokoron)                               |       |
|  |  Identity / Personality / Per-channel behavior adaptation                 |       |
|  +--------------------------------------------------------------------------+       |
+--------------------------------------------------------------------------------------+
```

### Workspace Structure

```
koclaw/
|-- gateway/          # [Rust] Core gateway binary -- routing, auth, encryption, sandbox
|-- agent/            # [Python] Agent logic -- LLM, TTS/ASR, MCP tools, RAG, memory
|-- channels/         # [Rust] Channel implementations (Telegram, QQ, Discord)
|-- common/           # [Rust] Shared types, traits, error types, crypto primitives
|-- sdk/              # [TypeScript] Web embedding SDK (@koclaw/web-widget)
|-- desktop/          # [Electron/React] Desktop app with Live2D (from AIKokoron)
|-- tests/            # Integration and end-to-end tests
|-- docs/             # Project documentation
|   |-- plans/        # Implementation plans (YYYY-MM-DD-feature-name.md)
|   |-- architecture/ # Architecture decision records and design docs
|   |-- api/          # API documentation for external integrations
|   |-- integration/  # Integration guides (shinBlog, external projects)
|   |-- security/     # Security design documents
|   `-- channels/     # Per-channel setup and configuration guides
`-- scripts/          # Build, deploy, and utility scripts
```

---

## Tech Stack

| Component       | Technology                        | Rationale                                           |
|-----------------|-----------------------------------|-----------------------------------------------------|
| Gateway         | Rust (tokio, axum)                | Memory safety, zero-cost abstractions, performance  |
| Agent           | Python (FastAPI, uvicorn)         | ML ecosystem access, existing AIKokoron codebase    |
| Desktop         | Electron + React                  | Existing AIKokoron frontend, Live2D SDK support     |
| Web SDK         | TypeScript (React)                | npm distribution for blog/web integration           |
| IPC Protocol    | WebSocket + JSON (Protocol Buffers planned) | Efficient bridge between Gateway and Agent |
| Database        | SQLite (embedded) / PostgreSQL    | Flexibility for single-user and multi-user deploys  |
| Encryption      | X25519 + ChaCha20-Poly1305       | Modern AEAD, used by WireGuard and Signal           |
| Key Derivation  | HKDF-SHA256                       | Standards-compliant key derivation                  |
| Serialization   | serde + serde_json, TOML          | Rust ecosystem standard, human-readable config      |
| HTTP Client     | reqwest (rustls-tls)              | Async HTTP with pure-Rust TLS                       |
| Logging         | tracing + tracing-subscriber      | Structured, async-aware logging with filtering      |
| Error Handling  | thiserror + anyhow                | Typed errors for libraries, flexible errors for app |

---

## Quick Start

### Prerequisites

| Requirement     | Minimum Version | Installation                              |
|-----------------|-----------------|-------------------------------------------|
| Rust            | 1.85+ (2024 edition) | `rustup default stable`              |
| Python          | 3.10+           | https://python.org or system package      |
| uv (Python)     | 0.5+            | `pip install uv` or https://docs.astral.sh/uv |
| Node.js         | 20+ (for SDK)   | https://nodejs.org                        |
| Git             | 2.x             | https://git-scm.com                       |

### Clone and Build

```bash
# Clone the repository
git clone https://github.com/yourusername/koclaw.git
cd koclaw

# Build the Rust gateway
cargo build --release

# Set up the Python agent
cd agent
uv sync
cd ..
```

### Configure

```bash
# Copy the example configuration
cp config.example.toml config.toml

# Edit config.toml with your settings (channels, tokens, etc.)
# Or set environment variables:
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

### Run

```bash
# Start the Python Agent (in one terminal)
cd agent && uv run python -m koclaw_agent

# Start the Rust Gateway (in another terminal)
cargo run --release

# Or use Docker Compose for the full stack:
docker compose up --build
```

---

## Configuration

Koclaw uses a TOML configuration file (`config.toml`) with environment variable overrides. See `config.example.toml` for a fully annotated template.

### Gateway Settings

```toml
[gateway]
host = "127.0.0.1"       # Bind address
port = 18789              # Gateway port
agent_url = "ws://127.0.0.1:18790"  # Python Agent WebSocket URL
log_level = "info"        # trace, debug, info, warn, error
```

### Channel Configuration

```toml
[channels.telegram]
enabled = true
token_env = "TELEGRAM_BOT_TOKEN"   # Prefer env vars over inline tokens
mode = "polling"                    # "polling" (dev) or "webhook" (prod)
# webhook_url = "https://your-domain.com/webhook/telegram"
# allowed_users = []               # Empty = allow all users

[channels.qq]
enabled = false
app_id_env = "QQ_BOT_APP_ID"
secret_env = "QQ_BOT_SECRET"
sandbox = true                      # Use sandbox mode for development

[channels.discord]
enabled = false
token_env = "DISCORD_BOT_TOKEN"
```

### Environment Variables

```
# Required
KOCLAW_ENCRYPTION_KEY=           # Master encryption key (auto-generated on first run)
KOCLAW_AGENT_URL=                # Agent WebSocket URL (default: ws://127.0.0.1:18790)

# LLM Providers (at least one required)
ANTHROPIC_API_KEY=               # Claude API key
OPENAI_API_KEY=                  # OpenAI API key
DEEPSEEK_API_KEY=                # DeepSeek API key

# Channels (configure as needed)
TELEGRAM_BOT_TOKEN=              # From @BotFather
QQ_BOT_APP_ID=                   # From q.qq.com developer portal
QQ_BOT_SECRET=                   # From q.qq.com developer portal
DISCORD_BOT_TOKEN=               # From Discord Developer Portal

# Optional
KOCLAW_LOG_LEVEL=info            # Logging verbosity
KOCLAW_SANDBOX_ROOT=./workspace  # Agent sandbox root directory
```

---

## Supported Channels

| Channel     | Protocol                | Status         | Permission Level | Notes                                     |
|-------------|-------------------------|----------------|------------------|--------------------------------------------|
| Telegram    | Bot API (polling/webhook)| In Progress    | Authenticated   | Text, voice, images, files, inline keyboards |
| QQ          | Official Bot API (WS+REST)| In Progress  | Authenticated   | Guild messages, DMs, rich cards             |
| Discord     | Bot API (gateway WS)   | In Progress    | Authenticated   | Text, voice channels, slash commands        |
| WebSocket   | Raw WebSocket           | Planned        | Authenticated   | Desktop companion connection                |
| Web Public  | REST + SSE              | Planned        | Public           | Blog widget chat (shinBlog integration)     |

### Permission Levels

| Level           | Channels                              | Capabilities                                              |
|-----------------|---------------------------------------|-----------------------------------------------------------|
| `Public`        | Blog widget, public web endpoints     | Chat only, no tools, no private data, rate limited        |
| `Authenticated` | Telegram, QQ, Discord private chat    | Full tools, memory access, file access within sandbox     |
| `Admin`         | Desktop app, designated admin users   | Unrestricted, configuration changes, system management    |

---

## Supported LLM Providers

| Provider     | Streaming | Vision  | Tool Use | Status         |
|--------------|-----------|---------|----------|----------------|
| Claude (Anthropic) | Yes  | Yes     | Yes      | Planned        |
| OpenAI (GPT) | Yes      | Yes     | Yes      | Planned        |
| DeepSeek     | Yes       | Yes     | Yes      | Planned        |
| Ollama (Local) | Yes    | Model-dependent | Model-dependent | Planned |

Provider selection is config-driven. The Agent routes requests to the appropriate provider based on configuration and optionally per-channel overrides.

---

## Security

Koclaw takes a defense-in-depth approach to security:

### End-to-End Encryption

- **Key Exchange:** X25519 Elliptic Curve Diffie-Hellman for session establishment.
- **Session Encryption:** ChaCha20-Poly1305 AEAD for all message payloads.
- **Key Derivation:** HKDF-SHA256 with domain-separated context strings.
- **Nonce Management:** Unique nonces per message prevent replay attacks.
- **Phase 1 (current):** Server-mediated E2E -- protects against network eavesdropping. Gateway decrypts to forward to Agent.
- **Phase 2 (planned):** True zero-knowledge E2E -- Gateway acts as a pure relay, cannot decrypt messages.

### Memory Safety

The Gateway is written entirely in Rust, eliminating buffer overflows, use-after-free, and data races at compile time. All security-critical paths (encryption, authentication, permission enforcement) are in Rust.

### Sandboxed Execution

- Agent tool execution is confined to a designated workspace directory.
- Command execution uses an allowlist -- only pre-approved commands can run.
- File operations are scoped to the sandbox root.
- Destructive actions (file deletion, message sending) require explicit confirmation.

### Credential Protection

- Bot tokens and API keys are encrypted at rest using ChaCha20-Poly1305.
- A master key is generated on first run and stored with restrictive file permissions.
- Environment variables are preferred over inline configuration for secrets.
- Secrets are never logged, even at trace level.

### Permission Enforcement

Every incoming message carries a permission level derived from its channel of origin. The Router enforces these permissions before forwarding to the Agent, and filters Agent responses to strip unauthorized content (e.g., tool execution results from Public channels).

For the full security design, see [docs/security/encryption-design.md](docs/security/encryption-design.md).

---

## Comparison with Claw Ecosystem

Koclaw was designed to address specific gaps in the existing Claw ecosystem (OpenClaw, PicoClaw, ZeroClaw):

| Feature                      | OpenClaw       | PicoClaw       | ZeroClaw       | **Koclaw**           |
|------------------------------|----------------|----------------|----------------|----------------------|
| Language                     | Python         | Python         | Python         | **Rust + Python**    |
| E2E Encryption               | No             | No             | No             | **Yes (X25519 + ChaCha20)** |
| Memory Safety                | Runtime        | Runtime        | Runtime        | **Compile-time (Rust)** |
| Live2D Avatar                | No             | No             | No             | **Yes (Kokoron)**    |
| Unified Cross-Platform Identity | Limited     | No             | No             | **Yes**              |
| Multi-Channel SNS            | Partial        | Minimal        | No             | **Telegram, QQ, Discord, Web** |
| Multimodal Pipeline          | Text           | Text           | Text           | **Text + Voice + Vision** |
| Permission Levels            | Basic          | None           | None           | **Three-tier (Public/Auth/Admin)** |
| Web Embedding SDK            | No             | No             | No             | **@koclaw/web-widget** |
| Sandbox Enforcement          | Basic          | No             | No             | **Filesystem + command allowlist** |
| Encrypted Memory             | No             | No             | No             | **Yes (per-user keys)** |
| Config-Driven Architecture   | Partial        | No             | No             | **Full TOML + env vars** |

### When to Choose Koclaw

- You need E2E encryption for user privacy.
- You want a single AI persona across multiple messaging platforms.
- You need an embodied AI experience (Live2D avatar on desktop and web).
- You require compile-time memory safety for security-critical infrastructure.
- You want to embed an AI chat widget in an existing website.
- You need fine-grained permission control based on access context.

---

## Development

### Building from Source

```bash
# Compile in debug mode (faster builds, slower runtime)
cargo build

# Compile in release mode (optimized, stripped binary)
cargo build --release

# Run clippy linter
cargo clippy -- -W clippy::all

# Run tests
cargo test

# Format code
cargo fmt
```

### Running Tests

```bash
# Run all Rust tests
cargo test

# Run tests for a specific crate
cargo test -p koclaw-common
cargo test -p koclaw-gateway
cargo test -p koclaw-channels

# Run Python agent tests
cd agent && uv run pytest
```

### Project Conventions

- **Commit format:** `type(scope): description` (e.g., `feat(channel-tg): add voice message support`)
- **Types:** feat, fix, refactor, docs, test, chore, security
- **Scopes:** gateway, agent, channel-tg, channel-qq, channel-dc, sdk, common, docs
- **Code style:** `cargo fmt` for Rust, `ruff` for Python, `prettier` for TypeScript
- **Error handling:** `Result<T, E>` everywhere in Rust, typed exceptions in Python

For the full development guide, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Roadmap

### Phase 1 -- Gateway Core + Channels (Current)

- [x] Rust workspace with common, gateway, and channels crates
- [x] Core trait definitions (Channel, MessageRouter, PermissionLevel) with dyn-compatible BoxFuture pattern
- [x] IncomingMessage / OutgoingMessage data model
- [x] Configuration system (TOML + env vars with secret resolution)
- [x] Gateway-to-Agent WebSocket bridge (session-based response multiplexing)
- [x] Telegram channel implementation (polling mode with text/voice/image)
- [x] QQ channel implementation (WebSocket gateway + REST API)
- [x] Permission enforcement in Router (Public/Authenticated/Admin)
- [x] Python Agent stub with LLM routing (Claude, OpenAI, DeepSeek, Ollama)
- [x] Basic encryption at rest (ChaCha20-Poly1305 for credentials and session data)
- [x] Docker Compose deployment (Gateway + Agent)
- [ ] End-to-end integration tests

### Phase 2 -- Security, Discord, Memory & Persona (Current)

- [x] X25519 key exchange with HKDF-SHA256 session key derivation (4 tests)
- [x] Discord channel implementation (WebSocket Gateway + REST API)
- [x] Encrypted memory system with SQLite + ChaCha20-Poly1305 (7 tests)
- [x] Persona system with per-channel identity management (4 tests)
- [x] Tool sandbox with path validation and command allowlist (6 tests)
- [x] Persona + Sandbox wired into Agent Bridge protocol
- [ ] Voice pipeline integration (ASR/TTS from AIKokoron)
- [ ] True zero-knowledge E2E encryption (Agent-held keys)

### Phase 3 -- Web SDK, Desktop, and Advanced Features

- [ ] Web SDK (`@koclaw/web-widget`) for shinBlog integration
- [ ] Live2D avatar embedding for web
- [ ] RAG knowledge base integration
- [ ] Desktop companion application (Electron + Live2D)
- [ ] Multi-agent orchestration
- [ ] Workflow visualization dashboard
- [ ] Double Ratchet forward secrecy

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Related Projects

| Project    | Relationship                                                              |
|------------|---------------------------------------------------------------------------|
| AIKokoron  | Source of Agent logic, TTS/ASR pipeline, Live2D frontend                  |
| shinBlog   | External consumer of Koclaw SDK (web widget + chat API integration)       |
