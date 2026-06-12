//! Shared server state — vault, sessions, in-flight actions, witness chain,
//! and trust store.
//!
//! Persistence (Session 3):
//! - witness chain → SQLite (`<HESTIA_HOME>/witness.db`)
//! - trust         → JSON per entity under `<HESTIA_HOME>/trust/`
//!
//! Sessions and in-flight actions are intentionally RAM-only: a daemon
//! restart should invalidate sessions, and plugins must reconnect.

use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;
use web4_trust_core::EntityTrust;

use crate::storage::{ChainEntry, SqliteChainStore, TrustStore};
use crate::vault::Vault;

/// Active plugin session, created on `hestia_connect`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub session_id: Uuid,
    pub plugin_id: String,
    pub plugin_version: Option<String>,
    pub host_agent: String,
    pub host_agent_version: Option<String>,
    pub assigned_role: String,
    pub soft_lct: String,
    pub connected_at: DateTime<Utc>,
}

/// In-flight R6 action.
#[derive(Debug, Clone)]
pub struct InFlightAction {
    pub action_id: Uuid,
    pub session_id: Uuid,
    pub tool_name: String,
    pub target: Option<String>,
    /// Raw tool input arguments captured at begin_action time. Used by
    /// query_policy to match against `command_patterns` and similar
    /// rules that need the full call context.
    pub parameters: Option<serde_json::Value>,
    pub started_at: DateTime<Utc>,
    pub chain_position: u64,
}

/// The mutable core state passed to every request handler.
pub struct ServerState {
    pub vault: Vault,
    pub sessions: HashMap<Uuid, Session>,
    pub actions: HashMap<Uuid, InFlightAction>,
    pub chain_store: SqliteChainStore,
    pub trust_store: TrustStore,
    pub sovereign_lct: String,
    pub shared_context: serde_json::Map<String, serde_json::Value>,
    pub policy_engine: crate::policy::PolicyEngine,
    /// Plugin IDs that self-declared as synthetic (test harnesses,
    /// fuzzers, etc.). Excluded from operator-facing aggregations by
    /// default. Persisted in `<HESTIA_HOME>/synthetic.json`.
    pub synthetic_plugins: HashSet<String>,
    synthetic_path: PathBuf,
    pub home: PathBuf,
    /// Single-use OID4VCI `c_nonce`s issued but not yet redeemed.
    pub vci_nonces: HashSet<String>,
}

impl ServerState {
    /// Open all persistent stores rooted at `home` and prepare server state.
    pub fn open(vault: Vault, home: &Path) -> Result<Self> {
        let chain_store = SqliteChainStore::open(home.join("witness.db"))?;
        let trust_store = TrustStore::open(home.join("trust"))?;
        let sovereign_lct = "lct:web4:hestia:sovereign:phase1-placeholder".to_string();
        // Resolve the active policy from the vault. Falls back to the
        // safety preset if the vault's named preset isn't built-in.
        let policy_config = vault
            .policy()
            .resolve()
            .unwrap_or_else(|| crate::policy::get_preset("safety").unwrap().config);
        let policy_engine = crate::policy::PolicyEngine::new(policy_config);

        let synthetic_path = home.join("synthetic.json");
        let synthetic_plugins = load_synthetic_set(&synthetic_path);

        Ok(Self {
            vault,
            sessions: HashMap::new(),
            actions: HashMap::new(),
            chain_store,
            trust_store,
            sovereign_lct,
            shared_context: serde_json::Map::new(),
            policy_engine,
            synthetic_plugins,
            synthetic_path,
            home: home.to_path_buf(),
            vci_nonces: HashSet::new(),
        })
    }

    /// Mark a plugin_id as synthetic and persist. Idempotent; returns
    /// `true` if this call added a new entry.
    pub fn mark_synthetic(&mut self, plugin_id: &str) -> bool {
        let added = self.synthetic_plugins.insert(plugin_id.to_string());
        if added {
            // Best-effort persist; we don't fail the request on disk errors.
            let _ = save_synthetic_set(&self.synthetic_path, &self.synthetic_plugins);
        }
        added
    }

    pub fn is_synthetic(&self, plugin_id: &str) -> bool {
        self.synthetic_plugins.contains(plugin_id)
    }

    /// Re-build the policy engine from the vault's current state. Call
    /// after `vault.set_active_preset` or any policy mutation.
    pub fn reload_policy(&mut self) {
        let config = self
            .vault
            .policy()
            .resolve()
            .unwrap_or_else(|| crate::policy::get_preset("safety").unwrap().config);
        self.policy_engine = crate::policy::PolicyEngine::new(config);
    }

    /// Issue a Soft LCT for a new session.
    pub fn issue_soft_lct(&self, session_id: Uuid) -> String {
        let mut hasher = Sha256::new();
        hasher.update(session_id.as_bytes());
        hasher.update(self.sovereign_lct.as_bytes());
        let digest = hasher.finalize();
        let hex: String = digest[..8].iter().map(|b| format!("{:02x}", b)).collect();
        format!("lct:web4:session:{}", hex)
    }

    /// Append a chain entry under the sovereign LCT.
    pub fn append_chain(
        &self,
        event_type: &str,
        event_data: serde_json::Value,
    ) -> Result<ChainEntry> {
        self.chain_store
            .append(event_type, event_data, &self.sovereign_lct)
    }

    pub fn chain_len(&self) -> u64 {
        self.chain_store.len().unwrap_or(0)
    }

    pub fn recent_chain(&self, limit: u64) -> Vec<ChainEntry> {
        self.chain_store.read_recent(limit).unwrap_or_default()
    }

    /// Apply an outcome to the trust state for a plugin.
    pub fn apply_outcome(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
    ) -> Result<EntityTrust> {
        self.trust_store.update(plugin_id, success, magnitude)
    }

    pub fn trust(&self, plugin_id: &str) -> EntityTrust {
        self.trust_store
            .get(plugin_id)
            .unwrap_or_else(|_| EntityTrust::new(format!("plugin:{plugin_id}")))
    }

    pub fn trust_count(&self) -> usize {
        self.trust_store.list().map(|v| v.len()).unwrap_or(0)
    }

    /// Resolve a plugin_id from a session_id provided in tool args.
    /// Falls back to the most-recently-connected session if `session_id`
    /// is absent (this fallback is the Session-2-era behavior and will
    /// be removed once both SDKs reliably pass session_id in args).
    pub fn resolve_plugin_id(&self, session_id: Option<&str>) -> Option<String> {
        if let Some(sid) = session_id {
            if let Ok(uuid) = Uuid::parse_str(sid) {
                if let Some(s) = self.sessions.get(&uuid) {
                    return Some(s.plugin_id.clone());
                }
            }
            return None;
        }
        self.sessions
            .values()
            .max_by_key(|sess| sess.connected_at)
            .map(|sess| sess.plugin_id.clone())
    }
}

pub type SharedState = Arc<Mutex<ServerState>>;

fn load_synthetic_set(path: &Path) -> HashSet<String> {
    let bytes = match fs::read(path) {
        Ok(b) => b,
        Err(_) => return HashSet::new(),
    };
    let ids: Vec<String> = serde_json::from_slice(&bytes).unwrap_or_default();
    ids.into_iter().collect()
}

fn save_synthetic_set(path: &Path, set: &HashSet<String>) -> Result<()> {
    let mut ids: Vec<&String> = set.iter().collect();
    ids.sort();
    let bytes = serde_json::to_vec_pretty(&ids)?;
    fs::write(path, bytes)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_state() -> (TempDir, ServerState) {
        let dir = TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path()).unwrap();
        (dir, state)
    }

    #[test]
    fn chain_grows_with_hash_linkage() {
        let (_dir, state) = make_state();
        let e1 = state.append_chain("evt1", serde_json::json!({"a": 1})).unwrap();
        let e2 = state.append_chain("evt2", serde_json::json!({"b": 2})).unwrap();
        assert_eq!(e1.prev_hash, "0".repeat(64));
        assert_eq!(e2.prev_hash, e1.hash);
        assert_eq!(e1.chain_position, 0);
        assert_eq!(e2.chain_position, 1);
        assert_eq!(state.chain_len(), 2);
    }

    #[test]
    fn trust_evolves_with_outcomes() {
        let (_dir, state) = make_state();
        let t1 = state.apply_outcome("plug-1", true, 0.8).unwrap();
        assert_eq!(t1.action_count, 1);
        assert_eq!(t1.success_count, 1);
        let t2 = state.apply_outcome("plug-1", false, 0.8).unwrap();
        assert_eq!(t2.action_count, 2);
        assert_eq!(t2.success_count, 1);
    }

    #[test]
    fn issue_soft_lct_is_deterministic_given_inputs() {
        let (_dir, state) = make_state();
        let sid = Uuid::new_v4();
        let l1 = state.issue_soft_lct(sid);
        let l2 = state.issue_soft_lct(sid);
        assert_eq!(l1, l2);
        assert!(l1.starts_with("lct:web4:session:"));
    }

    #[test]
    fn synthetic_set_persists_across_reopen() {
        let dir = TempDir::new().unwrap();
        let vault_path = dir.path().join("v.enc");

        {
            let vault = Vault::init(vault_path.clone(), "p".into()).unwrap();
            let mut state = ServerState::open(vault, dir.path()).unwrap();
            assert!(state.mark_synthetic("conformance-runner"));
            assert!(state.mark_synthetic("conformance-runner-py"));
            // Re-marking the same id is a no-op.
            assert!(!state.mark_synthetic("conformance-runner"));
            assert!(state.is_synthetic("conformance-runner"));
            assert!(!state.is_synthetic("claude-code"));
        }

        // Reopen with the same home — synthetic set is restored from disk.
        let vault = Vault::open(vault_path.clone(), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path()).unwrap();
        assert!(state.is_synthetic("conformance-runner"));
        assert!(state.is_synthetic("conformance-runner-py"));
        assert!(!state.is_synthetic("claude-code"));
        assert_eq!(state.synthetic_plugins.len(), 2);
    }

    #[test]
    fn resolve_plugin_id_uses_session_id_when_provided() {
        let (_dir, mut state) = make_state();
        let sid_a = Uuid::new_v4();
        let sid_b = Uuid::new_v4();
        state.sessions.insert(
            sid_a,
            Session {
                session_id: sid_a,
                plugin_id: "alice".into(),
                plugin_version: None,
                host_agent: "x".into(),
                host_agent_version: None,
                assigned_role: "citizen".into(),
                soft_lct: "lct:test:a".into(),
                connected_at: Utc::now(),
            },
        );
        state.sessions.insert(
            sid_b,
            Session {
                session_id: sid_b,
                plugin_id: "bob".into(),
                plugin_version: None,
                host_agent: "x".into(),
                host_agent_version: None,
                assigned_role: "citizen".into(),
                soft_lct: "lct:test:b".into(),
                connected_at: Utc::now() + chrono::Duration::seconds(1),
            },
        );

        assert_eq!(
            state.resolve_plugin_id(Some(&sid_a.to_string())),
            Some("alice".into())
        );
        // fallback to most-recent when session_id is absent
        assert_eq!(state.resolve_plugin_id(None), Some("bob".into()));
        // unknown session_id resolves to None (no fallback)
        assert_eq!(state.resolve_plugin_id(Some("00000000-0000-0000-0000-000000000000")), None);
    }
}
