# Development Guide

This guide covers everything you need to build, test, and contribute to Koclaw. It includes environment setup, project structure, step-by-step guides for common development tasks, and code conventions.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Building from Source](#building-from-source)
- [Running Tests](#running-tests)
- [Adding a New Channel](#adding-a-new-channel)
- [Adding a New LLM Provider](#adding-a-new-llm-provider)
- [Code Style and Conventions](#code-style-and-conventions)
- [Commit Message Format](#commit-message-format)
- [Documentation Requirements](#documentation-requirements)
- [Debugging Tips](#debugging-tips)

---

## Prerequisites

### Required Tools

| Tool          | Minimum Version       | Purpose                          | Installation                            |
|---------------|-----------------------|----------------------------------|-----------------------------------------|
| Rust          | 1.85+ (2024 edition)  | Gateway, channels, common crates | `rustup default stable`                |
| Python        | 3.10+                 | Agent layer (LLM, TTS, tools)   | https://python.org                     |
| uv            | 0.5+                  | Python dependency management     | `pip install uv`                       |
| Git           | 2.x                   | Version control                  | https://git-scm.com                    |

### Optional Tools

| Tool          | Version     | Purpose                          | Installation                            |
|---------------|-------------|----------------------------------|-----------------------------------------|
| Node.js       | 20+         | Web SDK development              | https://nodejs.org                     |
| Docker        | 24+         | Containerized deployment         | https://docs.docker.com/get-docker     |
| Docker Compose| 2.x         | Multi-service orchestration      | Included with Docker Desktop           |
| cargo-watch   | Latest      | Auto-rebuild on file change      | `cargo install cargo-watch`            |
| cargo-nextest | Latest      | Faster test runner               | `cargo install cargo-nextest`          |

### Environment Setup

1. **Install Rust toolchain:**

   ```bash
   # Install rustup (if not already installed)
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

   # Or on Windows (WSL recommended for building):
   # Install WSL with Ubuntu, then install Rust inside WSL:
   wsl --install -d Ubuntu
   # Inside WSL:
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   sudo apt install build-essential pkg-config libssl-dev

   # Set stable as default
   rustup default stable

   # Add clippy and rustfmt
   rustup component add clippy rustfmt
   ```

   **Windows Note:** Building on Windows requires VS Build Tools with MSVC and Windows SDK. If those are not installed, use WSL Ubuntu instead. Git for Windows' `link.exe` can shadow MSVC's linker and cause build failures.

2. **Install Python toolchain:**

   ```bash
   # Install Python 3.10+ from your system package manager or python.org

   # Install uv (fast Python package manager)
   pip install uv
   ```

3. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/koclaw.git
   cd koclaw
   ```

4. **Verify the setup:**

   ```bash
   # Rust
   rustc --version    # Should be 1.85+
   cargo --version

   # Python
   python --version   # Should be 3.10+
   uv --version

   # Build verification
   cargo build
   ```

---

## Project Structure

```
koclaw/
|-- Cargo.toml              # Workspace root -- defines members and shared dependencies
|-- Cargo.lock              # Locked dependency versions
|-- config.example.toml     # Annotated example configuration
|-- CLAUDE.md               # Project guidelines for AI-assisted development
|-- README.md               # Project overview and quick start
|
|-- common/                 # koclaw-common crate -- shared types and traits
|   |-- Cargo.toml
|   `-- src/
|       |-- lib.rs          # Module re-exports
|       |-- channel.rs      # Channel trait, ChannelType enum, MessageRouter trait
|       |-- message.rs      # IncomingMessage, OutgoingMessage, Attachment types
|       |-- permission.rs   # PermissionLevel enum with capability checks
|       |-- error.rs        # KoclawError enum (thiserror-based)
|       `-- crypto.rs       # Encryption primitives (X25519, ChaCha20-Poly1305)
|
|-- gateway/                # koclaw-gateway crate -- the main binary
|   |-- Cargo.toml
|   `-- src/
|       |-- main.rs         # Entry point: logging, config, channel startup wiring
|       |-- router.rs       # MessageRouter with permission enforcement + response routing
|       |-- config.rs       # TOML configuration loading with env var secret resolution
|       `-- agent_bridge.rs # WebSocket client with session-based response multiplexing
|
|-- channels/               # koclaw-channels crate -- channel implementations
|   |-- Cargo.toml          # Feature flags per channel (telegram, qq, discord)
|   `-- src/
|       |-- lib.rs          # Conditional module exports
|       |-- telegram.rs     # Telegram Bot API: polling, text/voice/image, allowed users
|       |-- qq.rs           # QQ Bot API: OAuth2 tokens, WebSocket gateway, guild+DM
|       `-- discord.rs      # Discord Bot API implementation [planned]
|
|-- agent/                  # Python Agent (FastAPI + LLM routing)
|   |-- pyproject.toml
|   `-- koclaw_agent/
|       |-- __init__.py
|       |-- bridge.py       # WebSocket bridge server
|       |-- llm_router.py   # LLM provider selection and routing
|       `-- providers/      # Per-provider implementations
|
|-- sdk/                    # @koclaw/web-widget (TypeScript) [planned - Phase 3]
|-- desktop/                # Electron + React desktop app [planned - Phase 3]
|
|-- tests/                  # Integration and end-to-end tests
|
|-- docs/                   # Documentation
|   |-- plans/              # Implementation plans
|   |-- architecture/       # Architecture decision records
|   |-- api/                # API documentation
|   |-- integration/        # Integration guides
|   |-- security/           # Security design documents
|   `-- channels/           # Per-channel setup guides
|
`-- scripts/                # Build, deploy, utility scripts [planned]
```

### Crate Dependency Graph

```
koclaw-gateway (binary)
    |
    +---> koclaw-common (library)
    |
    +---> koclaw-channels (library)
              |
              +---> koclaw-common (library)
```

The `common` crate is the foundation -- it defines all shared types, traits, and error types. The `channels` crate depends on `common` for the trait definitions and message types. The `gateway` crate depends on both.

---

## Building from Source

### Debug Build (Development)

```bash
# Build all workspace members
cargo build

# Build a specific crate
cargo build -p koclaw-gateway
cargo build -p koclaw-common
cargo build -p koclaw-channels
```

### Building via WSL (Windows)

If you don't have VS Build Tools installed, use WSL Ubuntu:

```bash
# Build from Windows terminal using WSL
wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build"

# Run tests via WSL
wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test"
```

### Release Build (Production)

```bash
# Optimized build with LTO, stripped binary
cargo build --release

# The binary is at: target/release/koclaw (or koclaw.exe on Windows)
```

### Build with Specific Channel Features

```bash
# Build with only Telegram support (default)
cargo build

# Build with Telegram and QQ
cargo build --features "koclaw-channels/telegram,koclaw-channels/qq"

# Build with all channels
cargo build --features "koclaw-channels/telegram,koclaw-channels/qq,koclaw-channels/discord"
```

### Docker Build

```bash
# Build all services
docker compose build

# Build and run
docker compose up --build

# Build only the gateway
docker build -t koclaw-gateway .

# Build only the agent
docker build -t koclaw-agent agent/
```

### Auto-Rebuild (Development)

```bash
# Install cargo-watch
cargo install cargo-watch

# Rebuild and run on file changes
cargo watch -x run

# Rebuild and test on file changes
cargo watch -x test
```

---

## Running Tests

### Rust Tests

```bash
# Run all tests across the workspace
cargo test

# Run tests for a specific crate
cargo test -p koclaw-common
cargo test -p koclaw-gateway
cargo test -p koclaw-channels

# Run a specific test by name
cargo test test_permission_levels

# Run tests with output (for debugging)
cargo test -- --nocapture

# Run tests with cargo-nextest (faster, parallel)
cargo nextest run
```

### Python Agent Tests

```bash
cd agent
uv sync
uv run pytest

# With coverage
uv run pytest --cov=koclaw_agent --cov-report=html

# Run a specific test file
uv run pytest tests/test_llm_router.py
```

### Linting

```bash
# Rust linting
cargo clippy -- -W clippy::all

# Rust formatting check
cargo fmt --check

# Python linting
cd agent && uv run ruff check .

# Python type checking
cd agent && uv run mypy koclaw_agent/
```

### Integration Tests

```bash
# Run integration tests (requires running Agent)
cargo test --test integration

# Run end-to-end tests with Docker
docker compose -f docker-compose.test.yml up --abort-on-container-exit
```

---

## Adding a New Channel

This is a step-by-step guide for adding a new messaging platform channel to Koclaw.

### Step 1: Add ChannelType Variant

Edit `common/src/channel.rs`:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ChannelType {
    Telegram,
    QQ,
    Discord,
    WebSocket,
    WebPublic,
    MyNewChannel,    // <-- Add your variant here
}
```

Update the `Display` implementation:

```rust
impl std::fmt::Display for ChannelType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            // ... existing variants ...
            ChannelType::MyNewChannel => write!(f, "my-new-channel"),
        }
    }
}
```

### Step 2: Add Feature Flag

Edit `channels/Cargo.toml`:

```toml
[features]
default = ["telegram"]
telegram = ["dep:reqwest"]
qq = ["dep:reqwest"]
discord = ["dep:reqwest"]
my-new-channel = ["dep:reqwest"]    # <-- Add feature flag
```

Add any channel-specific dependencies as needed.

### Step 3: Create the Implementation File

Create `channels/src/my_new_channel.rs`:

```rust
use std::sync::Arc;
use anyhow::Result;
use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

pub struct MyNewChannel {
    api_key: String,
    // Add channel-specific fields
}

impl MyNewChannel {
    pub fn new(api_key: String) -> Self {
        Self { api_key }
    }
}

impl Channel for MyNewChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            tracing::info!("MyNewChannel starting...");

            // 1. Connect to the platform's API
            // 2. Spawn a background task to listen for events
            // 3. In the event handler:
            //    a. Parse platform-specific message format
            //    b. Convert to IncomingMessage
            //    c. Call router.route(message).await

            Ok(())
        })
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        // Clone fields from &msg BEFORE the async block to avoid lifetime issues
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        Box::pin(async move {
            // 1. Convert OutgoingMessage to platform-specific format
            // 2. Call the platform's send API
            // 3. Handle errors (rate limits, invalid target, etc.)

            Ok(())
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::MyNewChannel
    }

    fn default_permission(&self) -> PermissionLevel {
        // Choose the appropriate default:
        // - Public: for web-facing, anonymous channels
        // - Authenticated: for platforms with user identity
        // - Admin: for local/trusted channels
        PermissionLevel::Authenticated
    }
}
```

### Step 4: Register in Module Tree

Edit `channels/src/lib.rs`:

```rust
#[cfg(feature = "telegram")]
pub mod telegram;

#[cfg(feature = "qq")]
pub mod qq;

#[cfg(feature = "discord")]
pub mod discord;

#[cfg(feature = "my-new-channel")]
pub mod my_new_channel;    // <-- Add module
```

### Step 5: Add Configuration

Add a config section to `config.example.toml`:

```toml
[channels.my_new_channel]
enabled = false
api_key_env = "MY_NEW_CHANNEL_API_KEY"
# Add channel-specific configuration fields
```

### Step 6: Add Documentation

Create `docs/channels/my-new-channel.md` with:
- Prerequisites (account setup, API registration)
- Configuration reference
- Supported features table
- Rate limits
- Platform-specific notes

### Step 7: Add Tests

Create test cases for:
- Message normalization (platform format -> IncomingMessage)
- Response formatting (OutgoingMessage -> platform format)
- Error handling (network failures, rate limits)
- Permission level assignment

### Step 8: Verify

```bash
# Build with the new feature
cargo build --features "koclaw-channels/my-new-channel"

# Run tests
cargo test -p koclaw-channels

# Run clippy
cargo clippy -- -W clippy::all
```

---

## Adding a New LLM Provider

LLM providers are implemented in the Python Agent layer.

### Step 1: Create Provider Module

Create `agent/koclaw_agent/providers/my_provider.py`:

```python
from typing import AsyncIterator
from koclaw_agent.providers.base import (
    BaseProvider,
    AgentRequest,
    AgentResponse,
    StreamChunk,
)


class MyProvider(BaseProvider):
    """Integration with My LLM Service."""

    def __init__(self, api_key: str, default_model: str = "my-model-v1"):
        self.api_key = api_key
        self.default_model = default_model

    async def generate(self, request: AgentRequest) -> AgentResponse:
        """Generate a complete response."""
        # 1. Format the request for your provider's API
        # 2. Call the API
        # 3. Parse the response into AgentResponse
        ...

    async def generate_stream(
        self, request: AgentRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response."""
        # 1. Call the API with streaming enabled
        # 2. Yield StreamChunk objects as they arrive
        ...

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return False  # Set based on provider capabilities

    @property
    def supports_tools(self) -> bool:
        return True  # Set based on provider capabilities

    @property
    def provider_name(self) -> str:
        return "my-provider"
```

### Step 2: Register in Router

Edit `agent/koclaw_agent/llm_router.py`:

```python
from koclaw_agent.providers.my_provider import MyProvider

PROVIDERS = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "ollama": OllamaProvider,
    "my-provider": MyProvider,    # <-- Register here
}
```

### Step 3: Add Environment Variable

```
MY_PROVIDER_API_KEY=your-api-key
```

### Step 4: Add Tests

Create `agent/tests/test_my_provider.py`:

```python
import pytest
from koclaw_agent.providers.my_provider import MyProvider

@pytest.fixture
def provider():
    return MyProvider(api_key="test-key")

def test_provider_name(provider):
    assert provider.provider_name == "my-provider"

def test_supports_streaming(provider):
    assert provider.supports_streaming is True

@pytest.mark.asyncio
async def test_generate(provider):
    # Test with mocked API responses
    ...
```

### Step 5: Update Documentation

Add the provider to the supported providers table in the README and document any provider-specific configuration options.

---

## Code Style and Conventions

### Rust

- **Formatter:** `cargo fmt` (default settings)
- **Linter:** `cargo clippy -- -W clippy::all` (treat all warnings as errors in CI)
- **Error handling:** Use `Result<T, E>` for all fallible operations. Use `thiserror` for library error types, `anyhow` for application-level errors.
- **Naming:**
  - Types: `PascalCase` (e.g., `IncomingMessage`, `ChannelType`)
  - Functions and methods: `snake_case` (e.g., `send_message`, `route`)
  - Constants: `SCREAMING_SNAKE_CASE` (e.g., `MAX_MESSAGE_LENGTH`)
  - Module files: `snake_case` (e.g., `agent_bridge.rs`)
- **Comments:** Only where logic is not self-evident. No comments that restate the code.
- **Imports:** Group by: std -> external crates -> internal crates -> local modules. Separate groups with blank lines.
- **Tests:** Place unit tests in `#[cfg(test)] mod tests` at the bottom of each file. Integration tests go in the `tests/` directory.
- **Unsafe:** Avoid `unsafe` code. If absolutely necessary, document the safety invariants and add `// SAFETY:` comments.

### Python

- **Formatter / Linter:** `ruff` for both formatting and linting
- **Type checking:** `mypy` with strict mode
- **Testing:** `pytest` with `pytest-asyncio` for async tests
- **Naming:**
  - Classes: `PascalCase` (e.g., `ClaudeProvider`, `AgentRequest`)
  - Functions and variables: `snake_case` (e.g., `generate_stream`, `api_key`)
  - Constants: `SCREAMING_SNAKE_CASE` (e.g., `DEFAULT_MODEL`)
- **Type hints:** Required on all function signatures. Use `from __future__ import annotations` for forward references.
- **Docstrings:** Use Google style docstrings for public functions and classes.

### TypeScript (SDK)

- **Formatter:** `prettier`
- **Linter:** `eslint` with strict TypeScript rules
- **Compiler:** Strict TypeScript (`strict: true` in tsconfig)
- **Naming:**
  - Types/Interfaces: `PascalCase` (e.g., `KokoronWidgetProps`)
  - Functions and variables: `camelCase` (e.g., `sendMessage`)
  - Constants: `SCREAMING_SNAKE_CASE` (e.g., `MAX_RETRY_COUNT`)
  - File names: `kebab-case` (e.g., `kokoron-widget.tsx`)

---

## Commit Message Format

Koclaw uses a structured commit message format for clear, machine-parseable history.

### Format

```
type(scope): description

[optional body]

[optional footer]
```

### Types

| Type       | When to Use                                                |
|------------|-------------------------------------------------------------|
| `feat`     | A new feature or capability                                 |
| `fix`      | A bug fix                                                   |
| `refactor` | Code restructuring without behavior change                  |
| `docs`     | Documentation-only changes                                  |
| `test`     | Adding or updating tests                                    |
| `chore`    | Build system, CI, dependency updates, tooling               |
| `security` | Security-related changes (encryption, permissions, etc.)    |

### Scopes

| Scope        | Crate / Component                   |
|--------------|-------------------------------------|
| `gateway`    | koclaw-gateway crate                |
| `agent`      | Python agent layer                  |
| `common`     | koclaw-common crate                 |
| `channel-tg` | Telegram channel implementation     |
| `channel-qq` | QQ channel implementation           |
| `channel-dc` | Discord channel implementation      |
| `sdk`        | Web SDK (@koclaw/web-widget)        |
| `docs`       | Documentation files                 |
| `ci`         | CI/CD configuration                 |

### Examples

```
feat(channel-tg): add voice message support
fix(gateway): handle agent bridge reconnection on timeout
security(common): implement ChaCha20-Poly1305 session encryption
refactor(gateway): extract permission guard into middleware
docs(api): add web widget integration guide
test(common): add property tests for encryption round-trip
chore(ci): add GitHub Actions workflow for Rust CI
```

### Rules

- Subject line: imperative mood ("add", "fix", "implement"), not past tense
- Subject line: max 72 characters
- Body: wrap at 80 characters, explain the "why" not the "what"
- Footer: reference issues or breaking changes (e.g., `Closes #42`, `BREAKING CHANGE: ...`)

---

## Documentation Requirements

All code changes should be accompanied by appropriate documentation updates.

### When to Update Documentation

| Change Type                      | Documentation Required                                  |
|----------------------------------|----------------------------------------------------------|
| New trait or public API          | Update `docs/architecture/trait-design.md`              |
| New channel                      | Create `docs/channels/{channel-name}.md`                |
| New external API endpoint        | Update `docs/api/gateway-api.md`                        |
| New configuration option         | Update `config.example.toml` and README                 |
| Architecture decision            | Add record to `docs/architecture/`                      |
| Security-related change          | Update `docs/security/encryption-design.md`             |
| Breaking change                  | Add entry to `docs/CHANGELOG.md`                        |
| New feature                      | Add entry to `docs/CHANGELOG.md`                        |

### Documentation Style

- Write in English.
- Use plain text and ASCII art. No emojis.
- Use code blocks with language annotations for all code examples.
- Include complete, runnable examples where possible.
- Keep paragraphs focused on a single concept.
- Use tables for structured information.
- Link to related documentation within the project.

---

## Debugging Tips

### Rust Gateway

**Enable detailed logging:**

```bash
RUST_LOG=trace cargo run
```

**Log filtering by module:**

```bash
RUST_LOG=koclaw_gateway=debug,koclaw_channels=trace,koclaw_common=info cargo run
```

**Debug a specific test:**

```bash
RUST_LOG=trace cargo test test_name -- --nocapture
```

### Python Agent

**Enable debug logging:**

```bash
KOCLAW_LOG_LEVEL=debug uv run python -m koclaw_agent
```

**Interactive debugging:**

```bash
uv run python -m debugpy --listen 5678 -m koclaw_agent
# Attach VSCode debugger to port 5678
```

### Network Debugging

**Inspect WebSocket traffic between Gateway and Agent:**

```bash
# Use websocat to connect to the Agent bridge
websocat ws://127.0.0.1:18790

# Send a test message
{"type": "chat", "session_id": "debug", "user_id": "debug:1", "channel": "websocket", "permission": "Admin", "text": "Hello", "attachments": []}
```

**Inspect HTTP traffic:**

```bash
# Test the public chat endpoint
curl -X POST http://127.0.0.1:18789/api/v1/chat/public \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "language": "en"}'
```

### Common Issues

| Issue                                     | Solution                                                |
|-------------------------------------------|---------------------------------------------------------|
| `cargo build` fails with edition error    | Ensure Rust 1.85+ is installed: `rustup update stable` |
| `link.exe` error on Windows               | Git's `link.exe` shadows MSVC's linker. Use WSL Ubuntu to build instead |
| rustc ICE in `check_mod_deathness`        | Known rustc 1.93.1 bug. Use `#![allow(dead_code)]` as workaround |
| Agent bridge connection refused            | Start the Python Agent before the Gateway               |
| Telegram bot not responding               | Verify `TELEGRAM_BOT_TOKEN` is set correctly            |
| Permission denied errors                  | Check the channel's default permission level            |
| Encryption test failures                  | Verify `chacha20poly1305` and `x25519-dalek` versions   |
| Docker build fails on Windows             | Ensure Docker Desktop is running with WSL2 backend      |
| `koclaw_channels::qq` not found           | Add `features = ["telegram", "qq"]` to gateway's Cargo.toml dependency |
