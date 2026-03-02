<p align="center">
  <img src="assets/kokoron.png" alt="Kokoron" width="160">
</p>

<h1 align="center">Koclaw</h1>
<p align="center">安全的跨平台 AI Agent 框架 / セキュアなクロスプラットフォームAIエージェント / Secure Cross-Platform AI Agent Framework</p>

<p align="center">
  <a href="#中文">中文</a> · <a href="#日本語">日本語</a> · <a href="#english">English</a>
</p>

---

# 中文

## 这是什么

Koclaw 是一个面向个人部署的 AI Agent 框架。它的核心理念很简单：**一个 AI 角色，多个平台，统一记忆，端到端加密**。

你可以在 Telegram、QQ、Discord 上跟同一个 AI 助手对话，也可以通过桌面客户端的 Live2D 形象跟它面对面互动。不管从哪个渠道发消息，它都知道你是谁，记得之前聊过什么，并且保持一致的人格特征。更重要的是，即使服务器被入侵，攻击者也无法读取你的消息——因为所有对话都经过端到端加密。

项目名来自 **Ko**koron + **claw** —— Kokoron 是默认内置的 AI 角色，claw 表示它属于 AI Agent 生态的一部分。

## 设计出发点

市面上已经有不少优秀的开源项目在做类似的事情：

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** 做了非常棒的本地 LLM + Live2D VTuber 体验，支持语音打断和完全离线运行。但它主要面向桌面端单人使用，没有多平台 SNS 集成。
- **[OpenClaw](https://github.com/openclaw/openclaw)** 是功能最全面的个人 AI 助手框架之一，支持 WhatsApp/Telegram/Slack 等二十多个频道，生态非常丰富。但它是纯 TypeScript 实现，没有端到端加密，也没有 Live2D 角色化体验。
- **[ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw)** 把 Agent 运行时做到了极致轻量（3.4MB + 10ms 冷启动），纯 Rust 实现，非常适合边缘部署。但它专注于运行时基础设施，不包含 LLM 编排、语音管线等上层功能。

Koclaw 试图在这些项目之间找到自己的位置：

| | Open-LLM-VTuber | OpenClaw | ZeroClaw | **Koclaw** |
|---|---|---|---|---|
| 核心语言 | Python | TypeScript | Rust | **Rust + Python** |
| 端到端加密 | — | — | — | **X25519 + ChaCha20** |
| Live2D 角色 | 桌面端 | — | — | **多平台 (桌面/Web)** |
| SNS 集成 | — | 20+ 频道 | 频道插件 | **Telegram/QQ/Discord/Web** |
| 语音管线 | ASR + TTS | TTS | — | **ASR + TTS (GPT-SoVITS)** |
| 本地 LLM | 全面支持 | 部分支持 | 支持 | **支持 (Ollama)** |
| 内存安全 | 运行时 | 运行时 | 编译期 | **编译期 (Gateway)** |
| 定时任务 | — | Cron 服务 | — | **Cron + 一次性提醒** |
| MCP 工具 | 支持 | — | 支持 | **支持 (27+ 工具)** |

简单说，Koclaw 的核心优势是：**Rust 保证安全性 + Python 接入 ML 生态 + 端到端加密 + Live2D 角色化 + 跨平台统一身份**。

## 目前实现了什么

项目目前完成了 5 个开发阶段：

- **Phase 1-2**: Rust Gateway 核心、Telegram/QQ/Discord 频道、X25519 密钥交换、加密存储、权限系统、沙箱
- **Phase 3**: 对接 [AIKokoron](https://github.com/shinyo-io/AIKokoron) 的 Agent 逻辑、统一人设系统 (`persona.yaml`)、对话记忆、表情系统、GPT-SoVITS 语音合成、Whisper 语音识别、WebSocket 频道、Live2D 资源服务
- **Phase 4**: MCP 工具系统（27 个工具）、ClawHub 技能生态对接、权限分级的工具访问控制
- **Phase 5**: 定时提醒器、Cron 定时任务、心跳检测系统、主动消息推送

> **关于 AIKokoron**: Koclaw 的 Python Agent 层大量复用了 [AIKokoron](https://github.com/shinyo-io/AIKokoron) 的代码。AIKokoron 是一个正在开发中的独立项目，实现了 LLM 编排、语音管线、Live2D 前端等功能。目前尚未公开发布，但其核心能力已经集成到 Koclaw 中。

**测试覆盖**: 124 个测试（66 Rust + 58 Python），全部通过。

## 技术栈

- **Gateway**: Rust (tokio, axum, chacha20poly1305, x25519-dalek)
- **Agent**: Python (websockets, openai/anthropic SDK, MCP, loguru)
- **支持的 LLM**: Claude / GPT-4o / DeepSeek / Ollama (本地)
- **语音**: GPT-SoVITS (TTS) + Faster-Whisper (ASR)
- **桌面**: Electron + React + Live2D Cubism SDK
- **配置**: TOML + 环境变量，无需改代码即可切换频道和模型

## 快速开始

```bash
git clone https://github.com/ArcadiaFrame/koclaw.git && cd koclaw

# 编译 Gateway
cargo build --release

# 安装 Agent 依赖
cd agent && uv sync && cd ..

# 配置
cp config.example.toml config.toml
cp persona.yaml.example persona.yaml
# 编辑 config.toml 和 .env 设置 API Key 和 Bot Token

# 启动
cd agent && uv run python -m koclaw_agent &  # Agent
cargo run --release                            # Gateway
```

详细部署指南见项目内 `docs/deployment-linux.md`。

## 未来计划

- Web 嵌入 SDK (`@koclaw/web-widget`) — 一行代码在任意网站嵌入 AI 聊天
- 真正的零知识端到端加密 — Gateway 只做中转，完全无法解密
- RAG 知识库集成
- 多 Agent 协作
- Double Ratchet 前向保密

## 许可证

MIT License

---

# 日本語

## 概要

Koclaw は個人向けの AI エージェントフレームワークです。基本的な考え方はシンプルで、**一つの AI キャラクター、複数のプラットフォーム、統一された記憶、エンドツーエンド暗号化**。

Telegram、QQ、Discord で同じ AI アシスタントと会話でき、デスクトップでは Live2D アバターを通じて対面のようなやり取りもできます。どのチャンネルからメッセージを送っても、誰なのかを認識し、以前の会話を覚えており、一貫した性格を保ちます。さらに重要なのは、サーバーが侵害されても攻撃者はメッセージを読めないということ——すべてのやり取りはエンドツーエンドで暗号化されているからです。

プロジェクト名は **Ko**koron + **claw** から。Kokoron はデフォルトの AI キャラクター、claw は AI エージェントエコシステムの一部であることを示しています。

## 設計の背景

この分野には既に優れたオープンソースプロジェクトがあります：

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** — ローカル LLM + Live2D VTuber の素晴らしい体験を実現。音声割り込みや完全オフライン動作をサポート。ただし主にデスクトップ向けで、SNS マルチチャンネル連携はありません。
- **[OpenClaw](https://github.com/openclaw/openclaw)** — 20 以上のチャンネルをサポートする最も包括的な個人 AI アシスタント。TypeScript 実装でエコシステムが豊富。ただし E2E 暗号化や Live2D キャラクター体験はありません。
- **[ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw)** — エージェントランタイムを極限まで軽量化（3.4MB、コールドスタート 10ms）。純 Rust 実装でエッジデプロイに最適。ただしランタイム基盤に特化しており、LLM オーケストレーションや音声パイプラインは含みません。

Koclaw はこれらのプロジェクトの間で独自のポジションを目指しています：

| | Open-LLM-VTuber | OpenClaw | ZeroClaw | **Koclaw** |
|---|---|---|---|---|
| コア言語 | Python | TypeScript | Rust | **Rust + Python** |
| E2E 暗号化 | — | — | — | **X25519 + ChaCha20** |
| Live2D キャラクター | デスクトップ | — | — | **マルチプラットフォーム** |
| SNS 連携 | — | 20+ チャンネル | チャンネルプラグイン | **Telegram/QQ/Discord/Web** |
| 音声パイプライン | ASR + TTS | TTS | — | **ASR + TTS (GPT-SoVITS)** |
| メモリ安全性 | ランタイム | ランタイム | コンパイル時 | **コンパイル時 (Gateway)** |
| MCP ツール | サポート | — | サポート | **サポート (27+ ツール)** |

Koclaw の強みは：**Rust によるセキュリティ + Python の ML エコシステム + E2E 暗号化 + Live2D キャラクター + クロスプラットフォーム統一アイデンティティ**。

## 実装状況

5 つの開発フェーズが完了しています：

- **Phase 1-2**: Gateway コア、チャンネル実装（Telegram/QQ/Discord）、X25519 鍵交換、暗号化ストレージ、権限システム、サンドボックス
- **Phase 3**: [AIKokoron](https://github.com/shinyo-io/AIKokoron) の Agent ロジック統合、統一ペルソナ (`persona.yaml`)、会話メモリ、表情システム、GPT-SoVITS 音声合成、Whisper 音声認識、WebSocket チャンネル
- **Phase 4**: MCP ツールシステム（27 ツール）、ClawHub スキルエコシステム対応、権限ベースのツールアクセス制御
- **Phase 5**: リマインダー、Cron スケジューラー、ハートビート監視、プロアクティブメッセージ配信

> **AIKokoron について**: Koclaw の Python Agent レイヤーは [AIKokoron](https://github.com/shinyo-io/AIKokoron) のコードを多く再利用しています。AIKokoron は現在開発中の独立プロジェクトで、LLM オーケストレーション、音声パイプライン、Live2D フロントエンドなどを実装しています。まだ公開リリースはされていませんが、コア機能は Koclaw に統合済みです。

**テストカバレッジ**: 124 テスト（Rust 66 + Python 58）、全パス。

## 技術スタック

- **Gateway**: Rust (tokio, axum, chacha20poly1305, x25519-dalek)
- **Agent**: Python (websockets, openai/anthropic SDK, MCP, loguru)
- **対応 LLM**: Claude / GPT-4o / DeepSeek / Ollama（ローカル）
- **音声**: GPT-SoVITS (TTS) + Faster-Whisper (ASR)
- **デスクトップ**: Electron + React + Live2D Cubism SDK
- **設定**: TOML + 環境変数。コード変更なしでチャンネルやモデルを切り替え可能

## クイックスタート

```bash
git clone https://github.com/ArcadiaFrame/koclaw.git && cd koclaw

# Gateway をビルド
cargo build --release

# Agent 依存関係をインストール
cd agent && uv sync && cd ..

# 設定
cp config.example.toml config.toml
cp persona.yaml.example persona.yaml
# config.toml と .env を編集して API Key と Bot Token を設定

# 起動
cd agent && uv run python -m koclaw_agent &  # Agent
cargo run --release                            # Gateway
```

詳細なデプロイガイドはプロジェクト内の `docs/deployment-linux.md` を参照してください。

## 今後の予定

- Web 埋め込み SDK (`@koclaw/web-widget`) — 任意のサイトに AI チャットを一行で埋め込み
- 真のゼロ知識 E2E 暗号化 — Gateway は純粋なリレーとして機能
- RAG ナレッジベース統合
- マルチエージェント協調
- Double Ratchet 前方秘匿性

## ライセンス

MIT License

---

# English

## What is this

Koclaw is an AI Agent framework designed for personal deployment. The idea is straightforward: **one AI persona, multiple platforms, unified memory, end-to-end encryption**.

You can talk to the same AI assistant on Telegram, QQ, and Discord, or interact with it face-to-face through a Live2D avatar on your desktop. No matter which channel you use, it knows who you are, remembers what you talked about, and maintains a consistent personality. And even if the server gets compromised, your messages stay private — everything is end-to-end encrypted.

The name comes from **Ko**koron + **claw** — Kokoron is the default AI persona, and claw places it within the broader AI agent ecosystem.

## Why another framework

There are already several great open-source projects in this space:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** delivers an excellent local LLM + Live2D VTuber experience with voice interruption and fully offline operation. But it's primarily desktop-focused and doesn't integrate with messaging platforms.
- **[OpenClaw](https://github.com/openclaw/openclaw)** is one of the most comprehensive personal AI assistant frameworks, supporting 20+ channels with a rich ecosystem. But it's pure TypeScript with no end-to-end encryption or Live2D character experience.
- **[ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw)** pushes the agent runtime to extreme lightness (3.4MB binary, 10ms cold start) in pure Rust. But it focuses on runtime infrastructure and doesn't include LLM orchestration or voice pipelines.

Koclaw occupies a different niche:

| | Open-LLM-VTuber | OpenClaw | ZeroClaw | **Koclaw** |
|---|---|---|---|---|
| Core language | Python | TypeScript | Rust | **Rust + Python** |
| E2E encryption | — | — | — | **X25519 + ChaCha20** |
| Live2D character | Desktop | — | — | **Multi-platform** |
| SNS integration | — | 20+ channels | Channel plugins | **Telegram/QQ/Discord/Web** |
| Voice pipeline | ASR + TTS | TTS | — | **ASR + TTS (GPT-SoVITS)** |
| Memory safety | Runtime | Runtime | Compile-time | **Compile-time (Gateway)** |
| MCP tools | Supported | — | Supported | **Supported (27+ tools)** |

In short, Koclaw's core proposition: **Rust for security + Python for ML ecosystem + end-to-end encryption + Live2D character embodiment + unified cross-platform identity**.

## Current status

Five development phases are complete:

- **Phase 1-2**: Gateway core, channel implementations (Telegram/QQ/Discord), X25519 key exchange, encrypted storage, permission system, sandbox
- **Phase 3**: Integration with [AIKokoron](https://github.com/shinyo-io/AIKokoron) agent logic, unified persona system (`persona.yaml`), conversation memory, expression system, GPT-SoVITS TTS, Whisper ASR, WebSocket channel
- **Phase 4**: MCP tool system (27 tools), ClawHub skill ecosystem integration, permission-gated tool access
- **Phase 5**: Reminders, cron scheduler, heartbeat monitoring, proactive message delivery

> **About AIKokoron**: Koclaw's Python Agent layer reuses significant code from [AIKokoron](https://github.com/shinyo-io/AIKokoron). AIKokoron is an independent project under active development that implements LLM orchestration, voice pipelines, and a Live2D frontend. It hasn't been publicly released yet, but its core capabilities are already integrated into Koclaw.

**Test coverage**: 124 tests (66 Rust + 58 Python), all passing.

## Tech stack

- **Gateway**: Rust (tokio, axum, chacha20poly1305, x25519-dalek)
- **Agent**: Python (websockets, openai/anthropic SDK, MCP, loguru)
- **Supported LLMs**: Claude / GPT-4o / DeepSeek / Ollama (local)
- **Voice**: GPT-SoVITS (TTS) + Faster-Whisper (ASR)
- **Desktop**: Electron + React + Live2D Cubism SDK
- **Config**: TOML + env vars — switch channels and models without code changes

## Quick start

```bash
git clone https://github.com/ArcadiaFrame/koclaw.git && cd koclaw

# Build the Gateway
cargo build --release

# Install Agent dependencies
cd agent && uv sync && cd ..

# Configure
cp config.example.toml config.toml
cp persona.yaml.example persona.yaml
# Edit config.toml and .env to set API keys and bot tokens

# Run
cd agent && uv run python -m koclaw_agent &  # Agent
cargo run --release                            # Gateway
```

See `docs/deployment-linux.md` for detailed deployment instructions.

## Roadmap

- Web embedding SDK (`@koclaw/web-widget`) — drop AI chat into any website with one line
- True zero-knowledge E2E encryption — Gateway as a pure relay
- RAG knowledge base integration
- Multi-agent orchestration
- Double Ratchet forward secrecy

## License

MIT License
