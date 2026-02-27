//! Encrypted persistent memory backed by SQLite.
//!
//! All values are encrypted with ChaCha20-Poly1305 before storage.
//! The encryption key should be derived per-user via HKDF from a master key.

use anyhow::Result;
use rusqlite::Connection;
use tracing::debug;

use crate::crypto;

/// Encrypted persistent memory backed by SQLite.
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
            );",
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
            );",
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
        let mut stmt = self
            .conn
            .prepare("SELECT value FROM memory WHERE key = ?1")?;

        let result: Option<Vec<u8>> = stmt
            .query_row(rusqlite::params![key], |row| row.get(0))
            .ok();

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
        let affected = self
            .conn
            .execute("DELETE FROM memory WHERE key = ?1", rusqlite::params![key])?;
        Ok(affected > 0)
    }

    /// List all keys matching a prefix.
    pub fn list_keys(&self, prefix: &str) -> Result<Vec<String>> {
        let mut stmt = self
            .conn
            .prepare("SELECT key FROM memory WHERE key LIKE ?1 ORDER BY accessed_at DESC")?;
        let pattern = format!("{}%", prefix);
        let keys: Vec<String> = stmt
            .query_map(rusqlite::params![pattern], |row| row.get(0))?
            .filter_map(|r| r.ok())
            .collect();
        Ok(keys)
    }

    /// Count entries matching a prefix.
    pub fn count(&self, prefix: &str) -> Result<usize> {
        let mut stmt = self
            .conn
            .prepare("SELECT COUNT(*) FROM memory WHERE key LIKE ?1")?;
        let pattern = format!("{}%", prefix);
        let count: usize =
            stmt.query_row(rusqlite::params![pattern], |row| row.get(0))?;
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
        let encrypted: Vec<u8> = store1
            .conn
            .query_row(
                "SELECT value FROM memory WHERE key = 'secret'",
                [],
                |row| row.get(0),
            )
            .unwrap();

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
