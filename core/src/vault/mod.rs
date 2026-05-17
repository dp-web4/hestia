//! Vault module — encrypted credential storage.
//!
//! The Vault wraps the on-disk file format with high-level operations:
//! list / get / add / remove / rotate. All operations take a passphrase
//! since the file is encrypted at rest.

pub mod crypto;
pub mod entry;
pub mod policy_state;
pub mod storage;

pub use entry::VaultEntry;
pub use policy_state::{PolicyOverride, VaultPolicyState};
pub use storage::{default_hestia_home, vault_path, VaultData};

use std::path::PathBuf;

use crate::error::{CoreError, Result};

/// High-level Vault interface. Loads on construction; saves back on mutating ops.
pub struct Vault {
    path: PathBuf,
    passphrase: String,
    data: VaultData,
}

impl Vault {
    /// Open an existing vault file at `path` using `passphrase`.
    pub fn open(path: PathBuf, passphrase: String) -> Result<Self> {
        let data = storage::load(&path, &passphrase)?;
        Ok(Self {
            path,
            passphrase,
            data,
        })
    }

    /// Create a new empty vault at `path` with `passphrase`. Errors if a vault
    /// file already exists there (use `init_force` to overwrite).
    pub fn init(path: PathBuf, passphrase: String) -> Result<Self> {
        if path.exists() {
            return Err(CoreError::VaultAlreadyExists(path));
        }
        Self::init_force(path, passphrase)
    }

    pub fn init_force(path: PathBuf, passphrase: String) -> Result<Self> {
        let data = VaultData::default();
        storage::save(&path, &passphrase, &data)?;
        Ok(Self {
            path,
            passphrase,
            data,
        })
    }

    /// Number of entries
    pub fn len(&self) -> usize {
        self.data.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.entries.is_empty()
    }

    /// List entry names, sorted alphabetically.
    pub fn list(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.data.entries.iter().map(|e| e.name.as_str()).collect();
        names.sort();
        names
    }

    /// Get an entry by name. Returns None if not found.
    pub fn get(&self, name: &str) -> Option<&VaultEntry> {
        self.data.entries.iter().find(|e| e.name == name)
    }

    /// Add a new entry. Errors if an entry with the same name exists.
    pub fn add(&mut self, entry: VaultEntry) -> Result<()> {
        if self.data.entries.iter().any(|e| e.name == entry.name) {
            return Err(CoreError::CredentialAlreadyExists(entry.name));
        }
        self.data.entries.push(entry);
        self.save()
    }

    /// Replace an entry (or add it if it doesn't exist).
    pub fn upsert(&mut self, entry: VaultEntry) -> Result<()> {
        if let Some(idx) = self.data.entries.iter().position(|e| e.name == entry.name) {
            self.data.entries[idx] = entry;
        } else {
            self.data.entries.push(entry);
        }
        self.save()
    }

    /// Remove an entry by name. Returns the removed entry.
    pub fn remove(&mut self, name: &str) -> Result<VaultEntry> {
        let idx = self
            .data
            .entries
            .iter()
            .position(|e| e.name == name)
            .ok_or_else(|| CoreError::CredentialNotFound(name.to_string()))?;
        let removed = self.data.entries.remove(idx);
        self.save()?;
        Ok(removed)
    }

    fn save(&self) -> Result<()> {
        storage::save(&self.path, &self.passphrase, &self.data)
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }

    /// Read the policy state stored inside the vault.
    pub fn policy(&self) -> &VaultPolicyState {
        &self.data.policy
    }

    /// Replace the vault's policy state and persist.
    pub fn set_policy(&mut self, policy: VaultPolicyState) -> Result<()> {
        self.data.policy = policy;
        self.save()
    }

    /// Convenience: change just the active preset, keeping overrides + custom rules.
    /// Returns `Err(CoreError::InvalidPreset)` if the preset isn't built-in.
    pub fn set_active_preset(&mut self, preset_name: &str) -> Result<()> {
        if !crate::policy::is_preset_name(preset_name) {
            return Err(CoreError::InvalidPreset(preset_name.to_string()));
        }
        self.data.policy.active_preset = preset_name.to_string();
        self.save()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn temp_path() -> (TempDir, PathBuf) {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        (dir, path)
    }

    #[test]
    fn init_and_open_round_trip() {
        let (_dir, path) = temp_path();
        let _v = Vault::init(path.clone(), "passphrase".into()).unwrap();
        let v2 = Vault::open(path, "passphrase".into()).unwrap();
        assert_eq!(v2.len(), 0);
    }

    #[test]
    fn init_fails_when_vault_exists() {
        let (_dir, path) = temp_path();
        Vault::init(path.clone(), "p".into()).unwrap();
        let result = Vault::init(path, "p".into());
        assert!(matches!(result, Err(CoreError::VaultAlreadyExists(_))));
    }

    #[test]
    fn add_get_remove_lifecycle() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path.clone(), "p".into()).unwrap();

        v.add(VaultEntry::new("key1", "value1")).unwrap();
        v.add(VaultEntry::new("key2", "value2")).unwrap();

        assert_eq!(v.len(), 2);
        assert_eq!(v.list(), vec!["key1", "key2"]);
        assert_eq!(v.get("key1").unwrap().secret, "value1");
        assert!(v.get("nonexistent").is_none());

        let removed = v.remove("key1").unwrap();
        assert_eq!(removed.secret, "value1");
        assert_eq!(v.len(), 1);
        assert!(v.get("key1").is_none());

        // Persists across re-open
        let v2 = Vault::open(path, "p".into()).unwrap();
        assert_eq!(v2.list(), vec!["key2"]);
    }

    #[test]
    fn add_duplicate_fails() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path, "p".into()).unwrap();
        v.add(VaultEntry::new("key", "v1")).unwrap();
        let result = v.add(VaultEntry::new("key", "v2"));
        assert!(matches!(result, Err(CoreError::CredentialAlreadyExists(_))));
    }

    #[test]
    fn upsert_replaces_existing() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path, "p".into()).unwrap();
        v.add(VaultEntry::new("key", "v1")).unwrap();
        v.upsert(VaultEntry::new("key", "v2")).unwrap();
        assert_eq!(v.len(), 1);
        assert_eq!(v.get("key").unwrap().secret, "v2");
    }

    #[test]
    fn remove_missing_errors() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path, "p".into()).unwrap();
        let result = v.remove("nonexistent");
        assert!(matches!(result, Err(CoreError::CredentialNotFound(_))));
    }
}
