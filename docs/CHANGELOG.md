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

- **Gateway Binary** (`koclaw-gateway`)
  - Entry point with tokio async runtime and structured logging via `tracing`.
  - Environment-based log level configuration.
  - Graceful shutdown on Ctrl+C signal.
  - `Router` struct implementing the `MessageRouter` trait (message routing skeleton).

- **Channel Implementations** (`koclaw-channels`)
  - Feature-flag-based channel compilation (telegram, qq, discord).
  - `TelegramChannel` struct implementing the `Channel` trait (skeleton).
  - Conditional module exports based on enabled features.

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

### Planned (In Progress for v0.1.0)

- TOML configuration system with environment variable resolution.
- Gateway-to-Agent WebSocket bridge for Python Agent communication.
- Telegram channel: polling mode with text, voice, and image support.
- QQ channel: Official Bot API with guild messages and direct messages.
- Permission enforcement in the Router (Public vs Authenticated vs Admin).
- Python Agent stub with LLM routing (Claude, OpenAI, DeepSeek).
- ChaCha20-Poly1305 encryption for credentials at rest.
- Encrypted session data storage in SQLite.
- Docker Compose deployment (Gateway + Agent).
- End-to-end integration tests.

---

## Future Releases

### [0.2.0] - Planned

Phase 2: Security, Voice, and Memory

- X25519 key exchange for transport encryption.
- Discord channel implementation.
- Voice pipeline integration (ASR/TTS from AIKokoron).
- Encrypted memory system with persistence.
- Tool sandbox implementation (filesystem scope, command allowlist).
- Persona system (Kokoron identity across channels).
- True zero-knowledge E2E encryption (Agent-held keys).

### [0.3.0] - Planned

Phase 3: Web SDK, Desktop, and Advanced Features

- Web SDK (`@koclaw/web-widget`) for shinBlog integration.
- Live2D avatar embedding for web.
- RAG knowledge base integration.
- Desktop companion application (Electron + Live2D).
- Multi-agent orchestration.
- Workflow visualization dashboard.
- Double Ratchet forward secrecy.
