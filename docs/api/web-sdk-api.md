# Web SDK API Reference

**Package:** `@koclaw/web-widget`
**Status:** Planned (Phase 3)

This document specifies the public API for the Koclaw Web SDK, a drop-in React component that embeds the Kokoron AI assistant into any website. The SDK provides a chat interface with optional Live2D avatar, automatic SSE streaming, and configurable theming.

---

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Component API](#component-api)
- [Configuration Object](#configuration-object)
- [Events](#events)
- [Theming and Customization](#theming-and-customization)
- [Integration Examples](#integration-examples)
- [Headless Mode](#headless-mode)
- [TypeScript Types](#typescript-types)
- [Browser Support](#browser-support)

---

## Overview

The `@koclaw/web-widget` package provides two primary ways to add Kokoron to a website:

1. **React Component** -- `<KokoronWidget />` for React/Next.js applications.
2. **Script Tag** -- A standalone JavaScript bundle for plain HTML sites.

Both approaches connect to a Koclaw Gateway instance via the public chat API (`POST /api/v1/chat/public`) and render a floating chat panel with optional Live2D avatar.

### Architecture

```
+-------------------+        +------------------+        +----------------+
|   Host Website    |  SSE   |  Koclaw Gateway  |   WS   |  Koclaw Agent  |
|                   |------->|                  |------->|                |
| @koclaw/web-widget|<-------|  /api/v1/chat/   |<-------|  (Python)      |
|                   |        |  public          |        |                |
+-------------------+        +------------------+        +----------------+
```

---

## Installation

### npm / yarn / pnpm

```bash
npm install @koclaw/web-widget

# or
yarn add @koclaw/web-widget

# or
pnpm add @koclaw/web-widget
```

### CDN (Script Tag)

```html
<script src="https://unpkg.com/@koclaw/web-widget@latest/dist/koclaw-widget.umd.js"></script>
```

---

## Quick Start

### React

```tsx
import { KokoronWidget } from '@koclaw/web-widget';

function App() {
  return (
    <div>
      <h1>My Website</h1>
      <KokoronWidget gatewayUrl="https://your-gateway.example.com" />
    </div>
  );
}
```

### Plain HTML

```html
<!DOCTYPE html>
<html>
<head>
  <title>My Website</title>
</head>
<body>
  <h1>My Website</h1>

  <div id="koclaw-widget"></div>
  <script src="https://unpkg.com/@koclaw/web-widget@latest/dist/koclaw-widget.umd.js"></script>
  <script>
    KoclawWidget.mount('#koclaw-widget', {
      gatewayUrl: 'https://your-gateway.example.com',
      theme: 'dark',
      position: 'bottom-right',
      language: 'en'
    });
  </script>
</body>
</html>
```

---

## Component API

### KokoronWidget

The primary React component for embedding the chat widget.

```tsx
<KokoronWidget
  gatewayUrl="https://your-gateway.example.com"
  theme="dark"
  position="bottom-right"
  language="en"
  avatar={true}
  greeting="Hello! I'm Kokoron. How can I help you?"
  placeholder="Type a message..."
  maxHeight={600}
  onMessage={(msg) => console.log(msg)}
  onError={(err) => console.error(err)}
  onSessionStart={(sessionId) => console.log(sessionId)}
/>
```

### Props

| Prop             | Type                      | Default          | Description                                        |
|------------------|---------------------------|------------------|----------------------------------------------------|
| `gatewayUrl`     | `string`                  | **(required)**   | URL of the Koclaw Gateway instance                 |
| `theme`          | `'light' \| 'dark' \| 'auto' \| ThemeConfig` | `'auto'` | Color theme or custom theme configuration |
| `position`       | `'bottom-right' \| 'bottom-left' \| 'top-right' \| 'top-left'` | `'bottom-right'` | Position of the floating widget |
| `language`       | `string`                  | `'en'`           | Preferred response language (ISO 639-1)            |
| `avatar`         | `boolean`                 | `true`           | Show Live2D avatar (if available) or static avatar |
| `greeting`       | `string \| null`          | `null`           | Initial greeting message shown when chat opens     |
| `placeholder`    | `string`                  | `'Type a message...'` | Input field placeholder text                 |
| `maxHeight`      | `number`                  | `500`            | Maximum height of the chat panel in pixels         |
| `maxWidth`       | `number`                  | `380`            | Maximum width of the chat panel in pixels          |
| `sessionId`      | `string \| null`          | `null`           | Resume an existing session (from localStorage)     |
| `persistSession` | `boolean`                 | `true`           | Persist session ID in localStorage                 |
| `open`           | `boolean`                 | `false`          | Control whether the chat panel is open             |
| `closable`       | `boolean`                 | `true`           | Allow the user to close/minimize the chat panel    |
| `className`      | `string`                  | `''`             | Additional CSS class for the root container        |
| `style`          | `React.CSSProperties`    | `{}`             | Inline styles for the root container               |
| `onMessage`      | `(message: ChatMessage) => void` | `undefined` | Callback when a message is sent or received    |
| `onError`        | `(error: WidgetError) => void`   | `undefined` | Callback when an error occurs                  |
| `onSessionStart` | `(sessionId: string) => void`    | `undefined` | Callback when a new session starts             |
| `onOpen`         | `() => void`              | `undefined`      | Callback when the chat panel opens                 |
| `onClose`        | `() => void`              | `undefined`      | Callback when the chat panel closes                |

---

## Configuration Object

When using the script tag / UMD build, configuration is passed as a plain object to `KoclawWidget.mount()`.

```typescript
interface KoclawWidgetConfig {
  // Required
  gatewayUrl: string;

  // Appearance
  theme?: 'light' | 'dark' | 'auto' | ThemeConfig;
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  avatar?: boolean;
  greeting?: string | null;
  placeholder?: string;
  maxHeight?: number;
  maxWidth?: number;
  closable?: boolean;

  // Behavior
  language?: string;
  sessionId?: string | null;
  persistSession?: boolean;
  open?: boolean;

  // Callbacks
  onMessage?: (message: ChatMessage) => void;
  onError?: (error: WidgetError) => void;
  onSessionStart?: (sessionId: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
}
```

### Static Methods (UMD Build)

| Method                                          | Description                                    |
|-------------------------------------------------|------------------------------------------------|
| `KoclawWidget.mount(selector, config)`          | Mount the widget into a DOM element            |
| `KoclawWidget.unmount(selector)`                | Unmount and clean up the widget                |
| `KoclawWidget.getInstance(selector)`            | Get the widget instance for programmatic control |

---

## Events

### onMessage

Fired when a message is sent by the user or received from the agent.

```typescript
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  sessionId: string;
}
```

### onError

Fired when an error occurs (network failure, rate limiting, etc.).

```typescript
interface WidgetError {
  code: string;          // Error code from Gateway (e.g., 'RATE_LIMITED')
  message: string;       // Human-readable error message
  retryable: boolean;    // Whether the operation can be retried
  retryAfter?: number;   // Seconds to wait before retrying (if rate limited)
}
```

### onSessionStart

Fired when a new session is created. The session ID can be stored for resumption.

```typescript
onSessionStart: (sessionId: string) => void;
```

---

## Theming and Customization

### Built-in Themes

| Theme    | Description                                                     |
|----------|-----------------------------------------------------------------|
| `light`  | White background, dark text, suitable for light-themed sites    |
| `dark`   | Dark background, light text, suitable for dark-themed sites     |
| `auto`   | Follows the user's system preference (`prefers-color-scheme`)   |

### Custom Theme

Provide a `ThemeConfig` object for full control over colors, fonts, and spacing:

```typescript
interface ThemeConfig {
  // Panel
  panelBackground: string;       // e.g., '#1a1a2e'
  panelBorder: string;           // e.g., '1px solid #333'
  panelBorderRadius: string;     // e.g., '12px'
  panelShadow: string;           // e.g., '0 4px 24px rgba(0,0,0,0.3)'

  // Header
  headerBackground: string;      // e.g., '#16213e'
  headerText: string;            // e.g., '#e0e0e0'

  // Messages
  userBubbleBackground: string;  // e.g., '#0f3460'
  userBubbleText: string;        // e.g., '#ffffff'
  agentBubbleBackground: string; // e.g., '#2a2a4a'
  agentBubbleText: string;       // e.g., '#e0e0e0'

  // Input
  inputBackground: string;       // e.g., '#1a1a2e'
  inputText: string;             // e.g., '#e0e0e0'
  inputBorder: string;           // e.g., '1px solid #333'
  inputPlaceholder: string;      // e.g., '#666'

  // Button (floating toggle)
  buttonBackground: string;      // e.g., '#e94560'
  buttonText: string;            // e.g., '#ffffff'
  buttonSize: string;            // e.g., '56px'

  // Typography
  fontFamily: string;            // e.g., "'Inter', sans-serif"
  fontSize: string;              // e.g., '14px'

  // Scrollbar
  scrollbarTrack: string;        // e.g., 'transparent'
  scrollbarThumb: string;        // e.g., '#333'
}
```

### Example: Custom Theme

```tsx
<KokoronWidget
  gatewayUrl="https://your-gateway.example.com"
  theme={{
    panelBackground: '#0d1117',
    panelBorder: '1px solid #30363d',
    panelBorderRadius: '16px',
    headerBackground: '#161b22',
    headerText: '#c9d1d9',
    userBubbleBackground: '#1f6feb',
    userBubbleText: '#ffffff',
    agentBubbleBackground: '#21262d',
    agentBubbleText: '#c9d1d9',
    inputBackground: '#0d1117',
    inputText: '#c9d1d9',
    inputBorder: '1px solid #30363d',
    inputPlaceholder: '#484f58',
    buttonBackground: '#238636',
    buttonText: '#ffffff',
    buttonSize: '56px',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: '13px',
    scrollbarTrack: 'transparent',
    scrollbarThumb: '#30363d',
    panelShadow: '0 8px 32px rgba(0,0,0,0.4)'
  }}
/>
```

### CSS Custom Properties

The widget also exposes CSS custom properties (variables) for targeted overrides:

```css
.koclaw-widget {
  --koclaw-panel-bg: #1a1a2e;
  --koclaw-header-bg: #16213e;
  --koclaw-user-bubble-bg: #0f3460;
  --koclaw-agent-bubble-bg: #2a2a4a;
  --koclaw-button-bg: #e94560;
  --koclaw-font-family: 'Inter', sans-serif;
  --koclaw-font-size: 14px;
}
```

---

## Integration Examples

### Next.js (App Router)

```tsx
// app/components/ChatWidget.tsx
'use client';

import { KokoronWidget } from '@koclaw/web-widget';

export default function ChatWidget() {
  return (
    <KokoronWidget
      gatewayUrl={process.env.NEXT_PUBLIC_KOCLAW_GATEWAY_URL!}
      theme="auto"
      position="bottom-right"
      language="en"
      greeting="Hi there! I'm Kokoron, the AI assistant for this blog."
      onError={(err) => {
        if (err.code === 'AGENT_UNAVAILABLE') {
          console.warn('Kokoron is currently offline');
        }
      }}
    />
  );
}
```

```tsx
// app/layout.tsx
import ChatWidget from './components/ChatWidget';

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
        <ChatWidget />
      </body>
    </html>
  );
}
```

### Next.js (API Route Proxy)

If you want to proxy Gateway requests through your own API (to hide the Gateway URL from the client):

```typescript
// app/api/kokoron-chat/route.ts
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  const body = await req.json();
  const gatewayUrl = process.env.KOCLAW_GATEWAY_URL;

  const response = await fetch(`${gatewayUrl}/api/v1/chat/public`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  return new Response(response.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  });
}
```

Then configure the widget to use your proxy:

```tsx
<KokoronWidget gatewayUrl="/api/kokoron-chat" />
```

### Plain HTML with CDN

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My Blog</title>
</head>
<body>
  <main>
    <h1>Welcome to My Blog</h1>
    <p>Content goes here...</p>
  </main>

  <!-- Koclaw Widget -->
  <div id="kokoron-chat"></div>
  <script src="https://unpkg.com/@koclaw/web-widget@latest/dist/koclaw-widget.umd.js"></script>
  <script>
    KoclawWidget.mount('#kokoron-chat', {
      gatewayUrl: 'https://your-gateway.example.com',
      theme: 'auto',
      position: 'bottom-right',
      language: 'en',
      greeting: 'Hi! Ask me anything about this blog.',
      onError: function(err) {
        console.error('Koclaw widget error:', err.message);
      }
    });
  </script>
</body>
</html>
```

### Vue.js

```vue
<template>
  <div>
    <h1>My Vue App</h1>
    <div ref="widgetContainer"></div>
  </div>
</template>

<script>
import { onMounted, onUnmounted, ref } from 'vue';

export default {
  setup() {
    const widgetContainer = ref(null);

    onMounted(async () => {
      const { KoclawWidget } = await import('@koclaw/web-widget');
      KoclawWidget.mount(widgetContainer.value, {
        gatewayUrl: import.meta.env.VITE_KOCLAW_GATEWAY_URL,
        theme: 'auto',
        position: 'bottom-right',
      });
    });

    onUnmounted(() => {
      const { KoclawWidget } = require('@koclaw/web-widget');
      KoclawWidget.unmount(widgetContainer.value);
    });

    return { widgetContainer };
  }
};
</script>
```

---

## Headless Mode

For developers who want full control over the UI, the SDK exports a headless client that handles only the communication with the Gateway:

```typescript
import { KoclawClient } from '@koclaw/web-widget/headless';

const client = new KoclawClient({
  gatewayUrl: 'https://your-gateway.example.com',
  language: 'en',
});

// Send a message and iterate over streamed response chunks
const stream = client.chat('Hello, Kokoron!');

for await (const chunk of stream) {
  if (chunk.type === 'text') {
    process.stdout.write(chunk.content);
  } else if (chunk.type === 'done') {
    console.log('\n[Session:', chunk.sessionId, ']');
  } else if (chunk.type === 'error') {
    console.error('Error:', chunk.message);
  }
}
```

### KoclawClient API

| Method                                     | Returns                      | Description                          |
|--------------------------------------------|------------------------------|--------------------------------------|
| `new KoclawClient(config)`                 | `KoclawClient`               | Create a new headless client         |
| `client.chat(message, sessionId?)`         | `AsyncIterable<StreamChunk>` | Send a message and stream response   |
| `client.getSessionId()`                    | `string \| null`             | Get the current session ID           |
| `client.clearSession()`                    | `void`                       | Clear the current session            |
| `client.destroy()`                         | `void`                       | Clean up resources                   |

### StreamChunk Types

```typescript
type StreamChunk =
  | { type: 'text'; content: string }
  | { type: 'done'; sessionId: string }
  | { type: 'error'; code: string; message: string; retryable: boolean };
```

---

## TypeScript Types

The package exports all types for TypeScript consumers:

```typescript
import type {
  KokoronWidgetProps,
  KoclawWidgetConfig,
  ThemeConfig,
  ChatMessage,
  WidgetError,
  StreamChunk,
  KoclawClientConfig,
} from '@koclaw/web-widget';
```

---

## Browser Support

| Browser          | Minimum Version | Notes                                      |
|------------------|-----------------|---------------------------------------------|
| Chrome           | 80+             | Full support                                |
| Firefox          | 78+             | Full support                                |
| Safari           | 14+             | Full support                                |
| Edge             | 80+             | Full support (Chromium-based)               |
| iOS Safari       | 14+             | Full support                                |
| Chrome Android   | 80+             | Full support                                |

### Required Browser APIs

- `fetch` (with streaming body support)
- `ReadableStream`
- `TextDecoder`
- `localStorage` (for session persistence)
- `matchMedia` (for `theme: 'auto'`)
- `IntersectionObserver` (for lazy loading Live2D)

---

## Accessibility

The widget follows WAI-ARIA guidelines:

- Chat panel has `role="dialog"` with `aria-label`.
- Messages are rendered in a live region (`aria-live="polite"`).
- Toggle button has `aria-expanded` and `aria-haspopup` attributes.
- All interactive elements are keyboard-navigable.
- Focus is trapped within the open panel.
- Color contrast meets WCAG 2.1 AA standards for all built-in themes.
