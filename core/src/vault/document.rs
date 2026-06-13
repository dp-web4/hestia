//! Vault documents — non-credential items (config, metadata, state) that used
//! to live in plaintext sidecar files, plus the per-item *protection* model
//! that makes the vault recursive.
//!
//! Doctrine (see `dev-hub/design/recursive-vault.md`):
//! - **Total enclosure**: config/metadata/state live here, not in plaintext
//!   files. A `Document` is one such item.
//! - **Recursive locking**: a document may be `Master` (readable with the outer
//!   unlock) or `Sealed` (encrypted under an *independent* credential; the outer
//!   unlock reveals only that it exists). A sealed document's plaintext can
//!   itself be a whole `VaultData` — a sub-vault.
//! - **Memory-only unlock**: opening a sealed document decrypts **into a
//!   zeroizing buffer in memory** and returns it; nothing decrypted ever touches
//!   disk. Persistence always re-encrypts.

use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

use super::crypto::{decrypt, derive_key, encrypt, generate_nonce, generate_salt};
use crate::error::Result;

/// How a vault item is protected *beyond* the outer master encryption.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum Protection {
    /// Readable with the outer master unlock — the basics (config, metadata).
    /// The bytes are protected only by the whole-vault encryption.
    Master,
    /// Encrypted under an INDEPENDENT credential. The outer unlock reveals the
    /// item's existence + metadata but NOT its plaintext; opening requires the
    /// separate credential. Carries its own KDF salt + AEAD nonce.
    Sealed { salt: [u8; 16], nonce: [u8; 12] },
    // Liveness { requirement } — P4 (SITL-gated). Stored as a typed descriptor;
    // opening will require a satisfying PresenceProof, with the concrete
    // constellation-MFA verifier kept private. Not yet implemented.
}

/// A non-credential vault item: config, metadata, or state. `namespace` groups
/// items (e.g. "config", "constellation", "profile"); `name` is unique within a
/// namespace.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Document {
    pub namespace: String,
    pub name: String,
    pub protection: Protection,
    /// For `Master`: the plaintext bytes (held inside the outer-encrypted
    /// vault). For `Sealed`: the inner ciphertext (AEAD tag included) — never
    /// the cleartext.
    payload: Vec<u8>,
}

impl Document {
    /// A master-tier document. Plaintext is held inside the outer-encrypted
    /// vault; readable immediately after the outer unlock.
    pub fn master(namespace: impl Into<String>, name: impl Into<String>, bytes: Vec<u8>) -> Self {
        Self {
            namespace: namespace.into(),
            name: name.into(),
            protection: Protection::Master,
            payload: bytes,
        }
    }

    /// Seal `bytes` under an independent `credential` (a second passphrase /
    /// device secret). The plaintext is encrypted now and is never stored in
    /// the clear; opening requires the same credential.
    pub fn sealed(
        namespace: impl Into<String>,
        name: impl Into<String>,
        bytes: &[u8],
        credential: &str,
    ) -> Result<Self> {
        let salt = generate_salt();
        let nonce = generate_nonce();
        let key = derive_key(credential, &salt)?;
        let payload = encrypt(&key, &nonce, bytes)?;
        Ok(Self {
            namespace: namespace.into(),
            name: name.into(),
            protection: Protection::Sealed { salt, nonce },
            payload,
        })
    }

    pub fn is_sealed(&self) -> bool {
        matches!(self.protection, Protection::Sealed { .. })
    }

    /// The master-tier plaintext, if this is a `Master` document. `None` for a
    /// sealed document (use [`open`](Self::open) with its credential).
    pub fn master_bytes(&self) -> Option<&[u8]> {
        match self.protection {
            Protection::Master => Some(self.payload.as_slice()),
            _ => None,
        }
    }

    /// Decrypt this document INTO MEMORY. For a `Master` doc, returns a copy of
    /// the plaintext; for a `Sealed` doc, derives the key from `credential` and
    /// decrypts. The returned buffer zeroizes on drop and never touches disk.
    pub fn open(&self, credential: &str) -> Result<Zeroizing<Vec<u8>>> {
        match &self.protection {
            Protection::Master => Ok(Zeroizing::new(self.payload.clone())),
            Protection::Sealed { salt, nonce } => {
                let key = derive_key(credential, salt)?;
                let plaintext = decrypt(&key, nonce, &self.payload)?;
                Ok(Zeroizing::new(plaintext))
            }
        }
    }
}

/// One row of the vault's content *index*: enough to enumerate and reason about
/// an item after the outer unlock, without exposing sealed plaintext.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ItemRef {
    pub namespace: String,
    pub name: String,
    pub protection: Protection,
}

impl From<&Document> for ItemRef {
    fn from(d: &Document) -> Self {
        Self {
            namespace: d.namespace.clone(),
            name: d.name.clone(),
            protection: d.protection.clone(),
        }
    }
}
