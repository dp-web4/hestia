//! Shared server state — vault, sessions, in-flight actions, witness chain.
//!
//! Persistent storage of the witness chain comes in Session 3; for now the
//! chain lives in memory. The vault is loaded once at server start (passphrase
//! prompted) and stays unlocked while the server runs.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;

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
    pub started_at: DateTime<Utc>,
    pub chain_position: u64,
}

/// Witness chain entry (in-memory; Session 3 adds persistence).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChainEntry {
    pub hash: String,
    pub prev_hash: String,
    pub timestamp: DateTime<Utc>,
    pub event_type: String,
    pub event_data: serde_json::Value,
    pub signer_lct: String,
    pub chain_position: u64,
}

/// Per-agent trust state. Session 3 plugs in web4-trust-core; for now,
/// this struct is enough to roll the SDK's TrustState contract.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTrust {
    pub t3_talent: f64,
    pub t3_training: f64,
    pub t3_temperament: f64,
    pub v3_valuation: f64,
    pub v3_veracity: f64,
    pub v3_validity: f64,
    pub level: String,
    pub action_count: u64,
    pub last_action_at: Option<DateTime<Utc>>,
}

impl Default for AgentTrust {
    fn default() -> Self {
        Self {
            t3_talent: 0.5,
            t3_training: 0.5,
            t3_temperament: 0.5,
            v3_valuation: 0.5,
            v3_veracity: 0.5,
            v3_validity: 0.5,
            level: "medium".to_string(),
            action_count: 0,
            last_action_at: None,
        }
    }
}

impl AgentTrust {
    /// Update T3/V3 from an outcome. Phase 1 placeholder math; Session 3 swaps
    /// in the proper web4-trust-core evolution.
    pub fn apply_outcome(&mut self, success: bool, magnitude: f64) {
        let m = magnitude.clamp(0.0, 1.0);
        let delta = m * 0.05 * if success { 1.0 } else { -1.0 };
        self.t3_talent = (self.t3_talent + delta).clamp(0.0, 1.0);
        self.t3_training = (self.t3_training + delta * 0.7).clamp(0.0, 1.0);
        self.t3_temperament = (self.t3_temperament + delta * 0.5).clamp(0.0, 1.0);
        self.v3_valuation = (self.v3_valuation + delta * 0.3).clamp(0.0, 1.0);
        self.v3_veracity = (self.v3_veracity + delta * 0.4).clamp(0.0, 1.0);
        self.v3_validity = (self.v3_validity + delta * 0.2).clamp(0.0, 1.0);
        self.action_count += 1;
        self.last_action_at = Some(Utc::now());
        self.level = level_for((self.t3_talent + self.t3_training + self.t3_temperament) / 3.0);
    }

    pub fn days_since_last(&self) -> f64 {
        match self.last_action_at {
            None => 0.0,
            Some(t) => {
                let secs = (Utc::now() - t).num_seconds().max(0) as f64;
                secs / 86_400.0
            }
        }
    }
}

fn level_for(avg: f64) -> String {
    if avg < 0.2 {
        "low"
    } else if avg < 0.4 {
        "medium_low"
    } else if avg < 0.6 {
        "medium"
    } else if avg < 0.8 {
        "medium_high"
    } else {
        "high"
    }
    .to_string()
}

/// The mutable core state passed to every request handler.
pub struct ServerState {
    pub vault: Vault,
    pub sessions: HashMap<Uuid, Session>,
    pub actions: HashMap<Uuid, InFlightAction>,
    pub chain: Vec<ChainEntry>,
    pub trust_states: HashMap<String, AgentTrust>, // keyed by plugin_id
    pub sovereign_lct: String,
    pub shared_context: serde_json::Map<String, serde_json::Value>,
}

impl ServerState {
    pub fn new(vault: Vault) -> Self {
        // For Phase 1, use a deterministic placeholder sovereign LCT. Session 3
        // bootstraps a real Web4 society identity.
        let sovereign_lct = "lct:web4:hestia:sovereign:phase1-placeholder".to_string();
        Self {
            vault,
            sessions: HashMap::new(),
            actions: HashMap::new(),
            chain: Vec::new(),
            trust_states: HashMap::new(),
            sovereign_lct,
            shared_context: serde_json::Map::new(),
        }
    }

    /// Issue a Soft LCT for a new session.
    pub fn issue_soft_lct(&self, session_id: Uuid) -> String {
        let mut hasher = Sha256::new();
        hasher.update(session_id.as_bytes());
        hasher.update(self.sovereign_lct.as_bytes());
        let digest = hasher.finalize();
        format!("lct:web4:session:{}", hex_short(&digest[..8]))
    }

    /// Append a chain entry and return the entry's hash. Hash is over
    /// prev_hash || timestamp_iso || event_type || event_data_json.
    pub fn append_chain(
        &mut self,
        event_type: &str,
        event_data: serde_json::Value,
    ) -> ChainEntry {
        let prev_hash = self
            .chain
            .last()
            .map(|e| e.hash.clone())
            .unwrap_or_else(|| "0".repeat(64));
        let timestamp = Utc::now();
        let chain_position = self.chain.len() as u64;

        let mut hasher = Sha256::new();
        hasher.update(prev_hash.as_bytes());
        hasher.update(timestamp.to_rfc3339().as_bytes());
        hasher.update(event_type.as_bytes());
        hasher.update(
            serde_json::to_string(&event_data)
                .unwrap_or_default()
                .as_bytes(),
        );
        let hash = hex(&hasher.finalize()[..]);

        let entry = ChainEntry {
            hash,
            prev_hash,
            timestamp,
            event_type: event_type.to_string(),
            event_data,
            signer_lct: self.sovereign_lct.clone(),
            chain_position,
        };
        self.chain.push(entry.clone());
        entry
    }

    /// Get or initialize trust state for a plugin.
    pub fn trust_mut(&mut self, plugin_id: &str) -> &mut AgentTrust {
        self.trust_states
            .entry(plugin_id.to_string())
            .or_insert_with(AgentTrust::default)
    }

    pub fn trust(&self, plugin_id: &str) -> AgentTrust {
        self.trust_states
            .get(plugin_id)
            .cloned()
            .unwrap_or_default()
    }
}

pub type SharedState = Arc<Mutex<ServerState>>;

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

fn hex_short(bytes: &[u8]) -> String {
    hex(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use crate::vault::Vault;

    fn make_state() -> (TempDir, ServerState) {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        let vault = Vault::init(path, "p".into()).unwrap();
        (dir, ServerState::new(vault))
    }

    #[test]
    fn chain_grows_with_hash_linkage() {
        let (_dir, mut state) = make_state();
        let e1 = state.append_chain("evt1", serde_json::json!({"a": 1}));
        let e2 = state.append_chain("evt2", serde_json::json!({"b": 2}));
        assert_eq!(e1.prev_hash, "0".repeat(64));
        assert_eq!(e2.prev_hash, e1.hash);
        assert_eq!(e1.chain_position, 0);
        assert_eq!(e2.chain_position, 1);
        assert_eq!(state.chain.len(), 2);
    }

    #[test]
    fn trust_evolves_with_outcomes() {
        let mut t = AgentTrust::default();
        let initial = t.t3_talent;
        t.apply_outcome(true, 0.8);
        assert!(t.t3_talent > initial);
        assert_eq!(t.action_count, 1);

        let after_success = t.t3_talent;
        t.apply_outcome(false, 0.8);
        assert!(t.t3_talent < after_success);
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
}
