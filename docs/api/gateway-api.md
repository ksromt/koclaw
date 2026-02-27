# Gateway API Reference

This document specifies the Koclaw Gateway's external and internal APIs, including the WebSocket protocol for Agent communication, the public chat endpoint for web integration, authentication flows, and error handling.

---

## Table of Contents

- [Overview](#overview)
- [WebSocket Protocol (Gateway <-> Agent Bridge)](#websocket-protocol-gateway---agent-bridge)
- [Message Schemas](#message-schemas)
- [Chat Request / Response Protocol](#chat-request--response-protocol)
- [Streaming Response Protocol (SSE)](#streaming-response-protocol-sse)
- [Public Chat Endpoint](#public-chat-endpoint)
- [Authentication Flow](#authentication-flow)
- [Error Codes](#error-codes)
- [Rate Limiting](#rate-limiting)

---

## Overview

The Koclaw Gateway exposes two categories of APIs:

1. **Internal APIs** -- Used for communication between the Rust Gateway and the Python Agent. These use WebSocket with JSON-encoded messages.
2. **External APIs** -- Used by web clients (shinBlog, web widget) to interact with the Kokoron agent. These use REST + Server-Sent Events (SSE).

All external APIs require TLS in production. Internal APIs may run over plain WebSocket on localhost for single-machine deployments.

### Base URLs

| API          | Default URL                         | Protocol    |
|--------------|-------------------------------------|-------------|
| Gateway HTTP | `http://127.0.0.1:18789`           | REST + SSE  |
| Agent Bridge | `ws://127.0.0.1:18790`             | WebSocket   |

---

## WebSocket Protocol (Gateway <-> Agent Bridge)

The Gateway communicates with the Python Agent over a persistent WebSocket connection. All messages are JSON-encoded UTF-8 text frames.

### Connection Lifecycle

```
Gateway                                Agent
   |                                      |
   |--- WebSocket Connect --------------->|
   |                                      |
   |<-- Connection Acknowledged ----------|
   |    {"type": "connected",             |
   |     "agent_version": "0.1.0"}        |
   |                                      |
   |--- Chat Request -------------------->|
   |    {"type": "chat", ...}             |
   |                                      |
   |<-- Response Chunk -------------------|
   |    {"type": "text_chunk", ...}       |
   |                                      |
   |<-- Response Chunk -------------------|
   |    {"type": "text_chunk", ...}       |
   |                                      |
   |<-- Done -----------------------------|
   |    {"type": "done", ...}             |
   |                                      |
   |--- Ping ----------------------------->|
   |<-- Pong -----------------------------|
   |                                      |
```

### Heartbeat

The Gateway sends WebSocket Ping frames every 30 seconds. If the Agent does not respond with a Pong within 10 seconds, the connection is considered dead and the Gateway will attempt to reconnect with exponential backoff (1s, 2s, 4s, 8s, max 60s).

### Reconnection

On connection loss, the Gateway:

1. Queues incoming messages from channels.
2. Attempts reconnection with exponential backoff.
3. On reconnection, flushes the queued messages in order.
4. If the queue exceeds 1000 messages, older messages are dropped and an error is logged.

---

## Message Schemas

### IncomingMessage (Channel -> Gateway -> Agent)

This is the normalized message format that all channel implementations produce. The Gateway forwards it to the Agent for processing.

```json
{
  "type": "chat",
  "id": "msg_tg_12345678",
  "channel": "telegram",
  "user_id": "tg:98765432",
  "display_name": "Alice",
  "text": "Hello, Kokoron! What is the weather today?",
  "attachments": [
    {
      "attachment_type": "Image",
      "url": "https://api.telegram.org/file/bot.../photo.jpg",
      "mime_type": "image/jpeg",
      "file_name": "photo.jpg",
      "size": 245760
    }
  ],
  "permission": "Authenticated",
  "session_id": "sess_abc123def456",
  "timestamp": 1709078400000
}
```

#### Field Reference

| Field            | Type             | Required | Description                                           |
|------------------|------------------|----------|-------------------------------------------------------|
| `type`           | string           | Yes      | Always `"chat"` for chat requests                     |
| `id`             | string           | Yes      | Unique message ID from the source channel             |
| `channel`        | string           | Yes      | Channel identifier: `telegram`, `qq`, `discord`, `websocket`, `web-public` |
| `user_id`        | string           | Yes      | User identifier, prefixed by channel (e.g., `tg:12345`) |
| `display_name`   | string or null   | No       | Human-readable display name of the sender             |
| `text`           | string or null   | No       | Text content of the message (null for media-only)     |
| `attachments`    | array            | Yes      | Array of Attachment objects (empty if none)            |
| `permission`     | string           | Yes      | Permission level: `Public`, `Authenticated`, `Admin`  |
| `session_id`     | string           | Yes      | Session ID for conversation continuity                |
| `timestamp`      | integer          | Yes      | Unix timestamp in milliseconds                        |

#### Attachment Object

| Field             | Type           | Required | Description                                     |
|-------------------|----------------|----------|-------------------------------------------------|
| `attachment_type` | string         | Yes      | One of: `Image`, `Voice`, `Video`, `File`       |
| `url`             | string         | Yes      | URL or local file path to the attachment         |
| `mime_type`       | string or null | No       | MIME type (e.g., `image/jpeg`, `audio/ogg`)     |
| `file_name`       | string or null | No       | Original file name                              |
| `size`            | integer or null| No       | File size in bytes                              |

### OutgoingMessage (Agent -> Gateway -> Channel)

Response from the Agent, routed back through the appropriate channel.

```json
{
  "channel": "telegram",
  "target_id": "tg:98765432",
  "text": "Hello, Alice! I can check the weather for you. It looks like it will be sunny today with a high of 22C.",
  "attachments": [],
  "reply_to": "msg_tg_12345678"
}
```

#### Field Reference

| Field        | Type           | Required | Description                                           |
|--------------|----------------|----------|-------------------------------------------------------|
| `channel`    | string         | Yes      | Target channel identifier                             |
| `target_id`  | string         | Yes      | Target user or chat ID on the channel                 |
| `text`       | string or null | No       | Text content (supports channel-specific formatting)   |
| `attachments`| array          | Yes      | Array of Attachment objects to send                   |
| `reply_to`   | string or null | No       | ID of the message being replied to (if supported)     |

---

## Chat Request / Response Protocol

### Standard (Non-Streaming) Flow

For simple request-response interactions where the full response is returned at once.

**Gateway -> Agent:**

```json
{
  "type": "chat",
  "id": "msg_web_001",
  "channel": "web-public",
  "user_id": "web:anonymous_abc",
  "display_name": null,
  "text": "Tell me about this blog",
  "attachments": [],
  "permission": "Public",
  "session_id": "sess_web_xyz789",
  "timestamp": 1709078400000
}
```

**Agent -> Gateway (streamed response):**

```json
{"type": "text_chunk", "session_id": "sess_web_xyz789", "content": "Hello! "}
{"type": "text_chunk", "session_id": "sess_web_xyz789", "content": "I'm Kokoron, "}
{"type": "text_chunk", "session_id": "sess_web_xyz789", "content": "the AI assistant for this blog. "}
{"type": "text_chunk", "session_id": "sess_web_xyz789", "content": "How can I help you today?"}
{"type": "done", "session_id": "sess_web_xyz789"}
```

### Agent Response Message Types

| Type           | Description                                              |
|----------------|----------------------------------------------------------|
| `text_chunk`   | A partial text response (for streaming)                  |
| `done`         | Signals that the response is complete                    |
| `error`        | An error occurred during processing                      |
| `tool_start`   | Agent is beginning tool execution (name, args)           |
| `tool_result`  | Result of tool execution                                 |
| `thinking`     | Agent reasoning/thinking output (optional, debug only)   |

#### text_chunk

```json
{
  "type": "text_chunk",
  "session_id": "sess_abc123",
  "content": "partial response text"
}
```

#### done

```json
{
  "type": "done",
  "session_id": "sess_abc123",
  "usage": {
    "input_tokens": 150,
    "output_tokens": 87,
    "model": "claude-sonnet-4-20250514"
  }
}
```

#### error

```json
{
  "type": "error",
  "session_id": "sess_abc123",
  "code": "PROVIDER_ERROR",
  "message": "LLM provider returned an error: rate limit exceeded"
}
```

#### tool_start

```json
{
  "type": "tool_start",
  "session_id": "sess_abc123",
  "tool_name": "web_search",
  "tool_args": {"query": "weather Tokyo today"}
}
```

#### tool_result

```json
{
  "type": "tool_result",
  "session_id": "sess_abc123",
  "tool_name": "web_search",
  "result": "Sunny, 22C, humidity 45%",
  "success": true
}
```

---

## Streaming Response Protocol (SSE)

External clients (web browsers, shinBlog) consume responses via Server-Sent Events (SSE) over HTTP.

### Endpoint

```
POST /api/v1/chat/public
Content-Type: application/json
Accept: text/event-stream
```

### SSE Event Format

Each event follows the SSE specification (https://html.spec.whatwg.org/multipage/server-sent-events.html):

```
data: {"type": "text", "content": "Hello! "}

data: {"type": "text", "content": "I'm Kokoron. "}

data: {"type": "text", "content": "How can I help you?"}

data: {"type": "done", "session_id": "sess_abc123"}

```

### SSE Event Types

| Event Type | Description                                              |
|------------|----------------------------------------------------------|
| `text`     | A chunk of text response                                 |
| `done`     | Response is complete, includes session_id for continuity |
| `error`    | An error occurred; includes code and message             |

### Client Implementation Example (JavaScript)

```javascript
async function sendMessage(message, sessionId) {
  const response = await fetch('/api/v1/chat/public', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: message,
      session_id: sessionId,
      language: 'en'
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        if (data.type === 'text') {
          appendToChat(data.content);
        } else if (data.type === 'done') {
          sessionId = data.session_id;
        } else if (data.type === 'error') {
          showError(data.message);
        }
      }
    }
  }
}
```

---

## Public Chat Endpoint

The public chat endpoint is designed for web integration (e.g., shinBlog). It operates at the `Public` permission level.

### POST /api/v1/chat/public

Send a chat message and receive a streaming response.

**Request:**

```json
{
  "message": "Tell me about this blog",
  "session_id": "optional-session-id-for-continuity",
  "language": "en"
}
```

| Field        | Type           | Required | Description                                           |
|--------------|----------------|----------|-------------------------------------------------------|
| `message`    | string         | Yes      | The user's message text (max 4096 characters)         |
| `session_id` | string or null | No       | Session ID for conversation continuity. Omit to start a new session. |
| `language`   | string         | No       | Preferred response language (default: `en`)           |

**Response:**

Content-Type: `text/event-stream`

The response is an SSE stream as described in the Streaming Response Protocol section above.

**Response Headers:**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Koclaw-Session-Id: sess_abc123
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1709078460
```

### Constraints (Public Permission Level)

- No tool execution -- the agent responds with conversation only.
- No access to private user data, memories, or files.
- Rate limited per IP address (default: 10 messages per minute).
- Maximum message length: 4096 characters.
- Maximum session history: 50 messages (older messages are pruned).
- Input is sanitized before forwarding to the Agent.

### CORS Configuration

The Gateway must be configured to allow requests from the web client's origin:

```toml
[gateway.cors]
allowed_origins = ["https://your-blog.com", "http://localhost:3000"]
allow_credentials = false
```

---

## Authentication Flow

### Channel-Based Authentication (SNS Channels)

For Telegram, QQ, and Discord, authentication is handled by the channel platform itself. The Gateway trusts the channel's user identification and maps it to a Koclaw user identity.

```
User (Telegram) -> Telegram API -> Koclaw Channel -> Gateway
                                                      |
                                       user_id: "tg:12345"
                                       permission: Authenticated
```

### Session-Based Authentication (Web/WebSocket)

For web clients and direct WebSocket connections, Koclaw uses session tokens.

**Step 1: Create Session**

```
POST /api/v1/session
```

Response:

```json
{
  "session_id": "sess_abc123def456",
  "expires_at": 1709164800000,
  "permission": "Public"
}
```

**Step 2: Use Session**

Include the session_id in subsequent chat requests. The session maintains conversation history and context.

### E2E Encrypted Session (Desktop/Authenticated Clients)

For clients that support E2E encryption, an additional key exchange step is required before chat messages can be sent.

**Step 1: Client Hello**

```json
{
  "type": "client_hello",
  "client_ephemeral_pubkey": "<base64-encoded X25519 public key>"
}
```

**Step 2: Server Hello**

```json
{
  "type": "server_hello",
  "server_ephemeral_pubkey": "<base64-encoded X25519 public key>",
  "session_id": "sess_encrypted_xyz"
}
```

**Step 3: Derive Session Key**

Both sides compute:
```
shared_secret = X25519(own_private_key, peer_public_key)
session_key = HKDF-SHA256(shared_secret, salt="koclaw-session-v1", info="")
```

**Step 4: Encrypted Messages**

All subsequent messages in this session are encrypted with ChaCha20-Poly1305 using the derived session key.

```json
{
  "type": "encrypted",
  "session_id": "sess_encrypted_xyz",
  "nonce": "<base64-encoded 12-byte nonce>",
  "ciphertext": "<base64-encoded encrypted payload>"
}
```

---

## Error Codes

All errors follow a consistent format:

```json
{
  "type": "error",
  "code": "ERROR_CODE",
  "message": "Human-readable error description",
  "details": {}
}
```

### Error Code Reference

| Code                    | HTTP Status | Description                                              |
|-------------------------|-------------|----------------------------------------------------------|
| `BAD_REQUEST`           | 400         | Malformed request body or missing required fields        |
| `UNAUTHORIZED`          | 401         | Missing or invalid authentication credentials            |
| `PERMISSION_DENIED`     | 403         | Action requires higher permission level                  |
| `NOT_FOUND`             | 404         | Requested resource does not exist                        |
| `RATE_LIMITED`          | 429         | Too many requests; retry after the specified delay       |
| `MESSAGE_TOO_LONG`     | 400         | Message exceeds maximum length (4096 characters)         |
| `SESSION_EXPIRED`       | 401         | Session has expired; create a new session                |
| `AGENT_UNAVAILABLE`     | 503         | Python Agent is not connected or not responding          |
| `PROVIDER_ERROR`        | 502         | LLM provider returned an error                           |
| `ENCRYPTION_ERROR`      | 400         | E2E encryption handshake or decryption failed            |
| `CHANNEL_ERROR`         | 502         | Error communicating with the channel platform            |
| `INTERNAL_ERROR`        | 500         | Unexpected internal server error                         |

### Error Response Examples

**Rate Limited:**

```json
{
  "type": "error",
  "code": "RATE_LIMITED",
  "message": "Rate limit exceeded. Please retry after 45 seconds.",
  "details": {
    "retry_after_seconds": 45,
    "limit": 10,
    "window": "1m"
  }
}
```

**Permission Denied:**

```json
{
  "type": "error",
  "code": "PERMISSION_DENIED",
  "message": "Tool execution requires Authenticated permission level, but this session has Public permission.",
  "details": {
    "action": "execute_tool",
    "required": "Authenticated",
    "actual": "Public"
  }
}
```

---

## Rate Limiting

Rate limits are enforced per IP address for public endpoints and per user identity for authenticated channels.

### Default Limits

| Endpoint / Channel       | Limit                    | Window    |
|--------------------------|--------------------------|-----------|
| `POST /api/v1/chat/public` | 10 requests           | 1 minute  |
| `POST /api/v1/session`     | 5 requests            | 1 minute  |
| Telegram (per user)        | 30 messages            | 1 minute  |
| QQ (per user)              | 20 messages            | 1 minute  |
| Discord (per user)         | 30 messages            | 1 minute  |
| WebSocket (per session)    | 60 messages            | 1 minute  |

### Rate Limit Headers

All HTTP responses include rate limit information:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1709078460
```

| Header                  | Description                                           |
|-------------------------|-------------------------------------------------------|
| `X-RateLimit-Limit`    | Maximum requests allowed in the current window        |
| `X-RateLimit-Remaining`| Remaining requests in the current window              |
| `X-RateLimit-Reset`    | Unix timestamp when the window resets                 |

### Configuration

Rate limits are configurable in `config.toml`:

```toml
[gateway.rate_limit]
public_chat_per_minute = 10
session_create_per_minute = 5
authenticated_per_minute = 30

[gateway.rate_limit.burst]
enabled = true
multiplier = 2    # Allow 2x burst for short periods
window_seconds = 5
```

### Exceeding Rate Limits

When a rate limit is exceeded, the Gateway returns:

- HTTP 429 status code for REST endpoints.
- An error message through the WebSocket for WebSocket-connected clients.
- The channel-appropriate equivalent for SNS channels (e.g., a polite "please slow down" message on Telegram).
