//! App identity-vault custody for the human/root credential.
//!
//! This store is intentionally separate from the daemon's governance vault: it
//! belongs to a person rather than a machine. The legacy `operator.key` is read
//! only by the explicit migration function, and is removed only after the new
//! encrypted file has been written, synced, reopened, and authenticated.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use argon2::{Algorithm, Argon2, Params, Version};
use chacha20poly1305::{
    aead::{Aead, KeyInit},
    ChaCha20Poly1305, Key, Nonce,
};
use ed25519_dalek::{Signer, SigningKey};
use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use web4_core::{crypto::PublicKey, lct::derive_lct_id};
use zeroize::{Zeroize, Zeroizing};

const MAGIC: &[u8; 4] = b"HSTI";
const FORMAT_VERSION: u8 = 1;
const SALT_LEN: usize = 16;
const NONCE_LEN: usize = 12;
const HEADER_LEN: usize = MAGIC.len() + 1 + SALT_LEN + NONCE_LEN;
const ARGON_M_COST_KIB: u32 = 64 * 1024;
const ARGON_T_COST: u32 = 3;
const ARGON_P_COST: u32 = 4;

#[derive(Deserialize)]
struct LegacyOperatorKey {
    lct_id: String,
    secret_key_hex: String,
}

impl Drop for LegacyOperatorKey {
    fn drop(&mut self) {
        self.lct_id.zeroize();
        self.secret_key_hex.zeroize();
    }
}

#[derive(Serialize, Deserialize)]
struct StoredCredential {
    principal_lct: String,
    secret_key: [u8; 32],
    harness_secret_key: [u8; 32],
    device_secret_key: [u8; 32],
}

impl Drop for StoredCredential {
    fn drop(&mut self) {
        self.principal_lct.zeroize();
        self.secret_key.zeroize();
        self.harness_secret_key.zeroize();
        self.device_secret_key.zeroize();
    }
}

/// An unlocked identity vault. It deliberately has no `Debug`, `Serialize`, or
/// secret accessor: callers may identify the principal and request signatures,
/// but cannot turn the root seed back into application data.
pub struct IdentityVault {
    path: PathBuf,
    principal_lct: String,
    principal_key: SigningKey,
    harness_key: SigningKey,
    device_key: SigningKey,
    harness_lct: String,
    device_lct: String,
}

impl IdentityVault {
    /// Authenticate and open an encrypted identity vault.
    pub fn open(path: impl AsRef<Path>, passphrase: &str) -> Result<Self, String> {
        let path = path.as_ref();
        if passphrase.is_empty() {
            return Err("identity vault passphrase must not be empty".into());
        }

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(path)
                .map_err(|e| format!("inspect identity vault {}: {e}", path.display()))?
                .permissions()
                .mode()
                & 0o777;
            if mode & 0o077 != 0 {
                return Err(format!(
                    "identity vault {} is accessible outside its owner (mode {mode:o}); remove group/other permissions",
                    path.display()
                ));
            }
        }

        let raw =
            fs::read(path).map_err(|e| format!("read identity vault {}: {e}", path.display()))?;
        if raw.len() < HEADER_LEN + 16 {
            return Err("identity vault is truncated".into());
        }
        if &raw[..MAGIC.len()] != MAGIC {
            return Err("identity vault has the wrong magic".into());
        }
        if raw[MAGIC.len()] != FORMAT_VERSION {
            return Err(format!(
                "unsupported identity vault version {}",
                raw[MAGIC.len()]
            ));
        }

        let salt_start = MAGIC.len() + 1;
        let nonce_start = salt_start + SALT_LEN;
        let ciphertext_start = nonce_start + NONCE_LEN;
        let key = derive_key(passphrase, &raw[salt_start..nonce_start])?;
        let cipher = ChaCha20Poly1305::new(Key::from_slice(key.as_ref()));
        let plaintext = cipher
            .decrypt(
                Nonce::from_slice(&raw[nonce_start..ciphertext_start]),
                &raw[ciphertext_start..],
            )
            .map_err(|_| "identity vault authentication failed".to_string())?;
        let plaintext = Zeroizing::new(plaintext);
        let stored: StoredCredential = serde_json::from_slice(plaintext.as_slice())
            .map_err(|_| "identity vault payload is invalid".to_string())?;
        validate_lct(&stored.principal_lct)?;

        let harness_key = SigningKey::from_bytes(&stored.harness_secret_key);
        let device_key = SigningKey::from_bytes(&stored.device_secret_key);
        let harness_lct = lct_for_key(&harness_key)?;
        let device_lct = lct_for_key(&device_key)?;

        Ok(Self {
            path: path.to_path_buf(),
            principal_lct: stored.principal_lct.clone(),
            principal_key: SigningKey::from_bytes(&stored.secret_key),
            harness_key,
            device_key,
            harness_lct,
            device_lct,
        })
    }

    pub fn principal_lct(&self) -> &str {
        &self.principal_lct
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn harness_lct(&self) -> &str {
        &self.harness_lct
    }

    pub fn device_lct(&self) -> &str {
        &self.device_lct
    }

    pub fn harness_public_key_hex(&self) -> String {
        hex::encode(self.harness_key.verifying_key().to_bytes())
    }

    pub fn device_public_key_hex(&self) -> String {
        hex::encode(self.device_key.verifying_key().to_bytes())
    }

    /// Sign in the Rust shell. Only the encoded signature leaves this module.
    pub fn sign_hex(&self, message: &[u8]) -> Result<String, String> {
        Ok(hex::encode(self.principal_key.sign(message).to_bytes()))
    }

    pub fn sign_harness_hex(&self, message: &[u8]) -> String {
        hex::encode(self.harness_key.sign(message).to_bytes())
    }

    pub fn sign_device_hex(&self, message: &[u8]) -> String {
        hex::encode(self.device_key.sign(message).to_bytes())
    }

    fn verifying_key_bytes(&self) -> [u8; 32] {
        self.principal_key.verifying_key().to_bytes()
    }
}

/// Import a legacy plaintext `{lct_id, secret_key_hex}` credential exactly once.
///
/// The ordering is the guarantee: validate source → atomically create encrypted
/// destination → reopen/authenticate it → remove source. A failure before the
/// final step keeps the only readable credential intact.
pub fn migrate_plaintext_operator_key(
    source: impl AsRef<Path>,
    destination: impl AsRef<Path>,
    passphrase: &str,
) -> Result<IdentityVault, String> {
    let source = source.as_ref();
    let destination = destination.as_ref();
    if passphrase.is_empty() {
        return Err("identity vault passphrase must not be empty".into());
    }

    let source_meta = fs::symlink_metadata(source).map_err(|e| {
        format!(
            "inspect legacy operator credential {}: {e}",
            source.display()
        )
    })?;
    if source_meta.file_type().is_symlink() || !source_meta.is_file() {
        return Err(format!(
            "legacy operator credential {} must be a regular file, not a link or special file",
            source.display()
        ));
    }

    let stored = load_legacy(source)?;

    // A crash or permissions failure can leave a valid encrypted destination
    // beside the still-live plaintext source. Resume only after proving both
    // files contain the same principal and key; never overwrite either on a
    // mismatch.
    if destination.exists() {
        let opened = IdentityVault::open(destination, passphrase)?;
        let expected = SigningKey::from_bytes(&stored.secret_key)
            .verifying_key()
            .to_bytes();
        if opened.principal_lct() != stored.principal_lct
            || opened.verifying_key_bytes() != expected
        {
            return Err(
                "existing identity vault does not match the legacy credential; refusing to retire either file"
                    .into(),
            );
        }
        retire_plaintext_source(source)?;
        return Ok(opened);
    }

    save_new(destination, passphrase, &stored)?;
    let reopened = IdentityVault::open(destination, passphrase).map_err(|e| {
        let _ = fs::remove_file(destination);
        format!("new identity vault failed verification: {e}")
    })?;
    let expected = SigningKey::from_bytes(&stored.secret_key)
        .verifying_key()
        .to_bytes();
    if reopened.principal_lct() != stored.principal_lct
        || reopened.verifying_key_bytes() != expected
    {
        let _ = fs::remove_file(destination);
        return Err("new identity vault changed the principal credential".into());
    }

    retire_plaintext_source(source)?;
    Ok(reopened)
}

fn load_legacy(source: &Path) -> Result<StoredCredential, String> {
    let raw = Zeroizing::new(
        fs::read_to_string(source)
            .map_err(|e| format!("read legacy operator credential {}: {e}", source.display()))?,
    );
    let legacy: LegacyOperatorKey = serde_json::from_str(raw.as_str())
        .map_err(|_| "legacy operator credential has an invalid shape".to_string())?;
    validate_lct(&legacy.lct_id)?;
    let decoded = Zeroizing::new(
        hex::decode(legacy.secret_key_hex.trim())
            .map_err(|_| "legacy secret_key_hex is not valid hex".to_string())?,
    );
    let secret_key: [u8; 32] = decoded
        .as_slice()
        .try_into()
        .map_err(|_| "legacy secret_key_hex must be a 32-byte Ed25519 seed".to_string())?;
    Ok(StoredCredential {
        principal_lct: legacy.lct_id.clone(),
        secret_key,
        harness_secret_key: random_seed(),
        device_secret_key: random_seed(),
    })
}

fn random_seed() -> [u8; 32] {
    let mut seed = [0u8; 32];
    OsRng.fill_bytes(&mut seed);
    seed
}

fn lct_for_key(key: &SigningKey) -> Result<String, String> {
    let public = PublicKey::from_bytes(&key.verifying_key().to_bytes())
        .map_err(|e| format!("derive identity LCT from public key: {e}"))?;
    Ok(derive_lct_id(&public))
}

fn retire_plaintext_source(source: &Path) -> Result<(), String> {
    fs::remove_file(source).map_err(|e| {
        format!(
            "encrypted identity vault is valid, but removing plaintext source {} failed: {e}",
            source.display()
        )
    })?;
    sync_parent(source)?;
    Ok(())
}

fn validate_lct(lct: &str) -> Result<(), String> {
    if lct.trim() != lct || !lct.starts_with("lct:") || lct.len() <= 4 {
        return Err("identity credential carries an invalid principal LCT".into());
    }
    Ok(())
}

fn derive_key(passphrase: &str, salt: &[u8]) -> Result<Zeroizing<[u8; 32]>, String> {
    let params = Params::new(ARGON_M_COST_KIB, ARGON_T_COST, ARGON_P_COST, Some(32))
        .map_err(|e| format!("identity vault KDF parameters are invalid: {e}"))?;
    let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let mut key = Zeroizing::new([0u8; 32]);
    argon
        .hash_password_into(passphrase.as_bytes(), salt, key.as_mut())
        .map_err(|e| format!("identity vault key derivation failed: {e}"))?;
    Ok(key)
}

fn save_new(path: &Path, passphrase: &str, stored: &StoredCredential) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "identity vault path has no parent directory".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|e| format!("create identity vault directory {}: {e}", parent.display()))?;

    let mut salt = [0u8; SALT_LEN];
    let mut nonce = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut salt);
    OsRng.fill_bytes(&mut nonce);
    let key = derive_key(passphrase, &salt)?;
    let plaintext = Zeroizing::new(
        serde_json::to_vec(stored)
            .map_err(|_| "could not encode identity credential".to_string())?,
    );
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key.as_ref()));
    let mut ciphertext = cipher
        .encrypt(Nonce::from_slice(&nonce), plaintext.as_slice())
        .map_err(|_| "could not encrypt identity credential".to_string())?;

    let mut temp = tempfile::NamedTempFile::new_in(parent)
        .map_err(|e| format!("create identity vault temporary file: {e}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        temp.as_file()
            .set_permissions(fs::Permissions::from_mode(0o600))
            .map_err(|e| format!("set identity vault permissions: {e}"))?;
    }
    temp.write_all(MAGIC)
        .and_then(|_| temp.write_all(&[FORMAT_VERSION]))
        .and_then(|_| temp.write_all(&salt))
        .and_then(|_| temp.write_all(&nonce))
        .and_then(|_| temp.write_all(&ciphertext))
        .map_err(|e| format!("write identity vault: {e}"))?;
    ciphertext.zeroize();
    temp.as_file()
        .sync_all()
        .map_err(|e| format!("sync identity vault: {e}"))?;
    temp.persist_noclobber(path)
        .map_err(|e| format!("install identity vault {}: {}", path.display(), e.error))?;

    // Make the rename durable where the platform supports syncing directories.
    sync_parent(path)?;
    Ok(())
}

fn sync_parent(path: &Path) -> Result<(), String> {
    #[cfg(unix)]
    {
        let parent = path
            .parent()
            .ok_or_else(|| format!("{} has no parent directory", path.display()))?;
        fs::File::open(parent)
            .and_then(|dir| dir.sync_all())
            .map_err(|e| format!("sync directory {}: {e}", parent.display()))?;
    }
    Ok(())
}
