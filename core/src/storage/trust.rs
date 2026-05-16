//! Trust state persistence — thin wrapper around `web4-trust-core`'s
//! `FileStore`. Each plugin gets one `EntityTrust` JSON file under
//! `<HESTIA_HOME>/trust/`.
//!
//! Hestia stores trust by plugin_id with a `plugin:` prefix so it slots
//! into the Web4 entity-type taxonomy (`mcp:`, `lct:`, `role:`, etc).

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use web4_trust_core::storage::{FileStore, TrustStore as Web4TrustStore};
use web4_trust_core::EntityTrust;

/// Wraps the Web4 `FileStore` and routes plugin_id ↔ entity_id.
pub struct TrustStore {
    inner: FileStore,
    base_dir: PathBuf,
}

impl TrustStore {
    /// Open or create a trust store rooted at `base_dir`.
    pub fn open(base_dir: impl AsRef<Path>) -> Result<Self> {
        let base_dir = base_dir.as_ref().to_path_buf();
        let inner = FileStore::new(&base_dir)
            .map_err(|e| anyhow::anyhow!("opening trust store at {}: {}", base_dir.display(), e))?;
        Ok(Self { inner, base_dir })
    }

    pub fn base_dir(&self) -> &Path {
        &self.base_dir
    }

    fn entity_id(plugin_id: &str) -> String {
        // The plugin_id may already include a type prefix (e.g. "mcp:openclaw");
        // pass it through if it does, otherwise namespace it.
        if plugin_id.contains(':') {
            plugin_id.to_string()
        } else {
            format!("plugin:{plugin_id}")
        }
    }

    /// Fetch (or auto-create) the entity trust for a plugin.
    pub fn get(&self, plugin_id: &str) -> Result<EntityTrust> {
        let id = Self::entity_id(plugin_id);
        self.inner
            .get(&id)
            .with_context(|| format!("reading trust for {id}"))
    }

    /// Apply an outcome and persist. Returns the updated entity trust.
    pub fn update(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
    ) -> Result<EntityTrust> {
        let id = Self::entity_id(plugin_id);
        self.inner
            .update(&id, success, magnitude)
            .with_context(|| format!("updating trust for {id}"))
    }

    /// List known plugin_ids (without the `plugin:` prefix when applicable).
    pub fn list(&self) -> Result<Vec<String>> {
        let ids = self.inner.list(None).map_err(|e| anyhow::anyhow!("listing trust: {e}"))?;
        Ok(ids
            .into_iter()
            .map(|id| id.strip_prefix("plugin:").unwrap_or(&id).to_string())
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn outcome_updates_persist_across_reopen() {
        let dir = TempDir::new().unwrap();

        let store = TrustStore::open(dir.path()).unwrap();
        let t0 = store.get("claude-code").unwrap();
        assert_eq!(t0.action_count, 0);

        let t1 = store.update("claude-code", true, 0.8).unwrap();
        assert_eq!(t1.action_count, 1);
        assert_eq!(t1.success_count, 1);

        let t2 = store.update("claude-code", false, 0.5).unwrap();
        assert_eq!(t2.action_count, 2);
        assert_eq!(t2.success_count, 1);
        assert!(t2.t3.training >= 0.0 && t2.t3.training <= 1.0);

        drop(store);
        let reopened = TrustStore::open(dir.path()).unwrap();
        let t3 = reopened.get("claude-code").unwrap();
        assert_eq!(t3.action_count, 2);
        assert_eq!(t3.success_count, 1);
    }

    #[test]
    fn distinct_plugins_have_distinct_trust() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path()).unwrap();
        store.update("alice", true, 0.6).unwrap();
        store.update("bob", false, 0.6).unwrap();

        let a = store.get("alice").unwrap();
        let b = store.get("bob").unwrap();
        assert_eq!(a.action_count, 1);
        assert_eq!(b.action_count, 1);
        assert_eq!(a.success_count, 1);
        assert_eq!(b.success_count, 0);
        assert!(a.t3.training > b.t3.training);

        let listed = store.list().unwrap();
        assert_eq!(listed.len(), 2);
        assert!(listed.contains(&"alice".to_string()));
        assert!(listed.contains(&"bob".to_string()));
    }

    #[test]
    fn typed_entity_ids_pass_through() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path()).unwrap();
        store.update("mcp:openclaw", true, 0.5).unwrap();
        let listed = store.list().unwrap();
        // entity_id was "mcp:openclaw" — list() strips only the "plugin:" prefix.
        assert!(listed.contains(&"mcp:openclaw".to_string()));
    }
}
