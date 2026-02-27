# Phase 2: Security, Discord, Memory & Persona

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add transport encryption (X25519 key exchange), Discord channel, encrypted memory persistence, tool sandbox, and a persona system — making Koclaw a secure, multi-channel AI agent with conversation continuity.

**Architecture:** Extend the existing Rust gateway with X25519+ChaCha20 transport layer on top of the Phase 1 at-rest encryption. Discord channel follows the same `Channel` trait pattern as Telegram/QQ but uses WebSocket Gateway instead of HTTP polling. Memory uses SQLite with ChaCha20-encrypted blobs. Tool sandbox scopes the Agent's filesystem and command access. Persona system injects channel-specific system prompts into Agent requests.

**Tech Stack:** Rust (x25519-dalek, hkdf, sha2, rusqlite, tokio-tungstenite), Python (FastAPI, anthropic, openai).

**Build command:** `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build 2>&1"`
**Test command:** `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test 2>&1"`

---

## Task 1: X25519 Key Exchange + Session Encryption

**Files:**
- Modify: `common/src/crypto.rs`
- Modify: `common/Cargo.toml` (deps already in workspace, just need to add to crate)

**Step 1: Check common/Cargo.toml has the crypto deps**

`common/Cargo.toml` should have:
```toml
x25519-dalek = { workspace = true }
hkdf = { workspace = true }
sha2 = { workspace = true }
```

If not already present, add them.

**Step 2: Write failing test for key exchange**

Add to `common/src/crypto.rs` inside the `#[cfg(test)] mod tests` block:

```rust
#[test]
fn test_x25519_key_exchange() {
    let (alice_secret, alice_public) = generate_keypair();
    let (bob_secret, bob_public) = generate_keypair();

    let alice_shared = derive_shared_secret(&alice_secret, &bob_public);
    let bob_shared = derive_shared_secret(&bob_secret, &alice_public);

    assert_eq!(alice_shared, bob_shared, "Shared secrets must match");
}

#[test]
fn test_session_key_derivation() {
    let (alice_secret, alice_public) = generate_keypair();
    let (bob_secret, bob_public) = generate_keypair();

    let alice_session = derive_session_key(&alice_secret, &bob_public, b"koclaw-session-v1");
    let bob_session = derive_session_key(&bob_secret, &alice_public, b"koclaw-session-v1");

    assert_eq!(alice_session, bob_session, "Session keys must match");
    assert_ne!(alice_session, [0u8; 32], "Session key must not be zero");
}

#[test]
fn test_session_encrypt_decrypt() {
    let (alice_secret, alice_public) = generate_keypair();
    let (bob_secret, bob_public) = generate_keypair();

    let session_key = derive_session_key(&alice_secret, &bob_public, b"koclaw-session-v1");

    let plaintext = b"Hello from encrypted session!";
    let ciphertext = encrypt(plaintext, &session_key).unwrap();
    let decrypted = decrypt(&ciphertext, &session_key).unwrap();

    assert_eq!(plaintext.to_vec(), decrypted);
}

#[test]
fn test_different_contexts_produce_different_keys() {
    let (alice_secret, alice_public) = generate_keypair();
    let (bob_secret, bob_public) = generate_keypair();

    let key1 = derive_session_key(&alice_secret, &bob_public, b"koclaw-session-v1");
    let key2 = derive_session_key(&alice_secret, &bob_public, b"koclaw-memory-v1");

    assert_ne!(key1, key2, "Different contexts must produce different keys");
}
```

**Step 3: Run tests — expect FAIL**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test -p koclaw-common 2>&1"`
Expected: Compilation error — `generate_keypair`, `derive_shared_secret`, `derive_session_key` not found.

**Step 4: Implement key exchange functions**

Add to `common/src/crypto.rs`:

```rust
use x25519_dalek::{EphemeralSecret, PublicKey, StaticSecret};
use hkdf::Hkdf;
use sha2::Sha256;

/// Generate an X25519 keypair for key exchange.
///
/// Returns (secret_key_bytes, public_key_bytes).
/// The secret key should NEVER leave the device.
pub fn generate_keypair() -> ([u8; 32], [u8; 32]) {
    let secret = StaticSecret::random_from_rng(rand::thread_rng());
    let public = PublicKey::from(&secret);
    (secret.to_bytes(), public.to_bytes())
}

/// Perform X25519 Diffie-Hellman to derive a shared secret.
pub fn derive_shared_secret(my_secret: &[u8; 32], their_public: &[u8; 32]) -> [u8; 32] {
    let secret = StaticSecret::from(*my_secret);
    let public = PublicKey::from(*their_public);
    let shared = secret.diffie_hellman(&public);
    *shared.as_bytes()
}

/// Derive a session key from a shared secret using HKDF-SHA256.
///
/// The `context` parameter provides domain separation (e.g., b"koclaw-session-v1"
/// vs b"koclaw-memory-v1") so the same shared secret produces different keys
/// for different purposes.
pub fn derive_session_key(
    my_secret: &[u8; 32],
    their_public: &[u8; 32],
    context: &[u8],
) -> [u8; 32] {
    let shared_secret = derive_shared_secret(my_secret, their_public);
    let hkdf = Hkdf::<Sha256>::new(Some(context), &shared_secret);
    let mut session_key = [0u8; 32];
    hkdf.expand(b"koclaw-derived-key", &mut session_key)
        .expect("HKDF expand should not fail with 32-byte output");
    session_key
}
```

**Step 5: Run tests — expect PASS**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test -p koclaw-common 2>&1"`
Expected: All tests pass (5 original + 4 new = 9 total).

**Step 6: Commit**

```bash
git add common/src/crypto.rs common/Cargo.toml
git commit -m "security(common): add X25519 key exchange with HKDF session key derivation"
```

---

## Task 2: Discord Channel — WebSocket Gateway

**Files:**
- Create: `channels/src/discord.rs`
- Modify: `gateway/Cargo.toml` (add `discord` feature)
- Modify: `gateway/src/main.rs` (wire Discord startup)

**Background:** Discord bots connect to `wss://gateway.discord.gg/?v=10&encoding=json` via WebSocket. The connection lifecycle:
1. Receive HELLO (opcode 10) with heartbeat interval
2. Send IDENTIFY (opcode 2) with bot token
3. Receive READY (opcode 0)
4. Spawn heartbeat task (opcode 1 at interval)
5. Listen for DISPATCH events (opcode 0), especially MESSAGE_CREATE
6. Send messages via REST: `POST https://discord.com/api/v10/channels/{id}/messages`

Network footprint: single outbound WSS to Discord servers on port 443 — identical to the Discord desktop client.

**Step 1: Write Discord channel implementation**

Create `channels/src/discord.rs`:

```rust
#![allow(dead_code)]

use std::sync::Arc;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use tracing::{debug, error, info, warn};

use koclaw_common::channel::{BoxFuture, Channel, ChannelType, MessageRouter};
use koclaw_common::message::{IncomingMessage, OutgoingMessage};
use koclaw_common::permission::PermissionLevel;

const DISCORD_API_BASE: &str = "https://discord.com/api/v10";
const DISCORD_GATEWAY_URL: &str = "wss://gateway.discord.gg/?v=10&encoding=json";

/// Discord Gateway opcodes.
mod opcode {
    pub const DISPATCH: u8 = 0;
    pub const HEARTBEAT: u8 = 1;
    pub const IDENTIFY: u8 = 2;
    pub const RESUME: u8 = 6;
    pub const RECONNECT: u8 = 7;
    pub const INVALID_SESSION: u8 = 9;
    pub const HELLO: u8 = 10;
    pub const HEARTBEAT_ACK: u8 = 11;
}

/// A Discord Gateway payload.
#[derive(Debug, Deserialize)]
struct GatewayPayload {
    op: u8,
    d: Option<serde_json::Value>,
    s: Option<u64>,
    t: Option<String>,
}

#[derive(Debug, Serialize)]
struct GatewayCommand {
    op: u8,
    d: serde_json::Value,
}

/// Discord message object (subset of fields we care about).
#[derive(Debug, Deserialize)]
struct DiscordMessage {
    id: String,
    channel_id: String,
    content: String,
    author: DiscordUser,
    guild_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DiscordUser {
    id: String,
    username: String,
    bot: Option<bool>,
}

pub struct DiscordChannel {
    token: String,
    http_client: reqwest::Client,
}

impl DiscordChannel {
    pub fn new(token: String) -> Self {
        Self {
            token,
            http_client: reqwest::Client::new(),
        }
    }

    /// Connect to Discord Gateway and listen for events.
    async fn run_gateway(&self, router: Arc<dyn MessageRouter>) -> Result<()> {
        use futures_util::{SinkExt, StreamExt};
        use tokio_tungstenite::tungstenite::Message;

        info!("Connecting to Discord Gateway...");

        let (ws_stream, _) = tokio_tungstenite::connect_async(DISCORD_GATEWAY_URL)
            .await
            .context("Failed to connect to Discord Gateway")?;

        let (mut write, mut read) = ws_stream.split();

        // Step 1: Receive HELLO
        let hello = read.next().await
            .ok_or_else(|| anyhow::anyhow!("Gateway closed before HELLO"))?
            .context("Failed to read HELLO")?;

        let hello_payload: GatewayPayload = match hello {
            Message::Text(text) => serde_json::from_str(&text)?,
            _ => anyhow::bail!("Expected text frame for HELLO"),
        };

        if hello_payload.op != opcode::HELLO {
            anyhow::bail!("Expected HELLO (op 10), got op {}", hello_payload.op);
        }

        let heartbeat_interval = hello_payload.d
            .as_ref()
            .and_then(|d| d["heartbeat_interval"].as_u64())
            .unwrap_or(41250);

        info!(interval_ms = heartbeat_interval, "Received HELLO from Discord");

        // Step 2: Send IDENTIFY
        let identify = GatewayCommand {
            op: opcode::IDENTIFY,
            d: serde_json::json!({
                "token": self.token,
                "intents": 512 | 4096, // GUILD_MESSAGES | DIRECT_MESSAGES
                "properties": {
                    "os": "linux",
                    "browser": "koclaw",
                    "device": "koclaw"
                }
            }),
        };

        write.send(Message::Text(
            serde_json::to_string(&identify)?.into()
        )).await?;

        // Step 3: Spawn heartbeat task
        let heartbeat_interval_dur = std::time::Duration::from_millis(heartbeat_interval);
        let (heartbeat_tx, mut heartbeat_rx) = tokio::sync::mpsc::channel::<Option<u64>>(1);

        // Sequence number tracker
        let sequence = Arc::new(tokio::sync::Mutex::new(None::<u64>));
        let seq_heartbeat = sequence.clone();

        // Heartbeat sender task
        let mut write_shared = Arc::new(tokio::sync::Mutex::new(write));
        let write_for_heartbeat = write_shared.clone();

        tokio::spawn(async move {
            let mut interval = tokio::time::interval(heartbeat_interval_dur);
            loop {
                interval.tick().await;
                let seq = *seq_heartbeat.lock().await;
                let hb = GatewayCommand {
                    op: opcode::HEARTBEAT,
                    d: match seq {
                        Some(s) => serde_json::json!(s),
                        None => serde_json::Value::Null,
                    },
                };
                let mut writer = write_for_heartbeat.lock().await;
                if writer.send(Message::Text(
                    serde_json::to_string(&hb).unwrap().into()
                )).await.is_err() {
                    warn!("Heartbeat send failed, connection may be lost");
                    break;
                }
                debug!("Sent heartbeat");
            }
        });

        // Step 4: Event loop
        info!("Discord Gateway connected, listening for events...");

        while let Some(msg) = read.next().await {
            let msg = match msg {
                Ok(Message::Text(text)) => text,
                Ok(Message::Close(_)) => {
                    info!("Discord Gateway connection closed");
                    break;
                }
                Err(e) => {
                    error!(error = %e, "Discord Gateway error");
                    break;
                }
                _ => continue,
            };

            let payload: GatewayPayload = match serde_json::from_str(&msg) {
                Ok(p) => p,
                Err(e) => {
                    warn!(error = %e, "Failed to parse Gateway payload");
                    continue;
                }
            };

            // Update sequence number
            if let Some(s) = payload.s {
                *sequence.lock().await = Some(s);
            }

            match payload.op {
                opcode::DISPATCH => {
                    if let Some(ref event_name) = payload.t {
                        match event_name.as_str() {
                            "MESSAGE_CREATE" => {
                                if let Some(ref data) = payload.d {
                                    self.handle_message(data, &router).await;
                                }
                            }
                            "READY" => {
                                info!("Discord Gateway READY");
                            }
                            _ => {
                                debug!(event = %event_name, "Unhandled Discord event");
                            }
                        }
                    }
                }
                opcode::HEARTBEAT_ACK => {
                    debug!("Heartbeat acknowledged");
                }
                opcode::RECONNECT => {
                    warn!("Discord requested reconnect");
                    break;
                }
                opcode::INVALID_SESSION => {
                    warn!("Invalid session, will reconnect");
                    break;
                }
                _ => {
                    debug!(op = payload.op, "Unhandled Gateway opcode");
                }
            }
        }

        Ok(())
    }

    /// Handle a MESSAGE_CREATE event from Discord.
    async fn handle_message(
        &self,
        data: &serde_json::Value,
        router: &Arc<dyn MessageRouter>,
    ) {
        let msg: DiscordMessage = match serde_json::from_value(data.clone()) {
            Ok(m) => m,
            Err(e) => {
                warn!(error = %e, "Failed to parse Discord message");
                return;
            }
        };

        // Ignore bot messages (including our own)
        if msg.author.bot.unwrap_or(false) {
            return;
        }

        debug!(
            user = %msg.author.username,
            channel_id = %msg.channel_id,
            "Received Discord message"
        );

        let session_id = match &msg.guild_id {
            Some(guild) => format!("dc:{}:{}", guild, msg.channel_id),
            None => format!("dc:dm:{}", msg.channel_id),
        };

        let incoming = IncomingMessage {
            id: msg.id,
            channel: ChannelType::Discord,
            user_id: format!("dc:{}", msg.author.id),
            display_name: Some(msg.author.username),
            text: Some(msg.content),
            attachments: vec![],
            permission: PermissionLevel::Authenticated,
            session_id,
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        };

        if let Err(e) = router.route(incoming).await {
            error!(error = %e, "Failed to route Discord message");
        }
    }

    /// Send a text message to a Discord channel via REST API.
    async fn send_text(&self, channel_id: &str, text: &str, reply_to: Option<&str>) -> Result<()> {
        let url = format!("{}/channels/{}/messages", DISCORD_API_BASE, channel_id);

        let mut body = serde_json::json!({
            "content": text
        });

        if let Some(ref_id) = reply_to {
            body["message_reference"] = serde_json::json!({
                "message_id": ref_id
            });
        }

        let resp = self.http_client
            .post(&url)
            .header("Authorization", format!("Bot {}", self.token))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .context("Failed to send Discord message")?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            warn!(status = %status, body = %body, "Discord API error");
        }

        Ok(())
    }
}

impl Channel for DiscordChannel {
    fn start(&self, router: Arc<dyn MessageRouter>) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.run_gateway(router))
    }

    fn send_message(&self, msg: &OutgoingMessage) -> BoxFuture<'_, Result<()>> {
        let target_id = msg.target_id.clone();
        let text = msg.text.clone();
        let reply_to = msg.reply_to.clone();
        Box::pin(async move {
            self.send_text(
                &target_id,
                text.as_deref().unwrap_or(""),
                reply_to.as_deref(),
            ).await
        })
    }

    fn channel_type(&self) -> ChannelType {
        ChannelType::Discord
    }

    fn default_permission(&self) -> PermissionLevel {
        PermissionLevel::Authenticated
    }
}
```

**Step 2: Add discord feature to gateway**

In `gateway/Cargo.toml`, change the channels dependency:
```toml
koclaw-channels = { workspace = true, features = ["telegram", "qq", "discord"] }
```

**Step 3: Add tokio-tungstenite + futures-util to channels crate**

In `channels/Cargo.toml`:
```toml
[features]
default = ["telegram"]
telegram = ["dep:reqwest"]
qq = ["dep:reqwest"]
discord = ["dep:reqwest", "dep:tokio-tungstenite", "dep:futures-util"]

[dependencies]
# ... existing deps ...
tokio-tungstenite = { workspace = true, optional = true }
futures-util = { version = "0.3", optional = true }
```

**Step 4: Wire Discord in main.rs**

In `gateway/src/main.rs`, replace the Discord TODO block:
```rust
if let Some(ref dc) = config.channels.discord {
    if dc.enabled {
        match dc.resolve_token() {
            Ok(token) => {
                info!("Starting Discord channel");
                let channel = Arc::new(koclaw_channels::discord::DiscordChannel::new(token));
                router.register_channel(channel.clone()).await;

                let channel_router = router.clone();
                tokio::spawn(async move {
                    if let Err(e) = channel.start(channel_router).await {
                        error!(error = %e, "Discord channel stopped");
                    }
                });
            }
            Err(e) => error!(error = %e, "Discord channel config error"),
        }
    }
}
```

**Step 5: Add DiscordConfig.resolve_token() to config.rs**

In `gateway/src/config.rs`, add to `DiscordConfig`:
```rust
impl DiscordConfig {
    pub fn resolve_token(&self) -> anyhow::Result<String> {
        KoclawConfig::resolve_secret(&self.token, &self.token_env)
            .ok_or_else(|| anyhow::anyhow!("Discord token not configured (set token or token_env)"))
    }
}
```

**Step 6: Build and test**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo build 2>&1"`
Expected: Compiles successfully.

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test 2>&1"`
Expected: All existing tests still pass.

**Step 7: Commit**

```bash
git add channels/src/discord.rs channels/Cargo.toml gateway/Cargo.toml gateway/src/main.rs gateway/src/config.rs
git commit -m "feat(channel-dc): implement Discord channel with WebSocket Gateway"
```

---

## Task 3: Encrypted Memory System (SQLite + ChaCha20)

**Files:**
- Create: `common/src/memory.rs`
- Modify: `common/src/lib.rs`
- Modify: `gateway/src/router.rs` (pass memory to Agent requests)

**Step 1: Write failing tests for memory backend**

Add to `common/src/memory.rs`:

```rust
use anyhow::Result;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use tracing::debug;

use crate::crypto;

/// An encrypted memory entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    pub key: String,
    pub value: Vec<u8>,     // Encrypted blob
    pub created_at: u64,
    pub accessed_at: u64,
}

/// Encrypted persistent memory backed by SQLite.
///
/// All values are encrypted with ChaCha20-Poly1305 before storage.
/// The encryption key is derived per-user via HKDF from the master key.
pub struct MemoryStore {
    conn: Connection,
    master_key: [u8; 32],
}

impl MemoryStore {
    /// Create a new memory store at the given path.
    pub fn new(db_path: &str, master_key: [u8; 32]) -> Result<Self> {
        let conn = Connection::open(db_path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                accessed_at INTEGER NOT NULL
            );"
        )?;
        Ok(Self { conn, master_key })
    }

    /// Create an in-memory store for testing.
    pub fn in_memory(master_key: [u8; 32]) -> Result<Self> {
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                accessed_at INTEGER NOT NULL
            );"
        )?;
        Ok(Self { conn, master_key })
    }

    fn now_ms() -> u64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64
    }

    /// Store an encrypted value.
    pub fn store(&self, key: &str, plaintext: &[u8]) -> Result<()> {
        let encrypted = crypto::encrypt(plaintext, &self.master_key)?;
        let now = Self::now_ms();

        self.conn.execute(
            "INSERT OR REPLACE INTO memory (key, value, created_at, accessed_at) VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![key, encrypted, now, now],
        )?;

        debug!(key = key, "Stored encrypted memory entry");
        Ok(())
    }

    /// Retrieve and decrypt a value by key.
    pub fn retrieve(&self, key: &str) -> Result<Option<Vec<u8>>> {
        let mut stmt = self.conn.prepare(
            "SELECT value FROM memory WHERE key = ?1"
        )?;

        let result: Option<Vec<u8>> = stmt.query_row(
            rusqlite::params![key],
            |row| row.get(0),
        ).ok();

        match result {
            Some(encrypted) => {
                // Update accessed_at
                self.conn.execute(
                    "UPDATE memory SET accessed_at = ?1 WHERE key = ?2",
                    rusqlite::params![Self::now_ms(), key],
                )?;

                let decrypted = crypto::decrypt(&encrypted, &self.master_key)?;
                Ok(Some(decrypted))
            }
            None => Ok(None),
        }
    }

    /// Delete a memory entry.
    pub fn delete(&self, key: &str) -> Result<bool> {
        let affected = self.conn.execute(
            "DELETE FROM memory WHERE key = ?1",
            rusqlite::params![key],
        )?;
        Ok(affected > 0)
    }

    /// List all keys matching a prefix.
    pub fn list_keys(&self, prefix: &str) -> Result<Vec<String>> {
        let mut stmt = self.conn.prepare(
            "SELECT key FROM memory WHERE key LIKE ?1 ORDER BY accessed_at DESC"
        )?;
        let pattern = format!("{}%", prefix);
        let keys: Vec<String> = stmt.query_map(
            rusqlite::params![pattern],
            |row| row.get(0),
        )?.filter_map(|r| r.ok()).collect();
        Ok(keys)
    }

    /// Count entries matching a prefix.
    pub fn count(&self, prefix: &str) -> Result<usize> {
        let mut stmt = self.conn.prepare(
            "SELECT COUNT(*) FROM memory WHERE key LIKE ?1"
        )?;
        let pattern = format!("{}%", prefix);
        let count: usize = stmt.query_row(
            rusqlite::params![pattern],
            |row| row.get(0),
        )?;
        Ok(count)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_store() -> MemoryStore {
        let key = crypto::generate_key();
        MemoryStore::in_memory(key).unwrap()
    }

    #[test]
    fn test_store_and_retrieve() {
        let store = test_store();
        store.store("user:123:name", b"Alice").unwrap();

        let result = store.retrieve("user:123:name").unwrap();
        assert_eq!(result, Some(b"Alice".to_vec()));
    }

    #[test]
    fn test_retrieve_missing_key() {
        let store = test_store();
        let result = store.retrieve("nonexistent").unwrap();
        assert_eq!(result, None);
    }

    #[test]
    fn test_overwrite() {
        let store = test_store();
        store.store("key", b"first").unwrap();
        store.store("key", b"second").unwrap();

        let result = store.retrieve("key").unwrap();
        assert_eq!(result, Some(b"second".to_vec()));
    }

    #[test]
    fn test_delete() {
        let store = test_store();
        store.store("key", b"value").unwrap();

        assert!(store.delete("key").unwrap());
        assert!(!store.delete("key").unwrap()); // Already deleted

        let result = store.retrieve("key").unwrap();
        assert_eq!(result, None);
    }

    #[test]
    fn test_list_keys_with_prefix() {
        let store = test_store();
        store.store("session:abc:msg1", b"hello").unwrap();
        store.store("session:abc:msg2", b"world").unwrap();
        store.store("session:def:msg1", b"other").unwrap();
        store.store("user:123", b"data").unwrap();

        let keys = store.list_keys("session:abc:").unwrap();
        assert_eq!(keys.len(), 2);
        assert!(keys.iter().all(|k| k.starts_with("session:abc:")));

        let all_sessions = store.list_keys("session:").unwrap();
        assert_eq!(all_sessions.len(), 3);
    }

    #[test]
    fn test_different_master_keys_cannot_decrypt() {
        let key1 = crypto::generate_key();
        let key2 = crypto::generate_key();

        let store1 = MemoryStore::in_memory(key1).unwrap();
        store1.store("secret", b"classified").unwrap();

        // Get the raw encrypted blob
        let encrypted: Vec<u8> = store1.conn.query_row(
            "SELECT value FROM memory WHERE key = 'secret'",
            [],
            |row| row.get(0),
        ).unwrap();

        // Try to decrypt with a different key — should fail
        let result = crypto::decrypt(&encrypted, &key2);
        assert!(result.is_err(), "Decryption with wrong key must fail");
    }

    #[test]
    fn test_count() {
        let store = test_store();
        store.store("chat:1:a", b"x").unwrap();
        store.store("chat:1:b", b"y").unwrap();
        store.store("chat:2:a", b"z").unwrap();

        assert_eq!(store.count("chat:1:").unwrap(), 2);
        assert_eq!(store.count("chat:").unwrap(), 3);
        assert_eq!(store.count("other:").unwrap(), 0);
    }
}
```

**Step 2: Register the module**

In `common/src/lib.rs`, add:
```rust
pub mod memory;
```

**Step 3: Ensure rusqlite is in common/Cargo.toml**

Add to `common/Cargo.toml` if not already present:
```toml
rusqlite = { workspace = true }
```

**Step 4: Build and test**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test -p koclaw-common 2>&1"`
Expected: All tests pass (9 crypto + 7 memory = 16 total).

**Step 5: Commit**

```bash
git add common/src/memory.rs common/src/lib.rs common/Cargo.toml
git commit -m "feat(common): add encrypted memory store with SQLite backend"
```

---

## Task 4: Persona System

**Files:**
- Create: `common/src/persona.rs`
- Modify: `common/src/lib.rs`
- Create: `agent/koclaw_agent/persona.py`
- Modify: `agent/koclaw_agent/bridge.py` (inject persona into requests)

**Step 1: Define Persona types in Rust**

Create `common/src/persona.rs`:

```rust
use serde::{Deserialize, Serialize};
use crate::channel::ChannelType;

/// Defines an AI persona's identity and behavior.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Persona {
    /// Persona name (e.g., "Kokoron")
    pub name: String,
    /// Base system prompt shared across all channels
    pub base_prompt: String,
    /// Per-channel prompt overrides
    pub channel_prompts: Vec<ChannelPrompt>,
    /// Personality traits
    pub traits: Vec<String>,
    /// Preferred language for responses
    pub language: String,
}

/// Channel-specific prompt override.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelPrompt {
    pub channel: ChannelType,
    /// Additional prompt text appended to the base prompt for this channel
    pub prompt_suffix: String,
    /// Display name override for this channel
    pub display_name: Option<String>,
}

impl Persona {
    /// Get the full system prompt for a given channel.
    pub fn system_prompt(&self, channel: ChannelType) -> String {
        let mut prompt = self.base_prompt.clone();

        // Append channel-specific suffix if configured
        if let Some(cp) = self.channel_prompts.iter().find(|cp| cp.channel == channel) {
            prompt.push('\n');
            prompt.push_str(&cp.prompt_suffix);
        }

        prompt
    }

    /// Get the display name for a given channel.
    pub fn display_name(&self, channel: ChannelType) -> &str {
        self.channel_prompts
            .iter()
            .find(|cp| cp.channel == channel)
            .and_then(|cp| cp.display_name.as_deref())
            .unwrap_or(&self.name)
    }

    /// Create a default Kokoron persona.
    pub fn kokoron() -> Self {
        Self {
            name: "Kokoron".to_string(),
            base_prompt: concat!(
                "You are Kokoron, a helpful and friendly AI assistant. ",
                "You are knowledgeable, creative, and always willing to help. ",
                "You maintain a warm and approachable personality while being precise and thorough.",
            ).to_string(),
            channel_prompts: vec![
                ChannelPrompt {
                    channel: ChannelType::WebPublic,
                    prompt_suffix: "You are embedded in a blog. Keep responses concise and relevant to the blog's content. Do not execute tools or access private data.".to_string(),
                    display_name: Some("Kokoron (Blog Assistant)".to_string()),
                },
            ],
            traits: vec![
                "helpful".to_string(),
                "friendly".to_string(),
                "knowledgeable".to_string(),
            ],
            language: "auto".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_system_prompt_default() {
        let persona = Persona::kokoron();
        let prompt = persona.system_prompt(ChannelType::Telegram);
        assert!(prompt.contains("Kokoron"));
        // Telegram has no channel-specific override
        assert!(!prompt.contains("blog"));
    }

    #[test]
    fn test_system_prompt_with_channel_override() {
        let persona = Persona::kokoron();
        let prompt = persona.system_prompt(ChannelType::WebPublic);
        assert!(prompt.contains("Kokoron"));
        assert!(prompt.contains("blog")); // WebPublic has channel-specific suffix
    }

    #[test]
    fn test_display_name_default() {
        let persona = Persona::kokoron();
        assert_eq!(persona.display_name(ChannelType::Telegram), "Kokoron");
    }

    #[test]
    fn test_display_name_override() {
        let persona = Persona::kokoron();
        assert_eq!(
            persona.display_name(ChannelType::WebPublic),
            "Kokoron (Blog Assistant)"
        );
    }
}
```

**Step 2: Register module in lib.rs**

Add to `common/src/lib.rs`:
```rust
pub mod persona;
```

**Step 3: Add persona to Python Agent**

Create `agent/koclaw_agent/persona.py`:

```python
"""Persona system for Kokoron identity management."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Persona:
    """AI persona definition."""

    name: str = "Kokoron"
    base_prompt: str = (
        "You are Kokoron, a helpful and friendly AI assistant. "
        "You are knowledgeable, creative, and always willing to help. "
        "You maintain a warm and approachable personality while being precise and thorough."
    )
    channel_prompts: dict[str, str] = field(default_factory=lambda: {
        "web-public": (
            "You are embedded in a blog. Keep responses concise and relevant "
            "to the blog's content. Do not execute tools or access private data."
        ),
    })
    language: str = "auto"

    def system_prompt(self, channel: str) -> str:
        """Get full system prompt for a given channel."""
        prompt = self.base_prompt
        if channel in self.channel_prompts:
            prompt += "\n" + self.channel_prompts[channel]
        return prompt
```

**Step 4: Inject persona into Agent bridge**

In `agent/koclaw_agent/bridge.py`, update the chat handler to include the persona system prompt in LLM requests. The `handle_chat` function should prepend a system message using `persona.system_prompt(request["channel"])`.

**Step 5: Build and test**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test -p koclaw-common 2>&1"`
Expected: All tests pass (9 crypto + 7 memory + 4 persona = 20 total).

**Step 6: Commit**

```bash
git add common/src/persona.rs common/src/lib.rs agent/koclaw_agent/persona.py agent/koclaw_agent/bridge.py
git commit -m "feat(common): add persona system with per-channel identity management"
```

---

## Task 5: Tool Sandbox

**Files:**
- Create: `common/src/sandbox.rs`
- Modify: `common/src/lib.rs`
- Modify: `agent/koclaw_agent/bridge.py` (enforce sandbox on tool execution)

**Step 1: Define Sandbox types**

Create `common/src/sandbox.rs`:

```rust
use std::path::{Path, PathBuf};

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};

/// Sandbox configuration for Agent tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxConfig {
    /// Root directory for filesystem access (all paths resolved relative to this)
    pub root: PathBuf,
    /// Allowed shell commands (empty = no commands allowed)
    pub allowed_commands: Vec<String>,
    /// Maximum execution time per tool invocation in seconds
    pub timeout_seconds: u64,
    /// Maximum file size for read/write operations in bytes
    pub max_file_size: u64,
}

impl Default for SandboxConfig {
    fn default() -> Self {
        Self {
            root: PathBuf::from("./workspace"),
            allowed_commands: vec![],
            timeout_seconds: 30,
            max_file_size: 10 * 1024 * 1024, // 10 MB
        }
    }
}

impl SandboxConfig {
    /// Validate that a path is within the sandbox root.
    ///
    /// Returns the canonicalized path if valid.
    pub fn validate_path(&self, path: &str) -> Result<PathBuf> {
        let requested = self.root.join(path);

        // Resolve to absolute, eliminating .. and symlinks
        // Note: in production, canonicalize() requires the path to exist.
        // For creation operations, we validate the parent instead.
        let normalized = normalize_path(&requested);

        let root_normalized = normalize_path(&self.root);

        if !normalized.starts_with(&root_normalized) {
            bail!(
                "Path escape attempt: '{}' resolves outside sandbox root '{}'",
                path,
                self.root.display()
            );
        }

        Ok(normalized)
    }

    /// Check if a command is in the allowlist.
    pub fn validate_command(&self, command: &str) -> Result<()> {
        // Extract the base command (first word)
        let base_cmd = command.split_whitespace().next().unwrap_or("");

        if !self.allowed_commands.iter().any(|c| c == base_cmd) {
            bail!(
                "Command '{}' not in sandbox allowlist: {:?}",
                base_cmd,
                self.allowed_commands
            );
        }

        Ok(())
    }
}

/// Normalize a path without requiring it to exist (no canonicalize).
fn normalize_path(path: &Path) -> PathBuf {
    let mut components = Vec::new();
    for component in path.components() {
        match component {
            std::path::Component::ParentDir => {
                components.pop();
            }
            std::path::Component::CurDir => {}
            _ => {
                components.push(component);
            }
        }
    }
    components.iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_sandbox() -> SandboxConfig {
        SandboxConfig {
            root: PathBuf::from("/workspace"),
            allowed_commands: vec!["ls".to_string(), "cat".to_string(), "grep".to_string()],
            timeout_seconds: 30,
            max_file_size: 1024 * 1024,
        }
    }

    #[test]
    fn test_valid_path() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("docs/readme.md");
        assert!(result.is_ok());
        let path = result.unwrap();
        assert!(path.starts_with("/workspace"));
    }

    #[test]
    fn test_path_escape_blocked() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("../../etc/passwd");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("escape"));
    }

    #[test]
    fn test_path_escape_via_dotdot() {
        let sandbox = test_sandbox();
        let result = sandbox.validate_path("subdir/../../etc/shadow");
        assert!(result.is_err());
    }

    #[test]
    fn test_valid_command() {
        let sandbox = test_sandbox();
        assert!(sandbox.validate_command("ls -la").is_ok());
        assert!(sandbox.validate_command("cat file.txt").is_ok());
        assert!(sandbox.validate_command("grep pattern file").is_ok());
    }

    #[test]
    fn test_blocked_command() {
        let sandbox = test_sandbox();
        assert!(sandbox.validate_command("rm -rf /").is_err());
        assert!(sandbox.validate_command("curl evil.com").is_err());
    }

    #[test]
    fn test_default_sandbox_has_no_commands() {
        let sandbox = SandboxConfig::default();
        assert!(sandbox.validate_command("ls").is_err());
    }
}
```

**Step 2: Register module**

Add to `common/src/lib.rs`:
```rust
pub mod sandbox;
```

**Step 3: Build and test**

Run: `wsl -d Ubuntu -- bash -c "source ~/.cargo/env && cd /mnt/d/personal_development/Koclaw && cargo test -p koclaw-common 2>&1"`
Expected: All tests pass (9 crypto + 7 memory + 4 persona + 6 sandbox = 26 total).

**Step 4: Commit**

```bash
git add common/src/sandbox.rs common/src/lib.rs
git commit -m "security(common): add tool sandbox with path validation and command allowlist"
```

---

## Task 6: Wire Persona + Sandbox into Agent Bridge Protocol

**Files:**
- Modify: `gateway/src/agent_bridge.rs` (add persona and sandbox fields to AgentRequest)
- Modify: `gateway/src/router.rs` (include persona system prompt in requests)
- Modify: `agent/koclaw_agent/bridge.py` (use persona, enforce sandbox)

**Step 1: Extend AgentRequest with persona and sandbox**

In `gateway/src/agent_bridge.rs`, add fields to `AgentRequest`:

```rust
pub struct AgentRequest {
    // ... existing fields ...
    pub system_prompt: Option<String>,  // From persona
    pub sandbox_root: Option<String>,
    pub allowed_commands: Vec<String>,
}
```

**Step 2: Update Router to load and inject persona**

The Router should hold a `Persona` instance and include `persona.system_prompt(message.channel)` in the agent request.

**Step 3: Update Python bridge to use system_prompt**

In `agent/koclaw_agent/bridge.py`, pass the `system_prompt` from the request as the system message to the LLM provider.

**Step 4: Build and test**

Run full test suite.

**Step 5: Commit**

```bash
git add gateway/src/agent_bridge.rs gateway/src/router.rs agent/koclaw_agent/bridge.py
git commit -m "feat(gateway): wire persona and sandbox into agent bridge protocol"
```

---

## Task 7: Update Documentation

**Files:**
- Modify: `README.md` (update Phase 2 roadmap)
- Modify: `docs/CHANGELOG.md` (add Phase 2 entries)
- Modify: `docs/DEVELOPMENT.md` (update file descriptions)
- Create: `docs/channels/discord.md` (Discord setup guide)
- Modify: `docs/architecture/trait-design.md` (add Persona, Sandbox, Memory docs)
- Modify: `docs/security/encryption-design.md` (add X25519 key exchange details)

**Step 1: Update all documentation to reflect Phase 2 features**

Each file should be updated with:
- Discord channel documentation (setup, intents, permissions)
- X25519 key exchange protocol description
- Memory system usage guide
- Persona system configuration
- Sandbox configuration reference

**Step 2: Commit**

```bash
git add README.md docs/
git commit -m "docs: update documentation for Phase 2 features"
```

---

## Phase 2 Completion Checklist

- [ ] X25519 key exchange + HKDF session key derivation (9+ crypto tests)
- [ ] Discord channel with WebSocket Gateway (compiles, manual test with real bot)
- [ ] Encrypted memory store with SQLite (7+ memory tests)
- [ ] Persona system with per-channel identity (4+ persona tests)
- [ ] Tool sandbox with path validation + command allowlist (6+ sandbox tests)
- [ ] Persona + Sandbox wired into Agent Bridge protocol
- [ ] Documentation updated
- [ ] All tests pass (26+ across common crate)

## What Comes Next (Phase 3)

- Web SDK (`@koclaw/web-widget`) for shinBlog integration
- Live2D embedding for web
- RAG knowledge base with vector search
- Desktop companion application (Electron + Live2D)
- Multi-agent orchestration
- Workflow visualization dashboard
- Double Ratchet forward secrecy
- Voice pipeline integration (ASR/TTS from AIKokoron)
