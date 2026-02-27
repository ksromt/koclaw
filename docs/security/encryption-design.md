# E2E Encryption Design

## Goal

Ensure that even if the server (Gateway) is compromised or administered by an untrusted
party, user messages remain confidential.

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Server admin reads messages | E2E encryption — server only sees ciphertext |
| Network eavesdropping | TLS for transport + E2E for payload |
| Key theft from server | User private keys never leave user device |
| Replay attacks | Nonce-based encryption (ChaCha20-Poly1305) |
| Forward secrecy breach | Double Ratchet or periodic key rotation |

## Cryptographic Primitives

| Primitive | Algorithm | Library (Rust) |
|-----------|-----------|----------------|
| Key exchange | X25519 (Curve25519 ECDH) | `x25519-dalek` |
| Symmetric encryption | ChaCha20-Poly1305 (AEAD) | `chacha20poly1305` |
| Key derivation | HKDF-SHA256 | `hkdf` + `sha2` |
| Signing | Ed25519 | `ed25519-dalek` |
| Random | CSPRNG | `rand` (OsRng) |

## Key Exchange Flow

### Phase 1 (MVP): Server-Mediated E2E

In this phase, the Gateway decrypts messages to forward to the Agent.
This protects against network eavesdropping but NOT against a malicious server admin.

```
Client                         Gateway
  │                               │
  ├── ClientHello ───────────────►│
  │   (client_ephemeral_pubkey)   │
  │                               │
  │◄── ServerHello ───────────────┤
  │   (server_ephemeral_pubkey)   │
  │                               │
  │  shared_secret = X25519(      │
  │    client_priv,               │
  │    server_pub)                │
  │                               │
  │  session_key = HKDF(          │
  │    shared_secret,             │
  │    "koclaw-session-v1")       │
  │                               │
  ├── Encrypt(msg, session_key) ─►│  decrypt → forward to Agent
  │◄── Encrypt(resp, session_key)─┤  encrypt ← response from Agent
```

### Phase 2 (Future): True Zero-Knowledge E2E

Agent runs as a separate encrypted process. Gateway acts as a pure relay.
Messages are encrypted client-to-agent, Gateway cannot decrypt.

This requires the Agent to hold its own key pair and the client to
establish a session directly with the Agent through the Gateway relay.

## Encrypted Memory Storage

User memories and chat history are encrypted at rest:

```
plaintext_memory → HKDF(user_key, "memory-v1") → ChaCha20-Poly1305 → stored_blob
```

The encryption key is derived from the user's identity key, ensuring that
only authenticated sessions from that user can read their memories.

## Implementation Priority

1. **Phase 1**: TLS transport + server-side encryption at rest (basic security)
2. **Phase 1.5**: X25519 key exchange + ChaCha20 session encryption
3. **Phase 2**: True E2E with Agent-held keys
4. **Phase 3**: Double Ratchet for forward secrecy
