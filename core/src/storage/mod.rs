//! Persistence backends for the Hestia daemon.
//!
//! - `chain` — SQLCipher-encrypted hash-linked witness chain
//! - `trust` — per-entity T3/V3, each sealed at rest
//!
//! Both are encrypted at rest with a single stable storage key derived once
//! from `HESTIA_PASSPHRASE` (vault doctrine: no plaintext state). The key is
//! cached across writes (Argon2 once), so high-frequency writes (trust updates,
//! chain appends) don't re-derive per write.

pub mod chain;
pub mod trust;

pub use chain::{ChainEntry, SqliteChainStore};
pub use trust::TrustStore;

use std::path::Path;

use crate::error::{CoreError, Result};

/// Derive the stable storage key (32 bytes) from the vault `passphrase` + a
/// per-home salt persisted at `<home>/.store-salt` (the salt isn't secret).
/// Argon2id, done once per daemon/CLI open; the stores cache the result. The
/// passphrase is the same one that unlocked the vault — passed explicitly so the
/// key isn't coupled to a global env var.
pub fn storage_key(home: &Path, passphrase: &str) -> Result<[u8; 32]> {
    let salt_path = home.join(".store-salt");
    let salt: [u8; 16] = if salt_path.exists() {
        let raw = std::fs::read(&salt_path).map_err(|e| CoreError::io(&salt_path, e))?;
        raw.as_slice()
            .try_into()
            .map_err(|_| CoreError::KeyDerivation("store salt must be 16 bytes".into()))?
    } else {
        let s = web4_core::vault::crypto::generate_salt();
        std::fs::create_dir_all(home).ok();
        std::fs::write(&salt_path, s).map_err(|e| CoreError::io(&salt_path, e))?;
        s
    };
    let dk = web4_core::vault::crypto::derive_key(passphrase, &salt)
        .map_err(|e| CoreError::KeyDerivation(format!("deriving storage key: {e}")))?;
    Ok(*dk.as_bytes())
}
