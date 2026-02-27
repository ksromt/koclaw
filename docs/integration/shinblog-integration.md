# shinBlog Integration Guide

## Overview

shinBlog integrates with Koclaw via:
1. **Chat API** — REST/SSE endpoint for Kokoron conversations (available now)
2. **WebSocket API** — Real-time bidirectional channel (available now, port 18791)
3. **Web Widget** (future) — `@koclaw/web-widget` npm package with Live2D + Chat UI

## Architecture

```
shinBlog (Next.js)                  Koclaw
┌──────────────────┐    HTTP/SSE    ┌───────────────────────────────┐
│ /api/kokoron-chat├───────────────►│ Gateway :18789                │
│    (proxy route)  │               │   POST /api/v1/chat/public    │
└──────────────────┘               │                               │
                                    │   ┌─── Router ───┐            │
┌──────────────────┐    WebSocket   │   │  Permission  │    WS      │
│ Chat Component   ├───────────────►│   │  Enforcement │───────────►│ Agent :18790
│  (optional)       │  ws://:18791  │   └──────────────┘            │   ├── LLM Router
└──────────────────┘               │                               │   ├── Memory
                                    │   Static Files :18792         │   ├── Expression
┌──────────────────┐    HTTP        │   └── Live2D models          │   └── Voice (TTS/ASR)
│ Live2D Component ├───────────────►│   └── Voice assets           │
│  (optional)       │               └───────────────────────────────┘
└──────────────────┘
```

## Option 1: REST Chat API (Recommended for Blog)

### Endpoint
```
POST /api/v1/chat/public
Content-Type: application/json
```

### Request
```json
{
  "message": "Tell me about this blog",
  "session_id": "optional-session-id-for-continuity",
  "language": "en"
}
```

### Response (Server-Sent Events)
```
data: {"type": "text", "content": "Hello! "}
data: {"type": "text", "content": "I'm Kokoron. "}
data: {"type": "done", "session_id": "abc123"}
```

### Permission Level
This endpoint operates at `Public` permission level:
- Chat responses only (no tool execution)
- No access to private user data
- Rate limited (configurable, default: 10 messages/min per IP)
- Can answer questions about blog content (via RAG, if configured)

### Next.js API Route (`app/api/kokoron-chat/route.ts`)
```typescript
// Proxy to Koclaw Gateway — avoids exposing internal gateway URL to browser
export async function POST(req: Request) {
  const body = await req.json();
  const gatewayUrl = process.env.KOCLAW_GATEWAY_URL;

  const response = await fetch(`${gatewayUrl}/api/v1/chat/public`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  // Forward SSE stream
  return new Response(response.body, {
    headers: { 'Content-Type': 'text/event-stream' },
  });
}
```

## Option 2: WebSocket Channel (For Rich Interactive Features)

The WebSocket channel at port 18791 supports bidirectional communication with audio/expression data. Use this for features like:
- Real-time streaming responses
- Voice input/output (ASR/TTS)
- Live2D expression sync

### Protocol
```json
// Client → Gateway
{"type": "text-input", "content": "Hello Kokoron"}

// Gateway → Client (streaming)
{"type": "full-text", "content": "Hello! I'm Kokoron.", "expressions": ["joy"], "data": "<base64-audio>", "format": "wav"}
```

### Connection
```typescript
const ws = new WebSocket('ws://your-gateway:18791');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === 'full-text') {
    // Display text
    // Trigger Live2D expressions: msg.expressions
    // Play audio: msg.data (base64)
  }
};

ws.send(JSON.stringify({ type: 'text-input', content: 'Hello!' }));
```

## Option 3: Web Widget (Future — Phase 4)

The `@koclaw/web-widget` npm package will provide:
- Drop-in React component with Live2D avatar + chat panel
- Configurable theme to match host site
- Automatic SSE streaming
- Session persistence via localStorage

```tsx
import { KokoronWidget } from '@koclaw/web-widget';

<KokoronWidget
  gatewayUrl="https://your-gateway.com"
  theme="dark"
  position="bottom-right"
  language="en"
/>
```

**API spec already written**: See `docs/api/web-sdk-api.md` (596 lines) for the full component API, theming, and TypeScript types.

## Static Assets (Live2D, Voice)

Live2D models and voice reference audio are served from Koclaw's static file server:
```
http://your-gateway:18792/live2d/    → Live2D model files
http://your-gateway:18792/voice/     → TTS reference audio
```

## Environment Variables

### shinBlog side
```env
# .env.local
KOCLAW_GATEWAY_URL=http://127.0.0.1:18789       # Gateway REST API
NEXT_PUBLIC_KOCLAW_WS_URL=ws://127.0.0.1:18791  # WebSocket (if using Option 2)
NEXT_PUBLIC_KOCLAW_ASSETS_URL=http://127.0.0.1:18792  # Static assets (if using Live2D)
```

### Koclaw side (`config.toml`)
```toml
[gateway]
host = "127.0.0.1"
port = 18789

[channels.websocket]
enabled = true
host = "127.0.0.1"
port = 18791

[gateway.static_files]
enabled = true
host = "127.0.0.1"
port = 18792
root = "./assets"
```

## Security Notes

- Blog widget uses `Public` permission level — cannot execute tools or access files
- Rate limiting protects against abuse
- User input is sanitized before forwarding to Agent
- No private data (API keys, chat history from other channels) is exposed
- CORS must be configured on Gateway to allow shinBlog's domain
- For production: use HTTPS/WSS with a reverse proxy (nginx/Caddy)

## Reference Documentation

| Document | Path | Description |
|----------|------|-------------|
| Gateway API | `docs/api/gateway-api.md` | Full WebSocket protocol, message schemas, SSE streaming, auth |
| Web SDK API | `docs/api/web-sdk-api.md` | React component spec, theming, TypeScript types |
| Architecture | `docs/architecture/overview.md` | System diagram and component relationships |
| Trait Design | `docs/architecture/trait-design.md` | Channel, Router, Provider trait abstractions |
| Persona Config | `persona.yaml` | Kokoron identity, expressions, voice settings |
