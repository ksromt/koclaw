# Koclaw - Project Guidelines

## Project Overview

Koclaw is a secure, cross-platform AI Agent framework that combines:
- **Rust Gateway** for memory-safe, E2E encrypted message routing
- **Python Agent Layer** (based on AIKokoron) for LLM/ML pipelines
- **Multi-channel SNS integration** (Telegram, QQ, Discord, etc.)
- **Desktop companion** with Live2D avatar (Kokoron persona)
- **Web embedding** via SDK for external projects (e.g., shinBlog)

**Unique differentiators vs Claw ecosystem:**
1. E2E encryption (server admin cannot read messages)
2. Embodied interaction (Live2D Avatar across platforms)
3. Unified identity with per-channel permission levels
4. Multimodal pipeline (voice + vision + text)

## Architecture

```
koclaw/
├── gateway/          # [Rust] Core gateway - message routing, E2E encryption, auth, sandbox
├── agent/            # [Python] Agent logic - LLM, TTS/ASR, MCP tools, RAG, memory
├── channels/         # [Rust] Channel implementations (Telegram, QQ, Discord, etc.)
├── common/           # [Rust] Shared types, traits, utilities
├── sdk/              # [TypeScript] Web embedding SDK (@koclaw/web-widget)
├── desktop/          # [Electron/React] Desktop app with Live2D (future: from AIKokoron)
├── tests/            # Integration tests
├── docs/             # Documentation
│   ├── plans/        # Implementation plans (YYYY-MM-DD-feature-name.md)
│   ├── architecture/ # Architecture decision records
│   ├── api/          # API documentation for external integrations
│   ├── integration/  # Integration guides (Blog, external projects)
│   ├── security/     # Security design documents
│   └── channels/     # Per-channel setup guides
└── scripts/          # Build, deploy, utility scripts
```

## Development Principles

### 1. No Duplicate Development
- Before writing any new code, CHECK if similar functionality exists in:
  - AIKokoron (`D:\personal_development\AI_assistant\AIKokoron`)
  - shinBlog (`D:\personal_development\shinBlog`)
  - Any existing module in this project
- If reusable code exists, extract and adapt it rather than rewriting
- Document the source of adapted code in comments

### 2. Loose Coupling / High Cohesion
- Every subsystem communicates through **well-defined traits/interfaces**
- Channels, providers, tools, and memory backends are all swappable
- No module should directly depend on another module's internals
- Use dependency injection and trait objects for extensibility
- Config-driven behavior wherever possible

### 3. Open for Extension, Closed for Modification
- New channels: implement the `Channel` trait, register in config
- New LLM providers: implement the `Provider` trait, register in config
- New tools: implement the `Tool` trait, register in config
- Adding a feature should NOT require modifying existing working code
- Use feature flags for optional compile-time features

### 4. Security First
- **E2E Encryption**: All user messages encrypted with user-held keys; server sees only ciphertext
- **Sandbox**: Agent tool execution is sandboxed (filesystem scope, command allowlist)
- **Permission Levels**: Different channels get different permission levels:
  - `Public` (Blog widget): chat only, no tool access, no private data
  - `Authenticated` (Telegram/QQ private chat): full tools, memory, file access
  - `Admin` (local desktop): unrestricted
- **No unauthorized destructive actions**: file deletion, message sending, etc. require explicit confirmation
- **Memory safety**: Rust for all security-critical paths (gateway, encryption, sandbox)
- **Credential storage**: encrypted at rest, never plaintext in config files

### 5. Code Quality Standards
- **Rust**: `cargo fmt`, `cargo clippy` (deny warnings), all tests pass before commit
- **Python**: `ruff` for linting, `mypy` for type checking, `pytest` for tests
- **TypeScript**: `eslint`, `prettier`, strict TypeScript
- **Tests**: Every new feature needs tests. Prefer integration tests for cross-module behavior
- **Comments**: Only where logic isn't self-evident. No obvious comments
- **Error handling**: Use `Result<T, E>` in Rust, typed exceptions in Python. No silent failures

### 6. Commit Conventions
- Format: `type(scope): description`
- Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `security`
- Scopes: `gateway`, `agent`, `channel-tg`, `channel-qq`, `channel-dc`, `sdk`, `common`, `docs`
- Examples:
  - `feat(channel-tg): add voice message support`
  - `security(gateway): implement E2E key exchange`
  - `docs(api): add web widget integration guide`

### 7. Documentation Requirements
- Architecture decisions go in `docs/architecture/`
- Implementation plans go in `docs/plans/`
- API docs for external consumers go in `docs/api/`
- Channel-specific setup guides go in `docs/channels/`
- Update this CLAUDE.md when project conventions change

## Implementation Status

| Phase | Status | Commit | Tests |
|-------|--------|--------|-------|
| Phase 1: Gateway Core + Channels | ✅ Complete | `421fb2d`..`60cb166` | 31 Rust |
| Phase 2: Security, Discord, Memory & Persona | ✅ Complete | `408342f` | 35 Rust |
| Phase 3: AIKokoron Integration | ✅ Complete | `bbd15a2` | 35 Rust + 14 Python |
| Phase 3.5: Live Testing & Fixes | ✅ Complete | uncommitted | 35 Rust + 14 Python |
| Phase 4: MCP & ClawHub Compatibility | 📋 Planned | — | 30 new (planned) |

### Phase 3 Key Components
- **Unified Persona**: `persona.yaml` — single YAML config for both Rust and Python runtimes
- **Conversation Memory**: `agent/koclaw_agent/memory/` — FileMemory (JSON per session)
- **Expression System**: `agent/koclaw_agent/expression.py` — `[joy]`, `[anger]` tag extraction for Live2D
- **Voice Pipeline**: `agent/koclaw_agent/voice/` — GPT-SoVITS TTS + Faster-Whisper ASR (optional deps)
- **WebSocket Channel**: `channels/src/websocket_channel.rs` — port 18791 for Desktop/Web
- **Static File Server**: `gateway/src/static_server.rs` — port 18792 for Live2D assets
- **Frontend Config**: `desktop/koclaw-config.json` — AIKokoron Electron connection config

### Port Map
| Port | Service |
|------|---------|
| 18789 | Gateway HTTP API |
| 18790 | Gateway ↔ Agent WebSocket bridge |
| 18791 | WebSocket channel (Desktop/Web clients) |
| 18792 | Static file server (Live2D models, voice assets) |

### Pending (Not Yet Implemented)
- MCP Host integration (Python Agent as MCP client) — plan at `docs/plans/2026-03-01-phase4-mcp-and-clawhub.md`
- ClawHub skill compatibility (SKILL.md parser, registry client)
- Web SDK (`@koclaw/web-widget` npm package) — API docs ready, no source code yet
- True zero-knowledge E2E encryption (Agent-held keys)
- RAG knowledge base integration
- Multi-agent orchestration
- Double Ratchet forward secrecy

## Related Projects

| Project | Path | Relationship |
|---------|------|-------------|
| AIKokoron | `D:\personal_development\AI_assistant\AIKokoron` | Source of Agent logic, TTS/ASR pipeline, Live2D frontend |
| shinBlog | `D:\personal_development\shinBlog` | External consumer of Koclaw SDK (web widget + chat API) |

### Cross-Project References for shinBlog
When working on shinBlog and need to integrate with Koclaw:
- **API Reference**: `D:\personal_development\Koclaw\docs\api\gateway-api.md` (612 lines, complete WebSocket/SSE protocol)
- **Web SDK Spec**: `D:\personal_development\Koclaw\docs\api\web-sdk-api.md` (596 lines, React component API design)
- **Integration Guide**: `D:\personal_development\Koclaw\docs\integration\shinblog-integration.md` (example Next.js proxy route)
- **Persona Config**: `D:\personal_development\Koclaw\persona.yaml` (Kokoron identity and voice settings)

## Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Gateway | Rust (tokio) | Memory safety, performance, E2E encryption |
| Agent | Python (FastAPI) | ML ecosystem, existing AIKokoron code |
| Desktop | Electron + React | Existing AIKokoron frontend, Live2D SDK |
| Web SDK | TypeScript | npm distribution for blog/web integration |
| Database | SQLite (embedded) / PostgreSQL (server) | Flexibility for different deployment scales |
| Encryption | X25519 + ChaCha20-Poly1305 | Modern, fast, used by WireGuard/Signal |
| IPC | WebSocket + Protocol Buffers | Efficient binary protocol between Gateway and Agent |

## Build & Run

```bash
# Gateway (Rust)
cd gateway && cargo build --release

# Agent (Python)
cd agent && uv sync && uv run python -m koclaw_agent

# Full stack (Docker)
docker compose up
```

## Environment Variables

```
# Required
KOCLAW_ENCRYPTION_KEY=       # Master encryption key (generated on first run)
KOCLAW_AGENT_URL=            # Agent WebSocket URL (default: ws://127.0.0.1:18790)

# LLM Providers (at least one required)
ANTHROPIC_API_KEY=           # Claude API
OPENAI_API_KEY=              # OpenAI API
DEEPSEEK_API_KEY=            # DeepSeek API

# Channels (configure as needed)
TELEGRAM_BOT_TOKEN=          # From @BotFather
QQ_BOT_APP_ID=               # From q.qq.com
QQ_BOT_SECRET=               # From q.qq.com
DISCORD_BOT_TOKEN=           # From Discord Developer Portal

# Optional
KOCLAW_LOG_LEVEL=info        # trace, debug, info, warn, error
KOCLAW_SANDBOX_ROOT=./workspace  # Agent workspace root
```
