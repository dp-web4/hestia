//! Shared server state — vault, sessions, in-flight actions, witness chain,
//! and trust store.
//!
//! Persistence (all encrypted at rest, vault doctrine):
//! - witness chain → SQLCipher (`<HESTIA_HOME>/witness.db`)
//! - trust         → per-entity, each sealed under `<HESTIA_HOME>/trust/`
//! Both keyed by one storage key derived from the vault passphrase.
//!
//! Sessions and in-flight actions are intentionally RAM-only: a daemon
//! restart should invalidate sessions, and plugins must reconnect.

use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
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
    /// Trust *tier* (citizen/…) — distinct from the constellation role below.
    pub assigned_role: String,
    /// The #403 *capacity* the session acts in (a canonical `role:constellation:*`
    /// from the published set), used as `role_lct` on witnessed events + emitted
    /// reputation deltas. Declared at `connect`, normalized fail-closed.
    pub constellation_role: String,
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
    /// The actor's stated reason for the action (the accountability WHY),
    /// captured at `begin_action` and stamped onto the witnessed `outcome`.
    /// `None` = unstated (honest — never fabricated).
    pub intent: Option<String>,
    /// The host agent's OWN stable session id (e.g. Claude Code's `session_id`),
    /// passed through from the hook — the real per-session audit grain, since a
    /// hestia session is minted per connect (per tool-call for the hook) and is
    /// not itself a stable per-orchestrator-session identifier. `None` = the host
    /// didn't supply one.
    pub host_session_id: Option<String>,
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
    /// Per-constellation-role policy engines (#403 role-scoped law), built from
    /// the vault's `role_overlays`. A session's declared role selects its engine;
    /// its verdict is folded into `policy_engine` by strictest-wins in
    /// `query_policy`, so a role can only tighten the base, never loosen it.
    pub role_policy_engines: HashMap<String, crate::policy::PolicyEngine>,
    /// Plugin IDs that self-declared as synthetic (test harnesses,
    /// fuzzers, etc.). Excluded from operator-facing aggregations by
    /// default. Enclosed in the vault (document `presence`/`synthetic`).
    pub synthetic_plugins: HashSet<String>,
    pub home: PathBuf,
    /// Single-use OID4VCI `c_nonce`s issued but not yet redeemed.
    pub vci_nonces: HashSet<String>,
}

impl ServerState {
    /// Open all persistent stores rooted at `home` and prepare server state.
    /// `passphrase` is the vault passphrase — used to derive the storage key
    /// that seals the witness chain + trust files.
    pub fn open(vault: Vault, home: &Path, passphrase: &str) -> Result<Self> {
        // One stable storage key (Argon2 once) seals both the witness chain
        // (SQLCipher) and the trust files.
        let store_key = crate::storage::storage_key(home, passphrase)
            .map_err(|e| anyhow::anyhow!("deriving storage key: {e}"))?;
        let chain_store = SqliteChainStore::open(home.join("witness.db"), store_key)?;
        let trust_store = TrustStore::open(home.join("trust"), store_key)?;
        let sovereign_lct = "lct:web4:hestia:sovereign:phase1-placeholder".to_string();
        // Resolve the active policy from the vault. Falls back to the
        // safety preset if the vault's named preset isn't built-in.
        let policy_config = vault
            .policy()
            .resolve()
            .unwrap_or_else(|| crate::policy::get_preset("safety").unwrap().config);
        let policy_engine = crate::policy::PolicyEngine::new(policy_config);
        // Per-role overlay engines (#403). Empty unless the vault declares
        // `role_overlays`; each is folded strictest-wins into the base.
        let role_policy_engines = vault
            .policy()
            .role_configs()
            .into_iter()
            .map(|(role, cfg)| (role, crate::policy::PolicyEngine::new(cfg)))
            .collect();

        // Synthetic-plugin set lives in the vault (migrating a legacy
        // synthetic.json). Best-effort: an empty set on any read error.
        let synthetic_plugins: HashSet<String> =
            crate::vault::load_doc(&vault, "presence", "synthetic", "synthetic.json")
                .unwrap_or_default();

        Ok(Self {
            vault,
            sessions: HashMap::new(),
            actions: HashMap::new(),
            chain_store,
            trust_store,
            sovereign_lct,
            shared_context: serde_json::Map::new(),
            policy_engine,
            role_policy_engines,
            synthetic_plugins,
            home: home.to_path_buf(),
            vci_nonces: HashSet::new(),
        })
    }

    /// Mark a plugin_id as synthetic and persist. Idempotent; returns
    /// `true` if this call added a new entry.
    pub fn mark_synthetic(&mut self, plugin_id: &str) -> bool {
        let added = self.synthetic_plugins.insert(plugin_id.to_string());
        if added {
            // Best-effort persist into the vault; don't fail the request on
            // a disk/encrypt error.
            let _ = crate::vault::save_doc(
                &mut self.vault,
                "presence",
                "synthetic",
                "synthetic.json",
                &self.synthetic_plugins,
            );
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
        self.role_policy_engines = self
            .vault
            .policy()
            .role_configs()
            .into_iter()
            .map(|(role, cfg)| (role, crate::policy::PolicyEngine::new(cfg)))
            .collect();
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

    /// Resolve a durable **member LCT** for a plugin, for use as `subject_lct`
    /// on an emitted `ReputationDelta` (the `repemit-1` LCT-mapping). Fail-closed:
    /// returns `None` for any plugin that must not have reputation reported to the
    /// hub — synthetic/test plugins and malformed ids — so no un-mappable
    /// `plugin:` string ever reaches the emit path.
    ///
    /// The LCT is derived deterministically from the **durable** `plugin_id`
    /// bound to hestia's sovereign LCT — mirroring `issue_soft_lct`, but keyed on
    /// the stable plugin identity rather than the ephemeral session, so a given
    /// member has ONE member LCT across all its sessions. The plugin never
    /// supplies its own LCT: hestia mints it, so a member cannot forge a foreign
    /// `subject`. For v1 the hub trusts hestia's sovereign to attest its own
    /// constellation's members; v2's constellation-publish makes membership
    /// independently attestable and removes that residual trust.
    pub fn member_lct(&self, plugin_id: &str) -> Option<String> {
        let id = plugin_id.trim();
        if id.is_empty() || self.is_synthetic(id) {
            return None; // fail-closed: no emit for unmapped / synthetic members
        }
        let mut hasher = Sha256::new();
        hasher.update(b"web4:member:");
        hasher.update(id.as_bytes());
        hasher.update(self.sovereign_lct.as_bytes());
        let digest = hasher.finalize();
        let hex: String = digest[..12].iter().map(|b| format!("{:02x}", b)).collect();
        Some(format!("lct:web4:member:{hex}"))
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
        let ctx = crate::reputation::RepContext {
            role_lct: crate::reputation::V1_CONSTELLATION_ROLE,
            action_type: "outcome",
            action_target: "",
            action_id: "",
            reason: if success { "outcome:success" } else { "outcome:failure" },
        };
        self.apply_outcome_ctx(plugin_id, success, magnitude, &ctx)
    }

    /// Apply an outcome AND emit the trust movement as a role-scoped
    /// `web4_core::r6::ReputationDelta` to the local sink — the local half of the
    /// trust-tensor bridge (P3a; `designs/2026-07-01-trust-tensor-bridge.md`).
    /// The delta is the exact before/after diff, ready to emit to the hub §5.3
    /// projection once a member-emit path exists.
    pub fn apply_outcome_ctx(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
        ctx: &crate::reputation::RepContext,
    ) -> Result<EntityTrust> {
        // Trust accrues to the #403 (instance, role) grain, NOT the plugin type.
        // Before this, a mesh-worker's failures and an interactive session's
        // successes both landed on one `plugin:claude-code` entity — the deltas
        // were role-scoped but the trust generating them was not. Keying the
        // store on the (instance_lct, role_lct) pair closes that seam: a role's
        // reputation is its own, and can't be diluted or poisoned by another
        // capacity of the same instance.
        let trust_key = self.trust_entity_key(plugin_id, ctx.role_lct);
        let (before, after) =
            self.trust_store
                .update_returning_prior(&trust_key, success, magnitude)?;
        // LCT-mapping (sequence head, `repemit-1`): resolve the durable member
        // LCT for `plugin_id` before building the delta, so `subject_lct` is a
        // ground-truth member identity minted under hestia's sovereign — never
        // the raw `plugin:` string. Fail-closed: an unmapped plugin (synthetic
        // or malformed) yields `None` and emits NO delta, so test harnesses
        // never pollute the hub's reputation view and no un-mappable id reaches
        // the emit path. Local trust bookkeeping above still runs for everyone.
        if let Some(subject_lct) = self.member_lct(plugin_id) {
            if let Some(delta) = crate::reputation::delta_from_change(
                &subject_lct,
                ctx,
                &before,
                &after,
                chrono::Utc::now(),
            ) {
                crate::reputation::log_delta(&self.reputation_sink(), &delta);
            }
        }
        Ok(after)
    }

    /// Local sink for emitted reputation deltas — the ready-to-emit queue and a
    /// `calib`-ready reputation stream (`<home>/reputation-deltas.jsonl`).
    pub fn reputation_sink(&self) -> std::path::PathBuf {
        self.home.join(crate::reputation::SINK_FILE)
    }

    /// The durable trust-store key: the #403 `(instance_lct, role_lct)` grain.
    /// A mapped plugin keys on `<instance_lct>#<role_lct>` — the (subject, role)
    /// pair the hub fold also scopes on. An unmapped / synthetic plugin (no member
    /// LCT — it never emits) still gets a role-scoped local key so bookkeeping
    /// stays coherent. Old `plugin:<id>` trust blobs are legacy: they carried the
    /// degenerate all-sessions-smeared-together grain, so role-scoped trust starts
    /// fresh here rather than migrating that saturated history forward.
    pub fn trust_entity_key(&self, plugin_id: &str, role_lct: &str) -> String {
        match self.member_lct(plugin_id) {
            Some(instance_lct) => format!("{instance_lct}#{role_lct}"),
            None => format!("plugin:{plugin_id}#{role_lct}"),
        }
    }

    /// Read the trust for a specific `(instance, role)` grain.
    pub fn trust_for_role(&self, plugin_id: &str, role_lct: &str) -> EntityTrust {
        let key = self.trust_entity_key(plugin_id, role_lct);
        self.trust_store
            .get(&key)
            .unwrap_or_else(|_| EntityTrust::new(key))
    }

    /// Read trust for a plugin in the default (member) capacity. Retained for the
    /// non-role-aware call sites (dashboard/tests); role-aware reads should use
    /// [`trust_for_role`].
    pub fn trust(&self, plugin_id: &str) -> EntityTrust {
        self.trust_for_role(plugin_id, crate::reputation::DEFAULT_CONSTELLATION_ROLE)
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



#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_state() -> (TempDir, ServerState) {
        let dir = TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path(), "p").unwrap();
        (dir, state)
    }

    fn ctx_for(role: &'static str) -> crate::reputation::RepContext<'static> {
        crate::reputation::RepContext {
            role_lct: role,
            action_type: "outcome",
            action_target: "",
            action_id: "",
            reason: "outcome:failure",
        }
    }

    /// The re-key: one instance acting in TWO roles accrues trust INDEPENDENTLY.
    /// A mesh-worker's failures must not dilute the interactive-dev reputation of
    /// the same plugin instance (the seam this closes).
    #[test]
    fn trust_is_scoped_per_instance_role_not_per_plugin() {
        let (_dir, state) = make_state();
        let mw = "role:constellation:mesh-worker";
        let dev = "role:constellation:interactive-dev";
        // Same plugin, mesh-worker role: two failures.
        state.apply_outcome_ctx("claude-code", false, 0.8, &ctx_for(mw)).unwrap();
        let mw_trust = state.apply_outcome_ctx("claude-code", false, 0.8, &ctx_for(mw)).unwrap();
        // Same plugin, interactive-dev role: one success.
        let dev_trust = state
            .apply_outcome_ctx("claude-code", true, 0.8, &crate::reputation::RepContext {
                reason: "outcome:success", ..ctx_for(dev)
            })
            .unwrap();
        // Distinct entities: the two roles carry different entity_ids + scores.
        assert_ne!(mw_trust.entity_id, dev_trust.entity_id);
        assert!(mw_trust.entity_id.ends_with(mw), "got {}", mw_trust.entity_id);
        assert!(dev_trust.entity_id.ends_with(dev), "got {}", dev_trust.entity_id);
        // The mesh-worker's failures did not touch the dev role's trust.
        assert!(dev_trust.talent() > mw_trust.talent(),
            "dev(success) {} must outrank mesh-worker(2 failures) {}",
            dev_trust.talent(), mw_trust.talent());
        // Same instance underlies both (the shared member LCT prefix).
        let inst = state.member_lct("claude-code").unwrap();
        assert!(mw_trust.entity_id.starts_with(&inst));
        assert!(dev_trust.entity_id.starts_with(&inst));
        // Re-reading by role recovers the same accrued entity.
        assert_eq!(state.trust_for_role("claude-code", mw).entity_id, mw_trust.entity_id);
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
    fn member_lct_is_stable_per_plugin_and_distinct_across_plugins() {
        let (_dir, state) = make_state();
        // Same plugin -> same member LCT (stable across sessions), well-formed.
        let a1 = state.member_lct("alice").unwrap();
        let a2 = state.member_lct("alice").unwrap();
        assert_eq!(a1, a2);
        assert!(a1.starts_with("lct:web4:member:"));
        // Distinct plugins -> distinct member LCTs; neither leaks the raw id.
        let b = state.member_lct("bob").unwrap();
        assert_ne!(a1, b);
        assert!(!a1.contains("alice") && !b.contains("bob"));
    }

    #[test]
    fn member_lct_fails_closed_for_synthetic_and_empty() {
        let (_dir, mut state) = make_state();
        assert!(state.mark_synthetic("conformance-runner"));
        // Synthetic plugins never map -> no delta will be emitted for them.
        assert!(state.member_lct("conformance-runner").is_none());
        // Malformed / empty ids also fail closed.
        assert!(state.member_lct("").is_none());
        assert!(state.member_lct("   ").is_none());
        // A real member still maps.
        assert!(state.member_lct("claude-code").is_some());
    }

    #[test]
    fn emit_uses_member_lct_not_raw_plugin_id_and_skips_synthetic() {
        use std::io::BufRead;
        let (_dir, mut state) = make_state();
        // A real member: a moving outcome emits a delta whose subject_lct is the
        // mapped member LCT, not the raw plugin_id.
        state.apply_outcome("real-plugin", false, 0.7).unwrap();
        let sink = state.reputation_sink();
        let expected = state.member_lct("real-plugin").unwrap();
        let lines: Vec<String> = std::fs::File::open(&sink)
            .map(|f| std::io::BufReader::new(f).lines().map_while(Result::ok).collect())
            .unwrap_or_default();
        assert_eq!(lines.len(), 1, "one delta emitted for a real member");
        assert!(lines[0].contains(&expected), "subject_lct is the member LCT");
        assert!(!lines[0].contains("real-plugin"), "raw plugin_id never leaks");

        // A synthetic member: trust still updates locally, but NO delta is emitted.
        state.mark_synthetic("synthetic-plugin");
        state.apply_outcome("synthetic-plugin", false, 0.7).unwrap();
        let after: Vec<String> = std::fs::File::open(&sink)
            .map(|f| std::io::BufReader::new(f).lines().map_while(Result::ok).collect())
            .unwrap_or_default();
        assert_eq!(after.len(), 1, "synthetic plugin emits no delta (fail-closed)");
    }

    #[test]
    fn synthetic_set_persists_across_reopen() {
        let dir = TempDir::new().unwrap();
        let vault_path = dir.path().join("v.enc");

        {
            let vault = Vault::init(vault_path.clone(), "p".into()).unwrap();
            let mut state = ServerState::open(vault, dir.path(), "p").unwrap();
            assert!(state.mark_synthetic("conformance-runner"));
            assert!(state.mark_synthetic("conformance-runner-py"));
            // Re-marking the same id is a no-op.
            assert!(!state.mark_synthetic("conformance-runner"));
            assert!(state.is_synthetic("conformance-runner"));
            assert!(!state.is_synthetic("claude-code"));
        }

        // Reopen with the same home — synthetic set is restored from disk.
        let vault = Vault::open(vault_path.clone(), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path(), "p").unwrap();
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
                constellation_role: "role:constellation:member".into(),
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
                constellation_role: "role:constellation:member".into(),
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
