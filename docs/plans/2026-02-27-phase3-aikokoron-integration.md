# Phase 3: AIKokoron Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate AIKokoron's core capabilities into Koclaw — conversation memory, unified persona from YAML config, voice pipeline (GPT-SoVITS TTS + ASR), Live2D expression system, and Desktop/Web WebSocket channel — so that Kokoron works identically across Telegram, Desktop, and Web with shared memory and consistent identity.

**Architecture:** Koclaw's existing Gateway (Rust) → Agent (Python) pipeline is preserved. The Agent is upgraded from a stateless LLM router to a stateful agent with conversation memory, tool calling support, and voice pipeline. A new WebSocket channel is added to the Gateway for Desktop/Web clients. The AIKokoron Electron frontend connects to this WebSocket channel. Persona config moves from hardcoded Rust to a shared YAML file read by both Gateway and Agent.

**Tech Stack:** Rust (tokio, tungstenite), Python (websockets, openai, anthropic), GPT-SoVITS (external API), Faster-Whisper (ASR), YAML (persona config), Electron + React + Live2D (frontend, adapted from AIKokoron)

---

## Phase 3A: Agent Core Upgrade

### Task 1: Unified Persona Config (YAML)

Move persona from hardcoded Rust `Persona::kokoron()` to a shared YAML config file that both Gateway (Rust) and Agent (Python) read. This is the single source of truth for Kokoron's identity.

**Files:**
- Create: `persona.yaml` (project root)
- Modify: `common/src/persona.rs` — add YAML loading
- Modify: `gateway/src/main.rs` — load persona from YAML
- Modify: `agent/koclaw_agent/persona.py` — load from YAML
- Modify: `gateway/Cargo.toml` — add `serde_yaml` dependency
- Modify: `Cargo.toml` — add `serde_yaml` to workspace deps

**Step 1: Create persona.yaml**

```yaml
# Kokoron Persona Configuration
# Single source of truth for AI identity across all channels

name: "Kokoron"
language: "auto"  # auto-detect from user message

base_prompt: |
  You are Kokoron (ココロン), a helpful and friendly AI assistant.
  You are knowledgeable, creative, and always willing to help.
  You maintain a warm and approachable personality while being precise and thorough.
  You can communicate fluently in English, Japanese, and Chinese.
  When expressing emotions, wrap them in brackets like [joy], [surprise], [thinking].

traits:
  - helpful
  - friendly
  - knowledgeable
  - creative

channel_prompts:
  web-public:
    prompt_suffix: |
      You are embedded in a blog. Keep responses concise and relevant
      to the blog's content. Do not execute tools or access private data.
    display_name: "Kokoron (Blog Assistant)"
  telegram:
    prompt_suffix: |
      You are chatting via Telegram. You can use Markdown formatting.
      Keep responses conversational but informative.
  websocket:
    prompt_suffix: |
      You are in a desktop/web companion mode with Live2D avatar.
      Express emotions using brackets: [joy], [anger], [sadness], [surprise], [thinking], [neutral].
      Keep responses natural and conversational. You have voice output capability.

# Live2D model configuration (used by Desktop/Web channel)
live2d:
  model_path: "live2d-models/kokoron/kokoron.model3.json"
  # Emotion-to-expression mapping
  expressions:
    joy: "exp_happy"
    anger: "exp_angry"
    sadness: "exp_sad"
    surprise: "exp_surprised"
    thinking: "exp_thinking"
    neutral: "exp_neutral"
  # Idle motion group
  idle_motion_group: "Idle"

# Voice configuration (used by TTS/ASR pipeline)
voice:
  tts_provider: "gpt_sovits"
  gpt_sovits:
    base_url: "http://127.0.0.1:9880"
    refer_wav_path: "voice-models/kokoron/reference.wav"
    prompt_text: "Hello, I am Kokoron."
    prompt_language: "en"
    text_language: "auto"
  asr_provider: "faster_whisper"
  faster_whisper:
    model_size: "base"
    language: "auto"
```

**Step 2: Add serde_yaml workspace dependency**

In `Cargo.toml` (workspace root), add to `[workspace.dependencies]`:
```toml
serde_yaml = "0.9"
```

In `gateway/Cargo.toml`, add to `[dependencies]`:
```toml
serde_yaml = { workspace = true }
```

**Step 3: Update Rust Persona to load from YAML**

In `common/src/persona.rs`, add a `from_yaml_file()` method:

```rust
impl Persona {
    /// Load persona from a YAML config file.
    pub fn from_yaml(yaml_str: &str) -> Result<Self, String> {
        // Parse the YAML into a serde_json::Value first (common already has serde)
        // Then extract the fields we need
        let value: serde_yaml::Value = serde_yaml::from_str(yaml_str)
            .map_err(|e| format!("Failed to parse persona YAML: {e}"))?;

        let name = value["name"].as_str().unwrap_or("Kokoron").to_string();
        let base_prompt = value["base_prompt"].as_str().unwrap_or("").to_string();
        let language = value["language"].as_str().unwrap_or("auto").to_string();

        let mut traits = Vec::new();
        if let Some(arr) = value["traits"].as_sequence() {
            for item in arr {
                if let Some(s) = item.as_str() {
                    traits.push(s.to_string());
                }
            }
        }

        let mut channel_prompts = Vec::new();
        if let Some(map) = value["channel_prompts"].as_mapping() {
            for (key, val) in map {
                if let Some(channel_name) = key.as_str() {
                    let channel = match channel_name {
                        "telegram" => ChannelType::Telegram,
                        "qq" => ChannelType::QQ,
                        "discord" => ChannelType::Discord,
                        "websocket" => ChannelType::WebSocket,
                        "web-public" => ChannelType::WebPublic,
                        _ => continue,
                    };
                    channel_prompts.push(ChannelPrompt {
                        channel,
                        prompt_suffix: val["prompt_suffix"]
                            .as_str()
                            .unwrap_or("")
                            .to_string(),
                        display_name: val["display_name"]
                            .as_str()
                            .map(String::from),
                    });
                }
            }
        }

        Ok(Self { name, base_prompt, channel_prompts, traits, language })
    }
}
```

Add `serde_yaml` to `common/Cargo.toml`:
```toml
serde_yaml = { workspace = true }
```

**Step 4: Update Gateway main.rs to load persona from YAML**

```rust
// In main(), after loading config:
let persona = {
    let persona_path = std::path::Path::new("persona.yaml");
    if persona_path.exists() {
        let yaml = std::fs::read_to_string(persona_path)
            .expect("Failed to read persona.yaml");
        koclaw_common::persona::Persona::from_yaml(&yaml)
            .expect("Failed to parse persona.yaml")
    } else {
        info!("No persona.yaml found, using default Kokoron persona");
        koclaw_common::persona::Persona::kokoron()
    }
};
let router = Arc::new(router::Router::with_persona(bridge, persona));
```

Update `Router::new` to `Router::with_persona`:
```rust
impl Router {
    pub fn new(bridge: Arc<AgentBridge>) -> Self {
        Self::with_persona(bridge, Persona::kokoron())
    }

    pub fn with_persona(bridge: Arc<AgentBridge>, persona: Persona) -> Self {
        Self {
            bridge,
            channels: RwLock::new(HashMap::new()),
            persona,
        }
    }
}
```

**Step 5: Update Python Persona to load from YAML**

```python
# agent/koclaw_agent/persona.py
import yaml
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class Persona:
    name: str = "Kokoron"
    base_prompt: str = ""
    channel_prompts: dict[str, dict] = field(default_factory=dict)
    language: str = "auto"
    traits: list[str] = field(default_factory=list)
    live2d: dict = field(default_factory=dict)
    voice: dict = field(default_factory=dict)

    def system_prompt(self, channel: str) -> str:
        prompt = self.base_prompt
        if channel in self.channel_prompts:
            suffix = self.channel_prompts[channel].get("prompt_suffix", "")
            if suffix:
                prompt += "\n" + suffix
        return prompt

    @classmethod
    def from_yaml_file(cls, path: str | Path = "persona.yaml") -> "Persona":
        path = Path(path)
        if not path.exists():
            return cls.default()
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            name=data.get("name", "Kokoron"),
            base_prompt=data.get("base_prompt", ""),
            channel_prompts=data.get("channel_prompts", {}),
            language=data.get("language", "auto"),
            traits=data.get("traits", []),
            live2d=data.get("live2d", {}),
            voice=data.get("voice", {}),
        )

    @classmethod
    def default(cls) -> "Persona":
        return cls(
            name="Kokoron",
            base_prompt=(
                "You are Kokoron, a helpful and friendly AI assistant. "
                "You are knowledgeable, creative, and always willing to help."
            ),
        )
```

**Step 6: Add PyYAML dependency**

In `agent/pyproject.toml`, add to dependencies:
```
"pyyaml>=6.0",
```

**Step 7: Build and verify**

```bash
# WSL — Rust build
source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build 2>&1

# Python — sync deps
cd /mnt/d/personal_development/Koclaw/agent && uv sync 2>&1
```

**Step 8: Commit**

```bash
git add persona.yaml common/src/persona.rs common/Cargo.toml gateway/src/main.rs \
  gateway/src/router.rs gateway/Cargo.toml Cargo.toml \
  agent/koclaw_agent/persona.py agent/pyproject.toml
git commit -m "feat(common): unified persona config from YAML

Single persona.yaml is the source of truth for Kokoron's identity.
Both Rust Gateway and Python Agent read from the same file.
Includes Live2D and voice configuration sections for Phase 3B/3C."
```

---

### Task 2: Conversation Memory System

Add persistent conversation memory to the Agent so Kokoron remembers past interactions per session. Adapted from AIKokoron's `ChatHistoryManager` pattern.

**Files:**
- Create: `agent/koclaw_agent/memory/__init__.py`
- Create: `agent/koclaw_agent/memory/chat_history.py`
- Create: `agent/koclaw_agent/memory/base.py`
- Modify: `agent/koclaw_agent/bridge.py` — inject history into LLM calls
- Modify: `agent/koclaw_agent/llm_router.py` — accept message history
- Modify: `agent/koclaw_agent/providers/base.py` — accept message history
- Modify: `agent/koclaw_agent/providers/openai_provider.py` — use history
- Modify: `agent/koclaw_agent/providers/anthropic_provider.py` — use history

**Step 1: Create memory base interface**

```python
# agent/koclaw_agent/memory/base.py
from abc import ABC, abstractmethod

class BaseMemory(ABC):
    """Abstract base for conversation memory backends."""

    @abstractmethod
    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get conversation history for a session. Returns list of {"role": ..., "content": ...}."""
        ...

    @abstractmethod
    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        ...

    @abstractmethod
    async def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        ...

    @abstractmethod
    async def list_sessions(self) -> list[str]:
        """List all known session IDs."""
        ...
```

**Step 2: Create file-based chat history (adapted from AIKokoron)**

```python
# agent/koclaw_agent/memory/chat_history.py
import json
import asyncio
from pathlib import Path
from datetime import datetime

from loguru import logger
from .base import BaseMemory

class FileMemory(BaseMemory):
    """File-based conversation memory. Stores JSON per session."""

    def __init__(self, storage_dir: str = "chat_history"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        logger.info(f"FileMemory initialized: {self.storage_dir}")

    def _session_path(self, session_id: str) -> Path:
        safe_name = session_id.replace(":", "_").replace("/", "_")
        return self.storage_dir / f"{safe_name}.json"

    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        async with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            return messages[-limit:]

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        path = self._session_path(session_id)
        async with self._lock:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {"session_id": session_id, "created": datetime.now().isoformat(), "messages": []}
            data["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            })
            data["updated"] = datetime.now().isoformat()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def clear_history(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if path.exists():
            async with self._lock:
                path.unlink()

    async def list_sessions(self) -> list[str]:
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(data.get("session_id", path.stem))
        return sessions
```

```python
# agent/koclaw_agent/memory/__init__.py
from .base import BaseMemory
from .chat_history import FileMemory

__all__ = ["BaseMemory", "FileMemory"]
```

**Step 3: Update BaseProvider to accept message history**

```python
# agent/koclaw_agent/providers/base.py
from abc import ABC, abstractmethod
from typing import AsyncGenerator

class BaseProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response. Yield text chunks."""
        ...
```

**Step 4: Update OpenAI provider to use history**

```python
# In openai_provider.py generate():
async def generate(
    self,
    text: str,
    session_id: str,
    attachments: list,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    messages = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
    ]
    # Inject conversation history
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": text})

    stream = await self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        max_tokens=4096,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

**Step 5: Update Anthropic provider to use history**

```python
# In anthropic_provider.py generate():
async def generate(
    self,
    text: str,
    session_id: str,
    attachments: list,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    messages = []
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": text})

    async with self.client.messages.stream(
        model=self.model,
        max_tokens=4096,
        system=system_prompt or DEFAULT_SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        async for chunk in stream.text_stream:
            yield chunk
```

**Step 6: Update LLMRouter to pass history**

```python
# In llm_router.py:
async def generate(
    self,
    text: str,
    session_id: str,
    permission: str = "Authenticated",
    attachments: list = None,
    provider: str = None,
    system_prompt: str = None,
    history: list[dict] = None,
) -> AsyncGenerator[str, None]:
    provider_name = provider or self.default_provider
    if provider_name in self._providers:
        provider_instance = self._providers[provider_name]
        async for chunk in provider_instance.generate(
            text, session_id, attachments or [],
            system_prompt=system_prompt,
            history=history,
        ):
            yield chunk
    else:
        yield f"[Echo] {text}"
        yield "\n\n(No LLM provider configured.)"
```

**Step 7: Update AgentBridge to manage memory**

```python
# In bridge.py:
from .memory import FileMemory
from .persona import Persona

class AgentBridge:
    def __init__(self, host="127.0.0.1", port=18790):
        self.host = host
        self.port = port
        self.llm_router = LLMRouter()
        self.memory = FileMemory()
        self.persona = Persona.from_yaml_file()

    async def _handle_chat(self, websocket, message: dict):
        session_id = message.get("session_id", "")
        text = message.get("text", "")
        channel = message.get("channel", "telegram")
        system_prompt = message.get("system_prompt") or self.persona.system_prompt(channel)

        # Get conversation history
        history = await self.memory.get_history(session_id)

        # Save user message
        await self.memory.add_message(session_id, "user", text)

        # Stream LLM response
        full_response = ""
        async for chunk in self.llm_router.generate(
            text=text,
            session_id=session_id,
            permission=message.get("permission", "Public"),
            attachments=message.get("attachments", []),
            system_prompt=system_prompt,
            history=history,
        ):
            full_response += chunk
            await websocket.send(json.dumps({
                "type": "text_chunk",
                "session_id": session_id,
                "content": chunk,
            }))

        # Save assistant response
        await self.memory.add_message(session_id, "assistant", full_response)

        # Signal completion
        await websocket.send(json.dumps({
            "type": "done",
            "session_id": session_id,
        }))
```

**Step 8: Build, test, and commit**

```bash
# Run agent to verify no import errors
cd /mnt/d/personal_development/Koclaw/agent && uv sync && uv run python -c "from koclaw_agent.memory import FileMemory; print('OK')"

# Build Rust
source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build 2>&1

git add agent/koclaw_agent/memory/ agent/koclaw_agent/bridge.py \
  agent/koclaw_agent/llm_router.py agent/koclaw_agent/providers/
git commit -m "feat(agent): add conversation memory system

File-based per-session memory. History injected into LLM context.
Both OpenAI and Anthropic providers support multi-turn conversation.
Agent also loads persona from YAML for system prompt resolution."
```

---

### Task 3: Expression Extraction System

Extract emotion expressions like `[joy]`, `[anger]` from LLM output text. These are used by the Live2D frontend to trigger avatar animations. Adapted from AIKokoron's live2d_model.py expression system.

**Files:**
- Create: `agent/koclaw_agent/expression.py`
- Modify: `agent/koclaw_agent/bridge.py` — extract expressions from response, send as metadata

**Step 1: Create expression extractor**

```python
# agent/koclaw_agent/expression.py
"""Extract emotion expressions from LLM output for Live2D animation."""

import re
from dataclasses import dataclass

EXPRESSION_PATTERN = re.compile(r"\[(\w+)\]")

# Known expressions (matches persona.yaml live2d.expressions)
KNOWN_EXPRESSIONS = {"joy", "anger", "sadness", "surprise", "thinking", "neutral"}

@dataclass
class ExpressionResult:
    """Result of expression extraction."""
    clean_text: str  # Text with expression tags removed
    expressions: list[str]  # Extracted expression names in order

def extract_expressions(text: str) -> ExpressionResult:
    """Extract [emotion] tags from text and return cleaned text + expressions list."""
    expressions = []
    for match in EXPRESSION_PATTERN.finditer(text):
        expr = match.group(1).lower()
        if expr in KNOWN_EXPRESSIONS:
            expressions.append(expr)

    clean_text = EXPRESSION_PATTERN.sub("", text).strip()
    # Clean up double spaces left by removal
    clean_text = re.sub(r"  +", " ", clean_text)

    return ExpressionResult(clean_text=clean_text, expressions=expressions)
```

**Step 2: Update bridge protocol to include expression data**

In `bridge.py`, after collecting the full response, extract expressions and include them in the `done` message:

```python
from .expression import extract_expressions

# In _handle_chat(), after collecting full_response:
expr_result = extract_expressions(full_response)

await websocket.send(json.dumps({
    "type": "done",
    "session_id": session_id,
    "expressions": expr_result.expressions,
}))
```

**Step 3: Commit**

```bash
git add agent/koclaw_agent/expression.py agent/koclaw_agent/bridge.py
git commit -m "feat(agent): expression extraction for Live2D animation

Extracts [joy], [anger], etc. from LLM output text.
Expressions sent in 'done' message for frontend Live2D integration."
```

---

## Phase 3B: Voice Pipeline

### Task 4: TTS Integration (GPT-SoVITS)

Add text-to-speech capability using GPT-SoVITS. The TTS server runs as an external process; Koclaw calls its HTTP API and streams audio back. Adapted from AIKokoron's `gpt_sovits_tts.py`.

**Files:**
- Create: `agent/koclaw_agent/voice/__init__.py`
- Create: `agent/koclaw_agent/voice/base_tts.py`
- Create: `agent/koclaw_agent/voice/gpt_sovits.py`
- Modify: `agent/koclaw_agent/bridge.py` — add TTS to response pipeline
- Modify: `agent/pyproject.toml` — add `httpx` dependency

**Step 1: Create TTS base interface**

```python
# agent/koclaw_agent/voice/base_tts.py
from abc import ABC, abstractmethod

class BaseTTS(ABC):
    @abstractmethod
    async def synthesize(self, text: str, language: str = "auto") -> bytes:
        """Convert text to audio bytes (WAV format)."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if TTS backend is accessible."""
        ...
```

**Step 2: Create GPT-SoVITS provider**

```python
# agent/koclaw_agent/voice/gpt_sovits.py
"""GPT-SoVITS TTS provider.

Calls the GPT-SoVITS API server (typically at http://127.0.0.1:9880).
Reference: AIKokoron's gpt_sovits_tts.py
"""

import httpx
from loguru import logger
from .base_tts import BaseTTS

class GPTSoVITSTTS(BaseTTS):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9880",
        refer_wav_path: str = "",
        prompt_text: str = "",
        prompt_language: str = "en",
        text_language: str = "auto",
    ):
        self.base_url = base_url.rstrip("/")
        self.refer_wav_path = refer_wav_path
        self.prompt_text = prompt_text
        self.prompt_language = prompt_language
        self.text_language = text_language
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"GPT-SoVITS TTS initialized: {self.base_url}")

    async def synthesize(self, text: str, language: str = "auto") -> bytes:
        params = {
            "text": text,
            "text_language": language if language != "auto" else self.text_language,
        }
        if self.refer_wav_path:
            params["refer_wav_path"] = self.refer_wav_path
            params["prompt_text"] = self.prompt_text
            params["prompt_language"] = self.prompt_language

        response = await self.client.get(f"{self.base_url}/tts", params=params)
        response.raise_for_status()
        return response.content

    def is_available(self) -> bool:
        try:
            import httpx as _
            resp = httpx.get(f"{self.base_url}/", timeout=3.0)
            return resp.status_code < 500
        except Exception:
            return False
```

```python
# agent/koclaw_agent/voice/__init__.py
from .base_tts import BaseTTS
from .gpt_sovits import GPTSoVITSTTS

__all__ = ["BaseTTS", "GPTSoVITSTTS"]
```

**Step 3: Add httpx dependency**

In `agent/pyproject.toml`:
```
"httpx>=0.27",
```

**Step 4: Integrate TTS into bridge**

Add optional TTS synthesis to the bridge. When a WebSocket client requests audio, the bridge synthesizes the response text into audio and sends it as a binary audio chunk.

```python
# In bridge.py, add TTS initialization:
from .voice import GPTSoVITSTTS

class AgentBridge:
    def __init__(self, host="127.0.0.1", port=18790):
        # ... existing init ...
        self.tts = self._init_tts()

    def _init_tts(self):
        voice_config = self.persona.voice
        if voice_config.get("tts_provider") == "gpt_sovits":
            sovits_cfg = voice_config.get("gpt_sovits", {})
            return GPTSoVITSTTS(
                base_url=sovits_cfg.get("base_url", "http://127.0.0.1:9880"),
                refer_wav_path=sovits_cfg.get("refer_wav_path", ""),
                prompt_text=sovits_cfg.get("prompt_text", ""),
                prompt_language=sovits_cfg.get("prompt_language", "en"),
                text_language=sovits_cfg.get("text_language", "auto"),
            )
        return None
```

In `_handle_chat()`, after the `done` message, if TTS is available and the request asks for audio:

```python
# In _handle_chat():
want_audio = message.get("audio_response", False)
if want_audio and self.tts and full_response:
    try:
        # Strip expression tags before synthesis
        clean_text = expr_result.clean_text
        audio_data = await self.tts.synthesize(clean_text)
        # Send audio as base64 in a separate message
        import base64
        await websocket.send(json.dumps({
            "type": "audio",
            "session_id": session_id,
            "format": "wav",
            "data": base64.b64encode(audio_data).decode("ascii"),
        }))
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
```

**Step 5: Commit**

```bash
git add agent/koclaw_agent/voice/ agent/koclaw_agent/bridge.py agent/pyproject.toml
git commit -m "feat(agent): GPT-SoVITS TTS integration

Voice synthesis via external GPT-SoVITS API server.
Audio sent as base64 WAV in WebSocket 'audio' message.
Config loaded from persona.yaml voice section."
```

---

### Task 5: ASR Integration (Speech-to-Text)

Add speech recognition so Desktop/Web clients can send audio and get it transcribed. Adapted from AIKokoron's ASR system.

**Files:**
- Create: `agent/koclaw_agent/voice/base_asr.py`
- Create: `agent/koclaw_agent/voice/faster_whisper_asr.py`
- Modify: `agent/koclaw_agent/voice/__init__.py`
- Modify: `agent/koclaw_agent/bridge.py` — handle audio input messages
- Modify: `agent/pyproject.toml` — add faster-whisper to optional deps

**Step 1: Create ASR base interface**

```python
# agent/koclaw_agent/voice/base_asr.py
from abc import ABC, abstractmethod

class BaseASR(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: bytes, language: str = "auto") -> str:
        """Transcribe audio bytes to text."""
        ...
```

**Step 2: Create Faster-Whisper ASR**

```python
# agent/koclaw_agent/voice/faster_whisper_asr.py
"""Faster-Whisper ASR provider.

Uses faster-whisper for local speech recognition.
Reference: AIKokoron's faster_whisper_asr.py
"""

import asyncio
import io
import wave
from loguru import logger
from .base_asr import BaseASR

class FasterWhisperASR(BaseASR):
    def __init__(self, model_size: str = "base", language: str = "auto"):
        self.model_size = model_size
        self.language = language if language != "auto" else None
        self._model = None
        logger.info(f"FasterWhisper ASR initialized: model={model_size}, lang={language}")

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, compute_type="int8")
        return self._model

    async def transcribe(self, audio_data: bytes, language: str = "auto") -> str:
        lang = language if language != "auto" else self.language
        model = self._get_model()

        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None, self._transcribe_sync, model, audio_data, lang
        )
        return text

    def _transcribe_sync(self, model, audio_data: bytes, language: str | None) -> str:
        # Write audio to a temporary buffer
        audio_file = io.BytesIO(audio_data)
        segments, _info = model.transcribe(
            audio_file,
            language=language,
            beam_size=5,
        )
        return " ".join(seg.text.strip() for seg in segments)
```

**Step 3: Update bridge to handle audio input**

```python
# In bridge.py _handle_connection(), add new message type:
elif msg_type == "audio_input":
    await self._handle_audio_input(websocket, message)

# New method:
async def _handle_audio_input(self, websocket, message: dict):
    """Transcribe audio input and process as chat."""
    session_id = message.get("session_id", "")
    import base64
    audio_data = base64.b64decode(message.get("audio_data", ""))

    if not self.asr:
        await websocket.send(json.dumps({
            "type": "error",
            "session_id": session_id,
            "content": "ASR not configured",
        }))
        return

    # Transcribe
    text = await self.asr.transcribe(audio_data)
    logger.info(f"ASR transcription: {text[:100]}")

    # Send transcription to client
    await websocket.send(json.dumps({
        "type": "transcription",
        "session_id": session_id,
        "content": text,
    }))

    # Process as regular chat
    chat_msg = {**message, "type": "chat", "text": text, "audio_response": True}
    await self._handle_chat(websocket, chat_msg)
```

**Step 4: Add optional dependency**

In `agent/pyproject.toml`:
```toml
[project.optional-dependencies]
voice = [
    "faster-whisper>=1.0",
]
```

**Step 5: Commit**

```bash
git add agent/koclaw_agent/voice/ agent/koclaw_agent/bridge.py agent/pyproject.toml
git commit -m "feat(agent): Faster-Whisper ASR integration

Speech-to-text via faster-whisper (local model).
Audio input messages transcribed and processed as chat.
Transcription sent back to client before LLM response."
```

---

## Phase 3C: Desktop/Web Channel

### Task 6: WebSocket Channel in Gateway

Add a WebSocket server channel to the Rust Gateway that Desktop/Web clients connect to. This replaces AIKokoron's standalone WebSocket handler with one integrated into Koclaw's routing system.

**Files:**
- Create: `channels/src/websocket_channel.rs`
- Modify: `channels/src/lib.rs` — add websocket module
- Modify: `channels/Cargo.toml` — add feature flag + deps
- Modify: `gateway/src/config.rs` — add WebSocket config
- Modify: `gateway/src/main.rs` — start WebSocket channel
- Modify: `gateway/Cargo.toml` — enable websocket feature
- Modify: `config.toml` — add websocket section

**Step 1: Add WebSocket channel feature flag**

In `channels/Cargo.toml`, add:
```toml
[features]
telegram = ["dep:reqwest"]
qq = ["dep:reqwest"]
discord = ["dep:reqwest"]
websocket = ["dep:tokio-tungstenite", "dep:futures-util"]

[dependencies]
# ... existing deps ...
tokio-tungstenite = { workspace = true, optional = true }
futures-util = { version = "0.3", optional = true }
```

**Step 2: Create WebSocket channel**

```rust
// channels/src/websocket_channel.rs
//! WebSocket channel for Desktop/Web Live2D clients.
//!
//! Protocol (compatible with AIKokoron frontend):
//!   Client -> Server: {"type": "text-input", "text": "...", "session_id": "..."}
//!   Client -> Server: {"type": "mic-audio-data", "audio": "base64...", "session_id": "..."}
//!   Client -> Server: {"type": "interrupt-signal", "session_id": "..."}
//!   Server -> Client: {"type": "full-text", "text": "...", "expressions": [...]}
//!   Server -> Client: {"type": "audio", "audio": "base64...", "format": "wav"}
//!   Server -> Client: {"type": "control", "action": "..."}

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::TcpListener;
use tokio::sync::{mpsc, RwLock};
use tokio_tungstenite::tungstenite::Message;
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{Attachment, IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

/// WebSocket channel for Desktop/Web clients.
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
            let ws_stream = tokio_tungstenite::accept_async(stream).await?;
            info!(%peer, "WebSocket client connected");

            let session_id = format!("ws:{}", peer);
            let router = router.clone();
            let clients = self.clients.clone();

            tokio::spawn(async move {
                if let Err(e) = Self::handle_client(
                    ws_stream, peer, session_id, router, clients,
                ).await {
                    error!(%peer, error = %e, "WebSocket client error");
                }
            });
        }
    }

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

        // Spawn sender task
        let send_session = session_id.clone();
        let send_task = tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                if ws_sender.send(Message::Text(msg.into())).await.is_err() {
                    break;
                }
            }
            debug!(session = %send_session, "WebSocket sender task ended");
        });

        // Receive loop
        while let Some(msg) = ws_receiver.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    let text_str: &str = &text;
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(text_str) {
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
                                        .unwrap()
                                        .as_secs(),
                                };
                                if let Err(e) = router.route(incoming).await {
                                    error!(error = %e, "Failed to route WebSocket message");
                                }
                            }
                            "ping" => {
                                let clients = clients.read().await;
                                if let Some(tx) = clients.get(&session_id) {
                                    let _ = tx.send(r#"{"type":"pong"}"#.to_string()).await;
                                }
                            }
                            _ => {
                                debug!(msg_type, "Unknown WebSocket message type");
                            }
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
    use std::time::SystemTime;
    let t = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    format!("ws-{t:x}")
}
```

**Step 3: Register in channels/src/lib.rs**

```rust
#[cfg(feature = "websocket")]
pub mod websocket_channel;
```

**Step 4: Add WebSocket config**

In `gateway/src/config.rs`:
```rust
#[derive(Debug, Deserialize)]
pub struct ChannelsConfig {
    pub telegram: Option<TelegramConfig>,
    pub qq: Option<QQConfig>,
    pub discord: Option<DiscordConfig>,
    pub websocket: Option<WebSocketConfig>,
}

#[derive(Debug, Deserialize)]
pub struct WebSocketConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_ws_host")]
    pub host: String,
    #[serde(default = "default_ws_port")]
    pub port: u16,
}

fn default_ws_host() -> String { "127.0.0.1".to_string() }
fn default_ws_port() -> u16 { 18791 }
```

**Step 5: Start WebSocket channel in main.rs**

```rust
// In main.rs, after Discord block:
if let Some(ref ws) = config.channels.websocket {
    if ws.enabled {
        info!(host = %ws.host, port = %ws.port, "Starting WebSocket channel");
        let channel = Arc::new(
            koclaw_channels::websocket_channel::WebSocketChannel::new(
                ws.host.clone(), ws.port,
            )
        );
        router.register_channel(channel.clone()).await;

        let channel_router = router.clone();
        tokio::spawn(async move {
            if let Err(e) = channel.start(channel_router).await {
                error!(error = %e, "WebSocket channel stopped");
            }
        });
    }
}
```

**Step 6: Enable in Cargo.toml**

In `gateway/Cargo.toml`:
```toml
koclaw-channels = { workspace = true, features = ["telegram", "qq", "discord", "websocket"] }
```

**Step 7: Add config section**

In `config.toml`:
```toml
[channels.websocket]
enabled = true
host = "127.0.0.1"
port = 18791
```

**Step 8: Build and commit**

```bash
source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build 2>&1

git add channels/src/websocket_channel.rs channels/src/lib.rs channels/Cargo.toml \
  gateway/src/config.rs gateway/src/main.rs gateway/Cargo.toml config.toml
git commit -m "feat(channel-ws): WebSocket channel for Desktop/Web clients

New WebSocket server channel on port 18791.
Protocol compatible with AIKokoron frontend (text-input, full-text).
Integrated into Gateway routing system with Authenticated permission."
```

---

### Task 7: Extended Bridge Protocol (Audio + Expressions)

Extend the Gateway ↔ Agent bridge protocol to support audio data and expression metadata. This allows the full voice + Live2D pipeline to work end-to-end.

**Files:**
- Modify: `gateway/src/agent_bridge.rs` — add audio and expression fields
- Modify: `gateway/src/router.rs` — forward audio/expressions to WebSocket clients
- Modify: `common/src/message.rs` — add audio attachment support

**Step 1: Extend AgentResponseChunk**

```rust
// In agent_bridge.rs:
#[derive(Debug, Clone, Deserialize)]
pub struct AgentResponseChunk {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub session_id: Option<String>,
    pub content: Option<String>,
    /// Base64-encoded audio data (WAV)
    pub audio_data: Option<String>,
    pub audio_format: Option<String>,
    /// Expression tags extracted from response
    pub expressions: Option<Vec<String>>,
}
```

**Step 2: Update Router to forward rich responses**

```rust
// In router.rs, update the chunk handling in route():
let mut expressions: Vec<String> = Vec::new();
let mut audio_data: Option<String> = None;

while let Some(chunk) = rx.recv().await {
    match chunk.msg_type.as_str() {
        "text_chunk" => { /* same as before */ }
        "audio" => {
            audio_data = chunk.audio_data;
        }
        "done" => {
            if let Some(exprs) = chunk.expressions {
                expressions = exprs;
            }
            break;
        }
        "error" => { /* same as before */ }
        _ => {}
    }
}

// When sending response, include expressions for WebSocket channel
if message.channel == ChannelType::WebSocket {
    // Send rich response with expressions + audio
    let channels = self.channels.read().await;
    if let Some(channel) = channels.get(&ChannelType::WebSocket) {
        let mut msg = OutgoingMessage {
            channel: ChannelType::WebSocket,
            target_id: target_id.to_string(),
            text: Some(full_response.clone()),
            attachments: Vec::new(),
            reply_to: None,
        };
        // Audio attachment
        if let Some(audio) = audio_data {
            msg.attachments.push(Attachment {
                attachment_type: AttachmentType::Voice,
                url: audio, // base64 data URL
                mime_type: Some("audio/wav".to_string()),
                file_name: None,
                size: None,
            });
        }
        channel.send_message(&msg).await?;
    }
}
```

**Step 3: Commit**

```bash
git add gateway/src/agent_bridge.rs gateway/src/router.rs
git commit -m "feat(gateway): extended bridge protocol for audio + expressions

AgentResponseChunk now carries audio_data and expressions.
Router forwards audio/expression data to WebSocket clients.
Enables full voice + Live2D pipeline through Gateway."
```

---

### Task 8: Static File Server for Live2D Models

Add a simple static file server to the Gateway so Desktop/Web clients can download Live2D model files. This avoids requiring clients to have model files locally.

**Files:**
- Create: `gateway/src/static_server.rs`
- Modify: `gateway/src/main.rs` — start static file server
- Modify: `gateway/src/config.rs` — add static_files config
- Modify: `gateway/Cargo.toml` — add warp or axum dependency

**Step 1: Add HTTP server dependency**

In `Cargo.toml` (workspace):
```toml
axum = "0.8"
tower-http = { version = "0.6", features = ["fs", "cors"] }
```

In `gateway/Cargo.toml`:
```toml
axum = { workspace = true }
tower-http = { workspace = true }
```

**Step 2: Create static file server**

```rust
// gateway/src/static_server.rs
//! Lightweight HTTP server for Live2D models, audio assets, and persona config.

use std::net::SocketAddr;
use std::path::PathBuf;

use anyhow::Result;
use axum::Router;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;
use tracing::info;

/// Start an HTTP server that serves static files from a directory.
pub async fn start_static_server(host: &str, port: u16, root: PathBuf) -> Result<()> {
    let app = Router::new()
        .nest_service("/", ServeDir::new(&root))
        .layer(CorsLayer::permissive());

    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    info!(%addr, root = %root.display(), "Static file server starting");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
```

**Step 3: Add config**

In `gateway/src/config.rs`:
```rust
#[derive(Debug, Deserialize)]
pub struct GatewayConfig {
    // ... existing fields ...
    #[serde(default)]
    pub static_files: Option<StaticFilesConfig>,
}

#[derive(Debug, Deserialize)]
pub struct StaticFilesConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_static_host")]
    pub host: String,
    #[serde(default = "default_static_port")]
    pub port: u16,
    #[serde(default = "default_static_root")]
    pub root: String,
}

fn default_static_host() -> String { "127.0.0.1".to_string() }
fn default_static_port() -> u16 { 18792 }
fn default_static_root() -> String { "./assets".to_string() }
```

**Step 4: Start in main.rs**

```rust
// In main.rs, after channel startup:
if let Some(ref sf) = config.gateway.static_files {
    if sf.enabled {
        let root = std::path::PathBuf::from(&sf.root);
        let host = sf.host.clone();
        let port = sf.port;
        tokio::spawn(async move {
            if let Err(e) = koclaw_gateway::static_server::start_static_server(
                &host, port, root,
            ).await {
                error!(error = %e, "Static file server stopped");
            }
        });
    }
}
```

**Step 5: Add config section**

In `config.toml`:
```toml
[gateway.static_files]
enabled = true
host = "127.0.0.1"
port = 18792
root = "./assets"
```

**Step 6: Create asset directory structure**

```bash
mkdir -p assets/live2d-models
mkdir -p assets/voice-models
```

**Step 7: Commit**

```bash
git add gateway/src/static_server.rs gateway/src/main.rs gateway/src/config.rs \
  gateway/src/lib.rs gateway/Cargo.toml Cargo.toml config.toml
git commit -m "feat(gateway): static file server for Live2D models and assets

HTTP server on port 18792 serves live2d-models/ and voice-models/.
Frontend downloads model files on first load (cached by browser).
CORS enabled for cross-origin access from Desktop/Web clients."
```

---

### Task 9: Frontend Adapter (AIKokoron → Koclaw)

Create a configuration bridge so the existing AIKokoron Electron+React frontend can connect to Koclaw's WebSocket channel instead of AIKokoron's standalone server. This involves creating a minimal config file that tells the frontend where to connect.

**Files:**
- Create: `desktop/README.md` — setup instructions
- Create: `desktop/koclaw-config.json` — frontend connection config

**NOTE:** The AIKokoron frontend at `D:\personal_development\AI_assistant\AIKokoron\frontend-source\` is NOT copied or forked. Instead, we configure it to point at Koclaw's WebSocket endpoint. The actual frontend adaptation (if needed) will be a separate task.

**Step 1: Create desktop config**

```json
{
  "$schema": "Koclaw Desktop Connection Config",
  "websocket_url": "ws://127.0.0.1:18791",
  "static_assets_url": "http://127.0.0.1:18792",
  "persona_name": "Kokoron"
}
```

**Step 2: Create README with setup instructions**

Document how to:
1. Clone/link the AIKokoron frontend
2. Modify its WebSocket URL to point at Koclaw
3. Build and run the Electron app

**Step 3: Commit**

```bash
git add desktop/
git commit -m "docs(desktop): frontend adapter config for AIKokoron integration

Config file for connecting AIKokoron's Electron frontend to Koclaw.
Points WebSocket at Gateway port 18791, assets at port 18792."
```

---

### Task 10: Integration Test — Full Pipeline

Create an integration test that verifies the full Telegram + WebSocket pipeline works end-to-end with memory, persona, and expression extraction.

**Files:**
- Create: `agent/tests/test_memory.py`
- Create: `agent/tests/test_expression.py`
- Create: `agent/tests/test_bridge_integration.py`
- Modify: `tests/` (Rust integration tests if needed)

**Step 1: Test expression extraction**

```python
# agent/tests/test_expression.py
from koclaw_agent.expression import extract_expressions

def test_extract_single_expression():
    result = extract_expressions("I'm so happy! [joy]")
    assert result.expressions == ["joy"]
    assert "[joy]" not in result.clean_text

def test_extract_multiple_expressions():
    result = extract_expressions("[thinking] Let me consider... [surprise] Oh!")
    assert result.expressions == ["thinking", "surprise"]

def test_no_expressions():
    result = extract_expressions("Hello, how are you?")
    assert result.expressions == []
    assert result.clean_text == "Hello, how are you?"

def test_unknown_expression_ignored():
    result = extract_expressions("[happy] Hello [unknown_emotion]")
    assert "unknown_emotion" not in result.expressions
```

**Step 2: Test memory system**

```python
# agent/tests/test_memory.py
import pytest
from koclaw_agent.memory import FileMemory

@pytest.fixture
def memory(tmp_path):
    return FileMemory(storage_dir=str(tmp_path / "test_history"))

@pytest.mark.asyncio
async def test_add_and_get(memory):
    await memory.add_message("sess1", "user", "Hello")
    await memory.add_message("sess1", "assistant", "Hi!")
    history = await memory.get_history("sess1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "Hi!"

@pytest.mark.asyncio
async def test_separate_sessions(memory):
    await memory.add_message("sess1", "user", "A")
    await memory.add_message("sess2", "user", "B")
    h1 = await memory.get_history("sess1")
    h2 = await memory.get_history("sess2")
    assert len(h1) == 1
    assert len(h2) == 1

@pytest.mark.asyncio
async def test_history_limit(memory):
    for i in range(100):
        await memory.add_message("sess1", "user", f"msg{i}")
    history = await memory.get_history("sess1", limit=10)
    assert len(history) == 10
    assert history[0]["content"] == "msg90"

@pytest.mark.asyncio
async def test_clear_history(memory):
    await memory.add_message("sess1", "user", "Hello")
    await memory.clear_history("sess1")
    assert await memory.get_history("sess1") == []
```

**Step 3: Run tests**

```bash
cd /mnt/d/personal_development/Koclaw/agent && uv run pytest tests/ -v 2>&1
```

**Step 4: Commit**

```bash
git add agent/tests/
git commit -m "test(agent): memory and expression extraction tests

7 tests covering FileMemory (add, get, limit, clear, sessions)
and expression extraction (single, multiple, unknown, empty)."
```

---

## Summary

| Task | Description | Key Files | Estimated Effort |
|------|-------------|-----------|-----------------|
| 1 | Unified Persona YAML | `persona.yaml`, `persona.rs`, `persona.py` | 30 min |
| 2 | Conversation Memory | `memory/`, `bridge.py`, providers | 45 min |
| 3 | Expression Extraction | `expression.py`, `bridge.py` | 15 min |
| 4 | TTS (GPT-SoVITS) | `voice/gpt_sovits.py`, `bridge.py` | 30 min |
| 5 | ASR (Faster-Whisper) | `voice/faster_whisper_asr.py`, `bridge.py` | 30 min |
| 6 | WebSocket Channel | `websocket_channel.rs`, `config.rs`, `main.rs` | 45 min |
| 7 | Extended Bridge Protocol | `agent_bridge.rs`, `router.rs` | 20 min |
| 8 | Static File Server | `static_server.rs`, `main.rs` | 20 min |
| 9 | Frontend Adapter | `desktop/` config + README | 10 min |
| 10 | Integration Tests | `tests/` | 20 min |

**Total estimated: ~4.5 hours**

## Execution Order

Tasks 1-3 (Agent Core) must be done first, in order.
Tasks 4-5 (Voice) can follow after Task 2.
Tasks 6-8 (Desktop/Web) can be done in parallel with Tasks 4-5.
Task 9 depends on Tasks 6+8.
Task 10 depends on all previous tasks.

Recommended sequence: 1 → 2 → 3 → (4,5,6 in parallel) → 7 → 8 → 9 → 10
