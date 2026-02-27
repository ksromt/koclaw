# shinBlog Integration Guide

## Overview

shinBlog integrates with Koclaw via:
1. **Chat API** — REST/SSE endpoint for Kokoron conversations
2. **Web Widget** (future) — `@koclaw/web-widget` npm package with Live2D + Chat UI

## Chat API

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

## shinBlog Implementation

### Next.js API Route (`app/api/kokoron-chat/route.ts`)
```typescript
// Proxy to Koclaw Gateway
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

### Environment Variable
```
KOCLAW_GATEWAY_URL=https://your-koclaw-gateway.example.com
```

## Web Widget (Future — Phase 3+)

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

## Security Notes

- Blog widget uses `Public` permission level — cannot execute tools or access files
- Rate limiting protects against abuse
- User input is sanitized before forwarding to Agent
- No private data (API keys, chat history from other channels) is exposed
- CORS must be configured on Gateway to allow shinBlog's domain
