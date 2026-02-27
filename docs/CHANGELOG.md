# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - Unreleased

Phase 1: Gateway Core + Telegram & QQ Channels

### Added

- **Workspace Structure**
  - Rust workspace with three crates: `koclaw-common`, `koclaw-gateway`, `koclaw-channels`.
  - Workspace-level dependency management with shared versions.
  - Release profile optimized for binary size (LTO, single codegen unit, stripped).

- **Core Traits and Types** (`koclaw-common`)
  - `Channel` trait for communication channel implementations.
  - `MessageRouter` trait for central message routing.
  - `ChannelType` enum with variants: Telegram, QQ, Discord, WebSocket, WebPublic.
  - `IncomingMessage` and `OutgoingMessage` data models with full serialization support.
  - `Attachment` type supporting Image, Voice, Video, and File attachment types.
  - `PermissionLevel` enum (Public, Authenticated, Admin) with capability check methods.
  - `KoclawError` enum with structured error variants for channels, encryption, auth, permissions, agent, and configuration.
  - Placeholder module for E2E encryption primitives (X25519 + ChaCha20-Poly1305).

- **Configuration System** (`koclaw-gateway`)
  - TOML configuration file loading (`config.toml`) with `config.example.toml` template.
  - Environment variable resolution for secrets (`token_env`, `secret_env` fields).
  - Per-channel configuration with enable/disable toggles.
  - Gateway settings: host, port, agent URL, log level.

- **Gateway Binary** (`koclaw-gateway`)
  - Entry point with tokio async runtime and structured logging via `tracing`.
  - Environment-based log level configuration.
  - Graceful shutdown on Ctrl+C signal.
  - `Router` struct with full message pipeline: permission enforcement, agent forwarding, streaming response collection, and channel response delivery.
  - `AgentBridge` WebSocket client with session-based response multiplexing (`HashMap<session_id, mpsc::Sender>`).
  - Channel startup wiring: config-driven channel registration and background task spawning.

- **Channel Implementations** (`koclaw-channels`)
  - Feature-flag-based channel compilation (telegram, qq, discord).
  - `TelegramChannel`: Bot API polling mode with text, voice, and image message support. Allowed users filtering.
  - `QQChannel`: Official Bot API with OAuth2 token management, WebSocket gateway connection (stub), guild and DM message support.
  - Dyn-compatible `Channel` trait using `BoxFuture` pattern (required for trait object dispatch).
  - Conditional module exports based on enabled features.

- **Encryption** (`koclaw-common`)
  - ChaCha20-Poly1305 AEAD encryption for credentials at rest.
  - Random key generation and nonce management.
  - Config value encrypt/decrypt helpers.
  - 5 unit tests for encryption round-trip, tampered ciphertext, wrong key, and empty plaintext.

- **Python Agent Stub** (`agent/`)
  - FastAPI WebSocket bridge server for Gateway communication.
  - LLM router with provider selection (Claude, OpenAI, DeepSeek, Ollama).
  - Streaming response chunks back to Gateway.
  - Configuration via environment variables.

- **Docker Deployment**
  - Multi-stage Rust Dockerfile (build with `rust:latest`, run with `debian:bookworm-slim`).
  - Python Agent Dockerfile with uv for dependency management.
  - `docker-compose.yml` with gateway + agent services and internal networking.

- **Documentation**
  - `CLAUDE.md` project guidelines with architecture, principles, and conventions.
  - Architecture overview with ASCII system diagram (`docs/architecture/overview.md`).
  - E2E encryption design document (`docs/security/encryption-design.md`).
  - Telegram channel setup guide (`docs/channels/telegram.md`).
  - QQ channel setup guide (`docs/channels/qq.md`).
  - shinBlog integration guide (`docs/integration/shinblog-integration.md`).
  - Phase 1 implementation plan (`docs/plans/2026-02-27-phase1-gateway-and-channels.md`).
  - Comprehensive README with architecture, features, and quick start guide.
  - Gateway API reference (`docs/api/gateway-api.md`).
  - Web SDK API reference (`docs/api/web-sdk-api.md`).
  - Core traits design document (`docs/architecture/trait-design.md`).
  - Development guide (`docs/DEVELOPMENT.md`).

### Remaining (In Progress for v0.1.0)

- End-to-end integration tests (Gateway + Agent + Channel round-trip).

---

## [0.2.0] - Unreleased

Phase 2: Security, Discord, Memory & Persona

### Added

- **X25519 Key Exchange** (`koclaw-common`)
  - `generate_keypair()` for X25519 keypair generation.
  - `derive_shared_secret()` for Diffie-Hellman shared secret.
  - `derive_session_key()` with HKDF-SHA256 and domain-separated context strings.
  - 4 unit tests: key exchange, session derivation, session encrypt/decrypt, context separation.

- **Discord Channel** (`koclaw-channels`)
  - `DiscordChannel` implementing the `Channel` trait via WebSocket Gateway.
  - Full Gateway lifecycle: HELLO, IDENTIFY, heartbeat, MESSAGE_CREATE event handling.
  - REST API message sending with reply support.
  - Intents: GUILD_MESSAGES, MESSAGE_CONTENT, DIRECT_MESSAGES.
  - `DiscordConfig::resolve_token()` for config-driven token resolution.
  - Wired into `main.rs` channel startup.

- **Encrypted Memory System** (`koclaw-common`)
  - `MemoryStore` backed by SQLite with ChaCha20-Poly1305 encrypted values.
  - Operations: store, retrieve, delete, list_keys (prefix), count.
  - In-memory constructor for testing.
  - 7 unit tests: store/retrieve, missing key, overwrite, delete, prefix list, wrong key, count.

- **Persona System** (`koclaw-common` + `agent/`)
  - `Persona` struct with base prompt, per-channel overrides, and display name.
  - `system_prompt(channel)` returns channel-appropriate prompt.
  - Default `Persona::kokoron()` with WebPublic blog assistant override.
  - Python `Persona` dataclass mirroring Rust types.
  - 4 unit tests: default prompt, channel override, default name, name override.

- **Tool Sandbox** (`koclaw-common`)
  - `SandboxConfig` with path validation and command allowlist.
  - `validate_path()` prevents directory traversal attacks.
  - `validate_command()` checks against explicit allowlist.
  - 6 unit tests: valid path, escape blocked, dotdot escape, valid/blocked commands, default empty.

- **Agent Bridge Protocol Extension** (`koclaw-gateway` + `agent/`)
  - `ChatContext` struct carrying system_prompt and sandbox config.
  - `AgentRequest` extended with `system_prompt`, `sandbox_root`, `allowed_commands` fields.
  - Router injects persona system prompt per channel into agent requests.
  - Python bridge passes system_prompt through to LLM providers.
  - Both Anthropic and OpenAI providers accept dynamic system_prompt.

---

## [0.3.0] - Unreleased

Phase 3: AIKokoron Integration (Voice, Memory, Expression, WebSocket)

### Added

- **Unified Persona YAML** (`persona.yaml`)
  - Single source of truth for Kokoron identity across Rust and Python runtimes.
  - `Persona::from_yaml()` in Rust (`serde_yaml`), `Persona.from_yaml_file()` in Python (`pyyaml`).
  - Channel-specific prompt overrides, Live2D expression mapping, voice config.
  - 4 additional persona unit tests (YAML full, minimal, unknown channel, invalid).

- **Conversation Memory System** (`agent/koclaw_agent/memory/`)
  - `BaseMemory` abstract base class with `get_history()`, `add_message()`, `clear_history()`, `list_sessions()`.
  - `FileMemory` implementation: JSON file per session with `asyncio.Lock` for thread-safety.
  - Safe session ID naming (colons → underscores for file-safe paths).
  - History injected into LLM context via updated provider interfaces.
  - 7 unit tests: add/get, separate sessions, empty, limit, clear, colon IDs, list sessions.

- **Expression Extraction** (`agent/koclaw_agent/expression.py`)
  - Regex-based extraction of known expression tags: `[joy]`, `[anger]`, `[sadness]`, `[surprise]`, `[thinking]`, `[neutral]`.
  - Unknown tags preserved in clean text, known tags stripped.
  - Case-insensitive matching.
  - 7 unit tests: single, multiple, none, unknown, all known, case insensitive, empty.

- **GPT-SoVITS TTS** (`agent/koclaw_agent/voice/gpt_sovits.py`)
  - HTTP client calling external GPT-SoVITS server (default: `http://127.0.0.1:9880/tts`).
  - Support for reference WAV for voice cloning.
  - Async interface via `httpx.AsyncClient`.

- **Faster-Whisper ASR** (`agent/koclaw_agent/voice/faster_whisper_asr.py`)
  - Local speech-to-text with lazy model loading.
  - CPU-bound transcription offloaded via `asyncio.get_running_loop().run_in_executor()`.
  - Configurable model size and compute type.

- **WebSocket Channel** (`channels/src/websocket_channel.rs`)
  - `WebSocketChannel` implementing `Channel` trait on port 18791.
  - Client connection tracking with `Arc<RwLock<HashMap>>`.
  - Protocol: `text-input` → Gateway routing → `full-text` response.
  - Feature-gated (`websocket` feature flag).

- **Extended Bridge Protocol** (`gateway/src/agent_bridge.rs`, `gateway/src/router.rs`)
  - `AgentResponseChunk` extended with `data`, `format`, `expressions` fields.
  - Router captures audio data and expressions from agent stream.
  - WebSocket clients receive audio as `Attachment` in `OutgoingMessage`.

- **Static File Server** (`gateway/src/static_server.rs`)
  - axum + tower-http `ServeDir` with permissive CORS.
  - Serves Live2D models and voice assets on port 18792.
  - Config-driven via `[gateway.static_files]` in TOML.

- **Frontend Adapter** (`desktop/koclaw-config.json`)
  - Connection config for AIKokoron Electron app.
  - WebSocket URL (port 18791) + static assets URL (port 18792).

- **Agent Bridge Enhancements** (`agent/koclaw_agent/bridge.py`)
  - Memory integration: load/save history per session.
  - Persona initialization on bridge startup.
  - Expression extraction on LLM responses.
  - TTS synthesis after text response (when `audio_response=True`).
  - ASR transcription for `audio_input` message type.
  - Graceful degradation when voice deps missing (`try/except ImportError`).

- **LLM Provider Updates** (`agent/koclaw_agent/providers/`)
  - `history` parameter added to `BaseProvider.generate()`, `OpenAIProvider`, `AnthropicProvider`.
  - History injected between system prompt and current user message.

---

## Future Releases

### [0.4.0] - Planned

Phase 4: Web SDK, Desktop Polish, and Advanced Features

- Web SDK (`@koclaw/web-widget`) for shinBlog integration (API spec ready at `docs/api/web-sdk-api.md`).
- Live2D avatar embedding for web.
- RAG knowledge base integration.
- Desktop companion application (Electron + Live2D) full integration.
- Multi-agent orchestration.
- Workflow visualization dashboard.
- Double Ratchet forward secrecy.
