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
use hkdf::Hkdf;
use rand::RngCore;
use sha2::Sha256;
use x25519_dalek::{PublicKey, StaticSecret};

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

// --- X25519 Key Exchange ---

/// Generate an X25519 keypair for key exchange.
///
/// Returns (secret_key_bytes, public_key_bytes).
/// The secret key should NEVER leave the device.
pub fn generate_keypair() -> ([u8; 32], [u8; 32]) {
    let secret = StaticSecret::random_from_rng(OsRng);
    let public = PublicKey::from(&secret);
    (secret.to_bytes(), public.to_bytes())
}

/// Perform X25519 Diffie-Hellman to derive a raw shared secret.
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

    // --- X25519 Key Exchange Tests ---

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
        let (alice_secret, _) = generate_keypair();
        let (_, bob_public) = generate_keypair();

        let session_key = derive_session_key(&alice_secret, &bob_public, b"koclaw-session-v1");

        let plaintext = b"Hello from encrypted session!";
        let ciphertext = encrypt(plaintext, &session_key).unwrap();
        let decrypted = decrypt(&ciphertext, &session_key).unwrap();

        assert_eq!(plaintext.to_vec(), decrypted);
    }

    #[test]
    fn test_different_contexts_produce_different_keys() {
        let (alice_secret, _) = generate_keypair();
        let (_, bob_public) = generate_keypair();

        let key1 = derive_session_key(&alice_secret, &bob_public, b"koclaw-session-v1");
        let key2 = derive_session_key(&alice_secret, &bob_public, b"koclaw-memory-v1");

        assert_ne!(key1, key2, "Different contexts must produce different keys");
    }
}
