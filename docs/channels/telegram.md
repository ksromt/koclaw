# Telegram Channel Setup Guide

## Prerequisites

1. A Telegram account
2. Create a bot via [@BotFather](https://t.me/BotFather):
   - Send `/newbot`
   - Choose a display name (e.g., "Kokoron")
   - Choose a username (must end in `bot`, e.g., `kokoron_ai_bot`)
   - Save the token: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

## Configuration

Set the environment variable:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

Or in `config.toml`:
```toml
[channels.telegram]
enabled = true
token_env = "TELEGRAM_BOT_TOKEN"
mode = "webhook"  # "webhook" (production) or "polling" (development)
webhook_url = "https://your-domain.com/webhook/telegram"
allowed_users = []  # empty = allow all; or list of telegram user IDs
```

## Message Modes

### Polling (Development)
- No HTTPS required
- Bot polls Telegram servers for updates
- Higher latency, simpler setup

### Webhook (Production)
- Requires HTTPS endpoint
- Telegram pushes updates to your server
- Lower latency, recommended for production

## Supported Features

| Feature | Status | Notes |
|---------|--------|-------|
| Text messages | Supported | Markdown formatting in replies |
| Voice messages | Supported | Auto-transcribed via ASR pipeline |
| Images | Supported | Forwarded to multimodal LLM |
| Files | Supported | Downloaded to sandbox workspace |
| Inline keyboards | Supported | For confirmation dialogs |
| Group chats | Supported | Responds to @mentions or /commands |
| Commands | Supported | /start, /help, /clear, /mode |
| Stickers | Partial | Recognized but not generated |

## Rate Limits

- Private chat: ~30 messages/second
- Group chat: ~20 messages/minute per group
- Broadcast: ~30 messages/second across all chats

## Bot Commands (register via @BotFather `/setcommands`)

```
start - Start conversation with Kokoron
help - Show available commands
clear - Clear conversation history
mode - Switch agent mode (chat/assistant/code)
status - Show agent status
```
