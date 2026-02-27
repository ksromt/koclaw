# QQ Channel Setup Guide

## Prerequisites

1. A QQ account
2. Register as developer at [QQ Open Platform](https://q.qq.com)
3. Create a Bot application:
   - Navigate to "机器人" section
   - Create new bot → fill in name, description, avatar
   - Submit for review (may take 1-3 business days)
   - After approval, obtain `APP_ID` and `APP_SECRET`

## Configuration

Set environment variables:
```
QQ_BOT_APP_ID=your_app_id
QQ_BOT_SECRET=your_app_secret
```

Or in `config.toml`:
```toml
[channels.qq]
enabled = true
app_id_env = "QQ_BOT_APP_ID"
secret_env = "QQ_BOT_SECRET"
sandbox = true  # true for development (sandbox guild), false for production
intents = ["guild_messages", "direct_messages", "group_at_messages"]
```

## QQ Bot Types

| Type | Scope | Setup |
|------|-------|-------|
| 频道机器人 (Guild Bot) | QQ Channels (频道) | Official API, stable |
| 群机器人 (Group Bot) | QQ Groups (群) | Official API, requires additional permissions |
| 私聊 (Direct Message) | Private conversations | Available after user initiates |

## Official SDK

QQ provides an official Go SDK: `github.com/tencent-connect/botgo`

For Rust, there is no official SDK. Options:
1. Use the REST API directly with `reqwest`
2. Use WebSocket for event-based communication
3. Wrap the Go SDK via FFI (not recommended)

## Supported Features

| Feature | Status | Notes |
|---------|--------|-------|
| Text messages | Supported | Markdown subset |
| Images | Supported | Upload via media API |
| Voice | Limited | Not in all contexts |
| @mention trigger | Supported | Bot responds when mentioned |
| Commands | Supported | Slash commands registered via API |
| Embeds/Cards | Supported | Rich message cards (Ark templates) |
| Direct messages | Supported | After user initiates first |
| Reactions | Supported | Emoji reactions |

## Important Notes

- QQ Bot API is separate from personal QQ login
- Bot can only interact in guilds/groups where it has been added
- Review process required for public bots
- Sandbox mode available for testing without review
- Rate limits apply (varies by bot type and tier)

## Alternative: Unofficial Frameworks

For personal QQ account integration (NOT recommended for production):
- NapCat, LLOneBot — use personal QQ account as bot
- Risk: violates QQ ToS, account may be banned
- Only suitable for personal experimentation
