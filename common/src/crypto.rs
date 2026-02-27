//! Encryption utilities for Koclaw.
//!
//! Phase 1: Encryption at rest (credentials, session data)
//! Phase 1.5: X25519 key exchange for transport encryption
//! Phase 2: True E2E with Agent-held keys
//!
//! See docs/security/encryption-design.md for full design.

use anyhow::{Context, Result};
use chacha20poly1305::{
    aead::{Aead, KeyInit, OsRng},
    ChaCha20Poly1305, Key, Nonce,
};
use rand::RngCore;

/// Length of a ChaCha20-Poly1305 nonce (96 bits / 12 bytes).
const NONCE_LEN: usize = 12;

/// Length of a ChaCha20-Poly1305 key (256 bits / 32 bytes).
const KEY_LEN: usize = 32;

/// Generate a random 256-bit encryption key.
pub fn generate_key() -> [u8; KEY_LEN] {
    let mut key = [0u8; KEY_LEN];
    OsRng.fill_bytes(&mut key);
    key
}

/// Encrypt plaintext using ChaCha20-Poly1305.
///
/// Returns: nonce (12 bytes) || ciphertext (includes 16-byte auth tag)
pub fn encrypt(plaintext: &[u8], key: &[u8; KEY_LEN]) -> Result<Vec<u8>> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));

    let mut nonce_bytes = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| anyhow::anyhow!("Encryption failed: {}", e))?;

    // Prepend nonce to ciphertext
    let mut output = Vec::with_capacity(NONCE_LEN + ciphertext.len());
    output.extend_from_slice(&nonce_bytes);
    output.extend_from_slice(&ciphertext);

    Ok(output)
}

/// Decrypt ciphertext produced by `encrypt()`.
///
/// Input: nonce (12 bytes) || ciphertext (with auth tag)
pub fn decrypt(data: &[u8], key: &[u8; KEY_LEN]) -> Result<Vec<u8>> {
    if data.len() < NONCE_LEN {
        anyhow::bail!("Ciphertext too short");
    }

    let (nonce_bytes, ciphertext) = data.split_at(NONCE_LEN);
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    let nonce = Nonce::from_slice(nonce_bytes);

    let plaintext = cipher
        .decrypt(nonce, ciphertext)
        .map_err(|e| anyhow::anyhow!("Decryption failed (wrong key or corrupted data): {}", e))?;

    Ok(plaintext)
}

/// Encrypt a string value for config storage.
/// Returns a hex-encoded string prefixed with "enc:"
pub fn encrypt_config_value(value: &str, key: &[u8; KEY_LEN]) -> Result<String> {
    let encrypted = encrypt(value.as_bytes(), key)?;
    Ok(format!("enc:{}", hex::encode(encrypted)))
}

/// Decrypt a config value produced by `encrypt_config_value()`.
pub fn decrypt_config_value(encoded: &str, key: &[u8; KEY_LEN]) -> Result<String> {
    let hex_str = encoded
        .strip_prefix("enc:")
        .context("Not an encrypted config value (missing 'enc:' prefix)")?;

    let data = hex::decode(hex_str).context("Invalid hex in encrypted config value")?;
    let plaintext = decrypt(&data, key)?;

    String::from_utf8(plaintext).context("Decrypted config value is not valid UTF-8")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encrypt_decrypt_roundtrip() {
        let key = generate_key();
        let plaintext = b"sensitive bot token 123456:ABCdef";

        let ciphertext = encrypt(plaintext, &key).unwrap();
        assert_ne!(&ciphertext[NONCE_LEN..], plaintext); // Must differ

        let decrypted = decrypt(&ciphertext, &key).unwrap();
        assert_eq!(plaintext, &decrypted[..]);
    }

    #[test]
    fn test_wrong_key_fails() {
        let key1 = generate_key();
        let key2 = generate_key();
        let plaintext = b"secret";

        let ciphertext = encrypt(plaintext, &key1).unwrap();
        let result = decrypt(&ciphertext, &key2);

        assert!(result.is_err());
    }

    #[test]
    fn test_config_value_roundtrip() {
        let key = generate_key();
        let value = "my-api-key-12345";

        let encrypted = encrypt_config_value(value, &key).unwrap();
        assert!(encrypted.starts_with("enc:"));

        let decrypted = decrypt_config_value(&encrypted, &key).unwrap();
        assert_eq!(value, decrypted);
    }

    #[test]
    fn test_empty_plaintext() {
        let key = generate_key();
        let plaintext = b"";

        let ciphertext = encrypt(plaintext, &key).unwrap();
        let decrypted = decrypt(&ciphertext, &key).unwrap();
        assert_eq!(plaintext, &decrypted[..]);
    }

    #[test]
    fn test_tampered_ciphertext_fails() {
        let key = generate_key();
        let plaintext = b"important data";

        let mut ciphertext = encrypt(plaintext, &key).unwrap();
        // Flip a bit in the ciphertext (after nonce)
        if let Some(byte) = ciphertext.get_mut(NONCE_LEN + 1) {
            *byte ^= 0xFF;
        }

        let result = decrypt(&ciphertext, &key);
        assert!(result.is_err());
    }
}
