//! Trust state persistence — per-entity `EntityTrust`, each **sealed at rest**.
//!
//! Each plugin gets one file under `<HESTIA_HOME>/trust/` named by a hash of
//! its entity id; the file content (the `EntityTrust` JSON) is encrypted with
//! the stable storage key (vault doctrine — no plaintext state). Reuses
//! `web4-trust-core`'s `EntityTrust` math (`update_from_outcome`); only the I/O
//! is local + sealed (so we don't depend on the upstream FileStore's plaintext
//! writes). A legacy plaintext file is read transparently and re-sealed on the
//! next write.
//!
//! Hestia stores trust by plugin_id with a `plugin:` prefix so it slots into
//! the Web4 entity-type taxonomy (`mcp:`, `lct:`, `role:`, etc).

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use web4_core::vault::crypto::{self, DerivedKey};
use web4_trust_core::EntityTrust;

/// Per-entity sealed trust store.
pub struct TrustStore {
    base_dir: PathBuf,
    key: [u8; 32],
}

impl TrustStore {
    /// Open (create) a sealed trust store rooted at `base_dir`, keyed by the
    /// stable storage key.
    pub fn open(base_dir: impl AsRef<Path>, key: [u8; 32]) -> Result<Self> {
        let base_dir = base_dir.as_ref().to_path_buf();
        std::fs::create_dir_all(&base_dir)
            .with_context(|| format!("creating trust dir {}", base_dir.display()))?;
        Ok(Self { base_dir, key })
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

    /// File for an entity id — named by a hash, content sealed.
    fn entity_file(&self, entity_id: &str) -> PathBuf {
        let hash = format!("{:x}", Sha256::digest(entity_id.as_bytes()));
        self.base_dir.join(format!("{}.json", &hash[..16]))
    }

    fn dk(&self) -> DerivedKey {
        DerivedKey::from_bytes(self.key)
    }

    /// Read + decrypt one entity file. Sniffs a legacy plaintext JSON (`{`) vs a
    /// sealed blob. `None` if the file is absent.
    fn load(&self, entity_id: &str) -> Result<Option<EntityTrust>> {
        let path = self.entity_file(entity_id);
        if !path.exists() {
            return Ok(None);
        }
        let raw = std::fs::read(&path).with_context(|| format!("reading trust {}", path.display()))?;
        let json: Vec<u8> = if raw.first() == Some(&b'{') {
            raw // legacy plaintext JSON
        } else {
            crypto::open(&self.dk(), &raw).context("decrypting trust file")?
        };
        let trust: EntityTrust =
            serde_json::from_slice(&json).with_context(|| format!("parsing trust {}", path.display()))?;
        Ok(Some(trust))
    }

    /// Seal + write one entity's trust.
    fn store(&self, trust: &EntityTrust) -> Result<()> {
        let json = serde_json::to_vec_pretty(trust).context("serializing trust")?;
        let sealed = crypto::seal(&self.dk(), &json).context("sealing trust")?;
        let path = self.entity_file(&trust.entity_id);
        std::fs::write(&path, sealed).with_context(|| format!("writing trust {}", path.display()))?;
        Ok(())
    }

    /// Fetch (or auto-create) the entity trust for a plugin.
    pub fn get(&self, plugin_id: &str) -> Result<EntityTrust> {
        let id = Self::entity_id(plugin_id);
        match self.load(&id)? {
            Some(t) => Ok(t),
            None => {
                let t = EntityTrust::new(&id);
                self.store(&t)?;
                Ok(t)
            }
        }
    }

    /// Apply an outcome and persist. Returns the updated entity trust.
    pub fn update(&self, plugin_id: &str, success: bool, magnitude: f64) -> Result<EntityTrust> {
        let mut t = self.get(plugin_id)?;
        t.update_from_outcome(success, magnitude);
        self.store(&t)?;
        Ok(t)
    }

    /// List known plugin_ids (without the `plugin:` prefix when applicable).
    /// The filename is a hash, so we read each file to recover its entity id.
    pub fn list(&self) -> Result<Vec<String>> {
        let mut out = Vec::new();
        let rd = match std::fs::read_dir(&self.base_dir) {
            Ok(rd) => rd,
            Err(_) => return Ok(out),
        };
        for entry in rd.flatten() {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let Ok(raw) = std::fs::read(&path) else { continue };
            let json = if raw.first() == Some(&b'{') {
                raw
            } else {
                match crypto::open(&self.dk(), &raw) {
                    Ok(b) => b,
                    Err(_) => continue,
                }
            };
            if let Ok(t) = serde_json::from_slice::<EntityTrust>(&json) {
                out.push(t.entity_id.strip_prefix("plugin:").unwrap_or(&t.entity_id).to_string());
            }
        }
        out.sort();
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const KEY: [u8; 32] = [3u8; 32];

    #[test]
    fn outcome_updates_persist_across_reopen_sealed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.get("claude-code").unwrap().action_count, 0);
        store.update("claude-code", true, 0.8).unwrap();
        let t = store.update("claude-code", false, 0.5).unwrap();
        assert_eq!(t.action_count, 2);
        assert_eq!(t.success_count, 1);

        // On disk the file is sealed (not plaintext JSON).
        let f = store.entity_file(&TrustStore::entity_id("claude-code"));
        let raw = std::fs::read(&f).unwrap();
        assert_ne!(raw.first(), Some(&b'{'), "trust file should be sealed, not plaintext JSON");

        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        let t = reopened.get("claude-code").unwrap();
        assert_eq!(t.action_count, 2);
        assert_eq!(t.success_count, 1);
    }

    #[test]
    fn distinct_plugins_listed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.update("alice", true, 0.6).unwrap();
        store.update("bob", false, 0.6).unwrap();
        let listed = store.list().unwrap();
        assert_eq!(listed.len(), 2);
        assert!(listed.contains(&"alice".to_string()));
        assert!(listed.contains(&"bob".to_string()));
    }

    #[test]
    fn legacy_plaintext_is_read_then_resealed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        // Write a plaintext trust file as an old install would.
        let t = EntityTrust::new("plugin:legacy");
        let f = store.entity_file("plugin:legacy");
        std::fs::write(&f, serde_json::to_vec_pretty(&t).unwrap()).unwrap();
        assert_eq!(std::fs::read(&f).unwrap().first(), Some(&b'{'));

        // get() reads the plaintext; update() re-seals it.
        assert_eq!(store.get("legacy").unwrap().action_count, 0);
        store.update("legacy", true, 0.5).unwrap();
        assert_ne!(std::fs::read(&f).unwrap().first(), Some(&b'{'), "should be re-sealed after write");
    }
}
