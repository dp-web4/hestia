//! Vault module — encrypted credential storage.
//!
//! The Vault wraps the on-disk file format with high-level operations:
//! list / get / add / remove / rotate. All operations take a passphrase
//! since the file is encrypted at rest.

pub mod crypto;
pub mod document;
pub mod entry;
pub mod policy_state;
pub mod storage;

pub use document::{Document, ItemRef, Protection};
pub use entry::VaultEntry;
pub use policy_state::{PolicyOverride, VaultPolicyState};
pub use storage::{default_hestia_home, vault_path, VaultData};

use zeroize::Zeroizing;

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

    // ---- Documents: config / metadata / state, enclosed in the vault ----
    //
    // The vault doctrine: every setting and piece of metadata lives here, not in
    // a plaintext sidecar file. A document is `Master` (readable with this
    // outer unlock) or `Sealed` (needs its own credential). Opening a sealed
    // document decrypts into memory only — nothing decrypted touches disk.

    fn doc_pos(&self, namespace: &str, name: &str) -> Option<usize> {
        self.data
            .documents
            .iter()
            .position(|d| d.namespace == namespace && d.name == name)
    }

    /// The content index: every document's namespace + name + protection,
    /// *without* exposing sealed plaintext. Lets a caller enumerate and reason
    /// about contents after the outer unlock.
    pub fn document_index(&self) -> Vec<ItemRef> {
        self.data.documents.iter().map(ItemRef::from).collect()
    }

    /// Store a master-tier document (config / metadata / state). Plaintext is
    /// held inside the outer-encrypted vault. Upserts by (namespace, name).
    pub fn put_document(
        &mut self,
        namespace: &str,
        name: &str,
        bytes: Vec<u8>,
    ) -> Result<()> {
        let doc = Document::master(namespace, name, bytes);
        match self.doc_pos(namespace, name) {
            Some(i) => self.data.documents[i] = doc,
            None => self.data.documents.push(doc),
        }
        self.save()
    }

    /// Read a master-tier document's bytes. `None` if absent or sealed (use
    /// [`open_document`](Self::open_document) for sealed items).
    pub fn get_document(&self, namespace: &str, name: &str) -> Option<&[u8]> {
        self.doc_pos(namespace, name)
            .and_then(|i| self.data.documents[i].master_bytes())
    }

    /// Store a document sealed under an INDEPENDENT credential. The outer unlock
    /// will reveal the item exists but not its plaintext; opening needs
    /// `credential`. Upserts by (namespace, name).
    pub fn seal_document(
        &mut self,
        namespace: &str,
        name: &str,
        bytes: &[u8],
        credential: &str,
    ) -> Result<()> {
        let doc = Document::sealed(namespace, name, bytes, credential)?;
        match self.doc_pos(namespace, name) {
            Some(i) => self.data.documents[i] = doc,
            None => self.data.documents.push(doc),
        }
        self.save()
    }

    /// Open a document INTO MEMORY. For a sealed document, `credential` is its
    /// independent secret. Returns a zeroizing buffer; nothing touches disk.
    pub fn open_document(
        &self,
        namespace: &str,
        name: &str,
        credential: &str,
    ) -> Result<Zeroizing<Vec<u8>>> {
        let i = self
            .doc_pos(namespace, name)
            .ok_or_else(|| CoreError::CredentialNotFound(format!("{namespace}/{name}")))?;
        self.data.documents[i].open(credential)
    }

    pub fn remove_document(&mut self, namespace: &str, name: &str) -> Result<()> {
        let i = self
            .doc_pos(namespace, name)
            .ok_or_else(|| CoreError::CredentialNotFound(format!("{namespace}/{name}")))?;
        self.data.documents.remove(i);
        self.save()
    }

    // ---- Recursion: a sub-vault is a sealed document whose plaintext is itself
    // a whole `VaultData`, opened with its own credential. ----

    /// Store a nested vault, sealed under its own `credential`. The sub-vault's
    /// contents are invisible (and unreadable) under the outer unlock alone.
    pub fn put_subvault(
        &mut self,
        namespace: &str,
        name: &str,
        sub: &VaultData,
        credential: &str,
    ) -> Result<()> {
        let bytes = serde_json::to_vec(sub)?;
        self.seal_document(namespace, name, &bytes, credential)
    }

    /// Open a nested vault into memory with its `credential`.
    pub fn open_subvault(
        &self,
        namespace: &str,
        name: &str,
        credential: &str,
    ) -> Result<VaultData> {
        let bytes = self.open_document(namespace, name, credential)?;
        let sub: VaultData = serde_json::from_slice(&bytes)?;
        Ok(sub)
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

    // ---- Recursive-vault doctrine ----

    #[test]
    fn master_document_round_trips_through_the_vault() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path.clone(), "master".into()).unwrap();
        v.put_document("config", "daemon", b"{\"bind\":\"127.0.0.1:7711\"}".to_vec())
            .unwrap();

        // Persists across re-open, readable with the outer unlock.
        let v2 = Vault::open(path, "master".into()).unwrap();
        assert_eq!(
            v2.get_document("config", "daemon").unwrap(),
            b"{\"bind\":\"127.0.0.1:7711\"}"
        );
        let idx = v2.document_index();
        assert_eq!(idx.len(), 1);
        assert_eq!(idx[0].protection, Protection::Master);
    }

    #[test]
    fn sealed_document_needs_its_own_credential_not_just_the_master() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path.clone(), "master".into()).unwrap();
        v.seal_document("secrets", "high_tier_key", b"top-secret-bytes", "second-factor")
            .unwrap();

        let v2 = Vault::open(path, "master".into()).unwrap();
        // The outer unlock reveals the item EXISTS + that it's sealed...
        let idx = v2.document_index();
        assert_eq!(idx[0].name, "high_tier_key");
        assert!(matches!(idx[0].protection, Protection::Sealed { .. }));
        // ...but not its plaintext: get_document (master path) sees nothing.
        assert!(v2.get_document("secrets", "high_tier_key").is_none());
        // Opening with the master passphrase fails — needs the seal credential.
        assert!(v2.open_document("secrets", "high_tier_key", "master").is_err());
        // The independent credential opens it, into memory.
        let opened = v2
            .open_document("secrets", "high_tier_key", "second-factor")
            .unwrap();
        assert_eq!(&*opened, b"top-secret-bytes");
    }

    #[test]
    fn no_plaintext_ever_hits_disk() {
        const MASTER_MARK: &[u8] = b"MASTER_PLAINTEXT_MARKER_zzz";
        const SEALED_MARK: &[u8] = b"SEALED_PLAINTEXT_MARKER_qqq";
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path.clone(), "master".into()).unwrap();
        v.put_document("config", "m", MASTER_MARK.to_vec()).unwrap();
        v.seal_document("secrets", "s", SEALED_MARK, "second").unwrap();

        // The on-disk file must contain NEITHER plaintext — master docs are
        // outer-encrypted, sealed docs are double-encrypted.
        let raw = std::fs::read(&path).unwrap();
        assert!(!contains(&raw, MASTER_MARK), "master plaintext leaked to disk");
        assert!(!contains(&raw, SEALED_MARK), "sealed plaintext leaked to disk");
    }

    #[test]
    fn subvault_is_recursive_and_independently_locked() {
        let (_dir, path) = temp_path();
        let mut v = Vault::init(path.clone(), "master".into()).unwrap();

        // Build a nested vault in memory and seal it under its own credential.
        let mut sub = VaultData::default();
        sub.entries.push(VaultEntry::new("inner_key", "inner_secret"));
        v.put_subvault("nested", "hub_state", &sub, "sub-cred").unwrap();

        let v2 = Vault::open(path, "master".into()).unwrap();
        // Wrong credential → no access to the sub-vault.
        assert!(v2.open_subvault("nested", "hub_state", "master").is_err());
        // Correct credential → the nested vault opens in memory.
        let opened = v2.open_subvault("nested", "hub_state", "sub-cred").unwrap();
        assert_eq!(opened.entries.len(), 1);
        assert_eq!(opened.entries[0].name, "inner_key");
        assert_eq!(opened.entries[0].secret, "inner_secret");
    }

    fn contains(haystack: &[u8], needle: &[u8]) -> bool {
        haystack.windows(needle.len()).any(|w| w == needle)
    }
}
