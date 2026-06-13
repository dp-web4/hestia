//! On-disk vault storage. The vault is one encrypted file at
//! `~/.hestia/vault.enc` (overridable via config). File layout:
//!
//! ```text
//! 0..4:    magic "HSTV" (4 bytes)
//! 4..5:    version byte (currently 1)
//! 5..21:   16-byte Argon2id salt
//! 21..33:  12-byte ChaCha20 nonce
//! 33..:    ChaCha20-Poly1305 ciphertext (auth-tagged)
//! ```
//!
//! The ciphertext, when decrypted, is JSON serialization of a `VaultData`
//! struct (which holds the list of entries + metadata).
//!
//! Atomic writes use temp-file-and-rename so a crash during write doesn't
//! corrupt the vault.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use super::crypto::{decrypt, derive_key, encrypt, generate_nonce, generate_salt};
use super::entry::VaultEntry;
use crate::error::{CoreError, Result};

/// File format magic + version
const MAGIC: &[u8; 4] = b"HSTV";
const VERSION: u8 = 1;
const HEADER_LEN: usize = 4 + 1 + 16 + 12; // = 33

/// The cleartext contents of the vault — serialized to JSON, then encrypted on disk.
///
/// **Schema versions**
/// - v1: `{ version, created_at, entries }`
/// - v2: adds `policy: VaultPolicyState`. The field is `#[serde(default)]`
///   so v1 vaults deserialize transparently with a default policy
///   (active_preset = "safety", no overrides, no custom rules). On
///   the next save, the file is rewritten with v2 layout.
/// - v3: adds `documents: Vec<Document>` — non-credential items (config,
///   metadata, state) that used to live in plaintext sidecar files, each
///   carrying its own `Protection` (Master / Sealed). `#[serde(default)]` so
///   older vaults load transparently. See `vault/document.rs`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultData {
    pub version: u32,
    pub created_at: DateTime<Utc>,
    pub entries: Vec<VaultEntry>,
    #[serde(default)]
    pub policy: super::policy_state::VaultPolicyState,
    #[serde(default)]
    pub documents: Vec<super::document::Document>,
}

impl Default for VaultData {
    fn default() -> Self {
        Self {
            version: 3,
            created_at: Utc::now(),
            entries: Vec::new(),
            policy: super::policy_state::VaultPolicyState::default(),
            documents: Vec::new(),
        }
    }
}

/// Path to the vault file, given a hestia home directory.
pub fn vault_path(hestia_home: &Path) -> PathBuf {
    hestia_home.join("vault.enc")
}

/// Default hestia home directory (`~/.hestia`).
pub fn default_hestia_home() -> Result<PathBuf> {
    let home = dirs::home_dir().ok_or(CoreError::NoHomeDirectory)?;
    Ok(home.join(".hestia"))
}

/// Read the vault file from disk, decrypt with the passphrase, return the data.
pub fn load(path: &Path, passphrase: &str) -> Result<VaultData> {
    if !path.exists() {
        return Err(CoreError::VaultNotFound(path.to_path_buf()));
    }

    let raw = fs::read(path).map_err(|e| CoreError::io(path, e))?;

    if raw.len() < HEADER_LEN {
        return Err(CoreError::VaultCorrupted {
            path: path.to_path_buf(),
            reason: "file too short for header".into(),
        });
    }

    if &raw[..4] != MAGIC {
        return Err(CoreError::VaultCorrupted {
            path: path.to_path_buf(),
            reason: "wrong magic bytes".into(),
        });
    }

    if raw[4] != VERSION {
        return Err(CoreError::VaultCorrupted {
            path: path.to_path_buf(),
            reason: format!("unsupported version: {}", raw[4]),
        });
    }

    let mut salt = [0u8; 16];
    salt.copy_from_slice(&raw[5..21]);
    let mut nonce = [0u8; 12];
    nonce.copy_from_slice(&raw[21..33]);
    let ciphertext = &raw[HEADER_LEN..];

    let key = derive_key(passphrase, &salt)?;
    let plaintext = decrypt(&key, &nonce, ciphertext)?;

    let data: VaultData = serde_json::from_slice(&plaintext)?;
    Ok(data)
}

/// Encrypt the vault data with the passphrase and write atomically to `path`.
/// A fresh salt + nonce are generated on every write.
pub fn save(path: &Path, passphrase: &str, data: &VaultData) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| CoreError::io(parent, e))?;
    }

    let salt = generate_salt();
    let nonce = generate_nonce();
    let key = derive_key(passphrase, &salt)?;

    let plaintext = serde_json::to_vec(data)?;
    let ciphertext = encrypt(&key, &nonce, &plaintext)?;

    let mut buffer = Vec::with_capacity(HEADER_LEN + ciphertext.len());
    buffer.extend_from_slice(MAGIC);
    buffer.push(VERSION);
    buffer.extend_from_slice(&salt);
    buffer.extend_from_slice(&nonce);
    buffer.extend_from_slice(&ciphertext);

    // Atomic write: temp file + rename
    let tmp_path = path.with_extension("enc.tmp");
    {
        let mut tmp = File::create(&tmp_path).map_err(|e| CoreError::io(&tmp_path, e))?;
        tmp.write_all(&buffer)
            .map_err(|e| CoreError::io(&tmp_path, e))?;
        tmp.sync_all().map_err(|e| CoreError::io(&tmp_path, e))?;
    }
    fs::rename(&tmp_path, path).map_err(|e| CoreError::io(path, e))?;

    // Tighten permissions on Unix (rwx for owner only)
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path)
            .map_err(|e| CoreError::io(path, e))?
            .permissions();
        perms.set_mode(0o600);
        fs::set_permissions(path, perms).map_err(|e| CoreError::io(path, e))?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn temp_vault() -> (TempDir, PathBuf) {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        (dir, path)
    }

    #[test]
    fn save_and_load_round_trip() {
        let (_dir, path) = temp_vault();
        let mut data = VaultData::default();
        data.entries.push(VaultEntry::new("key1", "secret1"));
        data.entries.push(VaultEntry::new("key2", "secret2"));

        save(&path, "passphrase", &data).unwrap();
        let loaded = load(&path, "passphrase").unwrap();
        assert_eq!(loaded.entries.len(), 2);
        assert_eq!(loaded.entries[0].name, "key1");
        assert_eq!(loaded.entries[0].secret, "secret1");
        assert_eq!(loaded.entries[1].name, "key2");
    }

    #[test]
    fn load_fails_with_wrong_passphrase() {
        let (_dir, path) = temp_vault();
        let data = VaultData::default();
        save(&path, "right", &data).unwrap();
        let result = load(&path, "wrong");
        assert!(matches!(result, Err(CoreError::DecryptionFailed)));
    }

    #[test]
    fn load_fails_when_file_missing() {
        let (_dir, path) = temp_vault();
        let result = load(&path, "pass");
        assert!(matches!(result, Err(CoreError::VaultNotFound(_))));
    }

    #[test]
    fn load_fails_with_corrupted_magic() {
        let (_dir, path) = temp_vault();
        fs::write(&path, b"garbage data not a real vault file").unwrap();
        let result = load(&path, "pass");
        assert!(matches!(result, Err(CoreError::VaultCorrupted { .. })));
    }

    #[test]
    fn save_overwrites_atomically_with_new_salt_and_nonce() {
        let (_dir, path) = temp_vault();
        let data = VaultData::default();
        save(&path, "p", &data).unwrap();
        let raw1 = fs::read(&path).unwrap();

        save(&path, "p", &data).unwrap();
        let raw2 = fs::read(&path).unwrap();

        // Same data, same passphrase, but different salt+nonce → ciphertext should differ
        assert_ne!(raw1, raw2);
    }

    #[cfg(unix)]
    #[test]
    fn save_sets_strict_permissions() {
        use std::os::unix::fs::PermissionsExt;
        let (_dir, path) = temp_vault();
        let data = VaultData::default();
        save(&path, "p", &data).unwrap();
        let perms = fs::metadata(&path).unwrap().permissions();
        // 0o600 = rw for owner only
        assert_eq!(perms.mode() & 0o777, 0o600);
    }

    #[test]
    fn entries_round_trip_through_encryption() {
        let (_dir, path) = temp_vault();
        let mut data = VaultData::default();
        let entry = VaultEntry::new("npm_token", "npm_xxxxx")
            .with_scope(vec!["publish".into()])
            .with_consumers(vec!["claude-code".into(), "openclaw".into()]);
        data.entries.push(entry);

        save(&path, "p", &data).unwrap();
        let loaded = load(&path, "p").unwrap();

        assert_eq!(loaded.entries.len(), 1);
        let e = &loaded.entries[0];
        assert_eq!(e.name, "npm_token");
        assert_eq!(e.secret, "npm_xxxxx");
        assert_eq!(e.scope, vec!["publish"]);
        assert_eq!(e.allowed_consumers, vec!["claude-code", "openclaw"]);
        assert!(e.allows("claude-code"));
        assert!(!e.allows("cursor"));
        assert!(e.matches_scope(&["publish".into()]));
        assert!(!e.matches_scope(&["infer".into()]));
    }
}
