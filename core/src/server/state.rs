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
    /// Durable inbound mailbox (entity-edge inbox): still-sealed notices parked
    /// by `hestia_notify {defer: true}` before the hub is ACKed, drained by
    /// `hestia_inbox`. Encrypted at rest under the same storage key as the
    /// witness chain, in its own file (queue ≠ ledger — two persistences).
    pub inbox_store: crate::storage::SqliteInboxStore,
    /// The legacy sovereign anchor string — witness-chain authorship + member-label
    /// derivation still key on this verbatim. See `sovereign` for the LCT identity.
    pub sovereign_lct: String,
    /// The constellation sovereign as a first-class, vault-persisted LCT (durable
    /// key-derived identity, sealed keypair). The society that mints the roles, with
    /// presence of its own. `sovereign.lct_id()` is its canonical id. See `sovereign`.
    pub sovereign: crate::sovereign::Sovereign,
    /// Phase-1 audit-first mirror: the published constellation roles as first-class
    /// `web4_core::RoleEntity` LCT entities (additive + read-only — law evaluation
    /// still uses the string-keyed `role_policy_engines` fold). See `role_registry`.
    pub role_registry: web4_core::RoleRegistry,
    /// Custodial member LCTs (the third registry consumer), `plugin_id → Lct`.
    /// Minted on a member's first connect, vault-persisted, each carrying a
    /// verifiable legacy alias to its `member_lct` label. See `member_registry`.
    pub member_registry: crate::member_registry::MemberRegistry,
    pub shared_context: serde_json::Map<String, serde_json::Value>,
    pub policy_engine: crate::policy::PolicyEngine,
    /// Per-constellation-role policy engines (#403 role-scoped law), built from
    /// the vault's `role_overlays`. A session's declared role selects its engine;
    /// its verdict is folded into `policy_engine` by strictest-wins in
    /// `query_policy`, so a role can only tighten the base, never loosen it.
    pub role_policy_engines: HashMap<String, crate::policy::PolicyEngine>,
    /// Per-`(instance, role)` policy engines (the finest grain), keyed by
    /// `(plugin_id, role)`. Selected AFTER the role engine and folded strictest-
    /// wins in the gate, so a specific orchestrator can only tighten its role's
    /// law, never loosen it. Built from the vault's `instance_overlays`.
    pub instance_policy_engines: HashMap<(String, String), crate::policy::PolicyEngine>,
    /// Hub-law gate (consolidation, 2026-07-10): the third fold input.
    /// `None` = no law file at `$HESTIA_HOME/law/hub-law.yaml` (no-op);
    /// `Some(Invalid)` fails closed. See `policy::law_gate`.
    pub law_gate: Option<crate::policy::LawGate>,
    /// Plugin IDs that self-declared as synthetic (test harnesses,
    /// fuzzers, etc.). Excluded from operator-facing aggregations by
    /// default. Enclosed in the vault (document `presence`/`synthetic`).
    pub synthetic_plugins: HashSet<String>,
    pub home: PathBuf,
    /// Single-use OID4VCI `c_nonce`s issued but not yet redeemed.
    pub vci_nonces: HashSet<String>,
    /// Operator-surface auth (RWOA W/O): issued challenges (anti-replay) and
    /// established operator sessions. See `server::operator_auth`.
    pub operator_challenges: crate::server::operator_auth::ChallengeStore,
    pub operator_sessions: crate::server::operator_auth::SessionStore,
}

/// Unix seconds now — the single clock for operator challenge/session TTLs.
pub fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

impl ServerState {
    /// Open all persistent stores rooted at `home` and prepare server state.
    /// `passphrase` is the vault passphrase — used to derive the storage key
    /// that seals the witness chain + trust files.
    pub fn open(mut vault: Vault, home: &Path, passphrase: &str) -> Result<Self> {
        // One stable storage key (Argon2 once) seals both the witness chain
        // (SQLCipher) and the trust files.
        let store_key = crate::storage::storage_key(home, passphrase)
            .map_err(|e| anyhow::anyhow!("deriving storage key: {e}"))?;
        let chain_store = SqliteChainStore::open(home.join("witness.db"), store_key)?;
        let trust_store = TrustStore::open(home.join("trust"), store_key)?;
        let inbox_store = crate::storage::SqliteInboxStore::open(home.join("inbox.db"), store_key)?;
        let sovereign_lct = "lct:web4:hestia:sovereign:phase1-placeholder".to_string();
        // The sovereign as a first-class, vault-persisted LCT — the society that
        // mints the roles now has durable presence of its own (id stable across
        // restarts, keypair sealed). `anchor` stays the legacy string, so member
        // labels + witness-chain authorship keyed on `sovereign_lct` are unchanged.
        let sovereign = crate::sovereign::Sovereign::load_or_mint(&mut vault, &sovereign_lct);
        eprintln!(
            "[hestia] sovereign LCT {} (self-issued bootstrap, placeholder strength)",
            sovereign.lct_id()
        );
        // Phase-1 mirror: the constellation roles as Role LCT entities, with
        // VAULT-STABLE identities (same LCT across restarts; secrets sealed).
        let role_registry = crate::role_registry::load_or_mint_registry(
            &mut vault,
            &sovereign_lct,
            &sovereign.lct_id(),
        );
        // Custodial member LCTs, loaded from the vault (minted lazily on connect).
        let member_registry = crate::member_registry::load_members(&vault);
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
        let instance_policy_engines = vault
            .policy()
            .instance_configs()
            .into_iter()
            .map(|(key, cfg)| (key, crate::policy::PolicyEngine::new(cfg)))
            .collect();

        // Hub-law third input (machine-local copy; hub is the content
        // authority). Absent file => None; invalid file => fail-closed gate.
        let law_gate = crate::policy::LawGate::load(home);
        if let Some(g) = &law_gate {
            match g.law_sha256() {
                Some(h) => eprintln!("[hestia] hub law loaded (sha256 {h})"),
                None => eprintln!("[hestia] WARNING: hub law present but INVALID — failing closed"),
            }
        }

        // Synthetic-plugin set lives in the vault (migrating a legacy
        // synthetic.json). Absent doc = fresh install (empty set is correct);
        // a present-but-unparseable doc must abort startup — collapsing it to
        // an empty set would silently drop the synthetic exclusion in
        // `member_lct` and mint durable, derivation-valid member LCTs for
        // synthetic plugins.
        let synthetic_plugins: HashSet<String> = {
            use anyhow::Context;
            crate::vault::load_doc(&vault, "presence", "synthetic", "synthetic.json").context(
                "synthetic-plugin set unreadable — failing closed instead of treating it as empty",
            )?
        };

        Ok(Self {
            vault,
            sessions: HashMap::new(),
            actions: HashMap::new(),
            chain_store,
            trust_store,
            inbox_store,
            sovereign_lct,
            sovereign,
            role_registry,
            member_registry,
            shared_context: serde_json::Map::new(),
            policy_engine,
            role_policy_engines,
            instance_policy_engines,
            law_gate,
            synthetic_plugins,
            home: home.to_path_buf(),
            vci_nonces: HashSet::new(),
            operator_challenges: crate::server::operator_auth::ChallengeStore::default(),
            operator_sessions: crate::server::operator_auth::SessionStore::default(),
        })
    }

    /// Mark a plugin_id as synthetic and persist. Idempotent on membership;
    /// `Ok(true)` if this call added a new entry.
    ///
    /// The persist is fail-closed and NOT guarded by novelty — the write-side
    /// mirror of the corrupt-doc load rule. A best-effort save that failed
    /// silently left the exclusion in memory only: durable member labels
    /// would mint for this plugin after the next restart, and a novelty
    /// guard meant no later re-join ever retried the write. The write is
    /// retried up to `max_attempts` times (law-settable via the vault policy,
    /// default 3 — see `VaultPolicyState::synthetic_persist_attempts`); if every
    /// attempt fails the error reaches the caller (which must refuse the
    /// request), the in-memory entry still stands so THIS run keeps the
    /// exclusion, and the next declaring join retries the persist again.
    pub fn mark_synthetic(&mut self, plugin_id: &str, max_attempts: u32) -> anyhow::Result<bool> {
        let added = self.synthetic_plugins.insert(plugin_id.to_string());
        let attempts = max_attempts.max(1);
        let mut last_err = None;
        for _ in 0..attempts {
            match crate::vault::save_doc(
                &mut self.vault,
                "presence",
                "synthetic",
                "synthetic.json",
                &self.synthetic_plugins,
            ) {
                Ok(()) => return Ok(added),
                Err(e) => last_err = Some(e),
            }
        }
        Err(last_err
            .expect("attempts >= 1 so the loop ran at least once")
            .context(format!(
                "failed to persist synthetic exclusion for '{plugin_id}' after {attempts} attempt(s)"
            )))
    }

    pub fn is_synthetic(&self, plugin_id: &str) -> bool {
        self.synthetic_plugins.contains(plugin_id)
    }

    /// Bounded, self-witnessing operator bootstrap (RWOA genesis window). If the
    /// law's `operator_access` is EMPTY (genesis), mint one operator: generate a
    /// keypair, write the private key 0600 to `<home>/operator.key` for the
    /// operator to load into their client (browser/helper/TPM), seed the PUBLIC
    /// key into the law, and witness the act AS a bootstrap (genesis evidence).
    /// The window ratchets shut the moment `operator_access` is non-empty — this
    /// no-ops on every subsequent start, so "claim you're still bootstrapping"
    /// has no re-entry. Returns the new operator's lct_id if one was minted.
    pub fn bootstrap_operator_if_genesis(&mut self) -> Result<Option<String>> {
        if self.vault.policy().operator_access_bootstrapped() {
            return Ok(None); // window shut — no re-entry
        }
        use std::os::unix::fs::PermissionsExt;
        let kp = web4_core::crypto::KeyPair::generate();
        let lct_id = web4_core::lct::derive_lct_id(&kp.verifying_key());
        // Self-contained credential the operator loads into their client: the
        // lct_id (so the client knows WHICH operator it is) + the raw Ed25519 seed
        // (hex) the client wraps + imports for signing. 0600, genesis handoff.
        let key_path = self.home.join("operator.key");
        let cred = serde_json::json!({
            "lct_id": lct_id,
            "secret_key_hex": hex::encode(kp.secret_key_bytes()),
            "note": "genesis operator credential — load into your dashboard client to sign in; keep private; rotate to a hardware key when able",
        });
        std::fs::write(
            &key_path,
            serde_json::to_vec_pretty(&cred).unwrap_or_default(),
        )
        .map_err(|e| anyhow::anyhow!("writing operator.key: {e}"))?;
        let mut perms = std::fs::metadata(&key_path)?.permissions();
        perms.set_mode(0o600);
        std::fs::set_permissions(&key_path, perms)?;

        let mut policy = self.vault.policy().clone();
        policy.operator_access.push(crate::vault::OperatorIdentity {
            lct_id: lct_id.clone(),
            public_key_hex: hex::encode(kp.public_key_bytes()),
            label: "genesis operator (bootstrap)".into(),
        });
        self.vault
            .set_policy(policy)
            .map_err(|e| anyhow::anyhow!("persisting bootstrapped operator: {e}"))?;

        // Self-witnessing A: the genesis act is recorded AS a bootstrap act, with
        // the evidence available at genesis (the sovereign process minting the
        // first operator). The record makes the origin auditable, not silent.
        let _ = self.append_chain(
            "operator_bootstrap",
            serde_json::json!({
                "operator": lct_id,
                "window": "genesis",
                "evidence": "sovereign-process-minting-first-operator",
                "note": "bounded self-terminating bootstrap; no re-entry once operator_access is non-empty",
            }),
        );
        eprintln!(
            "[hestia] OPERATOR BOOTSTRAP: minted genesis operator {lct_id}\n\
             [hestia]   private key written to {} (0600) — load it into your operator client;\n\
             [hestia]   the bootstrap window is now SHUT (add further operators via law).",
            key_path.display()
        );
        Ok(Some(lct_id))
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
        self.instance_policy_engines = self
            .vault
            .policy()
            .instance_configs()
            .into_iter()
            .map(|(key, cfg)| (key, crate::policy::PolicyEngine::new(cfg)))
            .collect();
        // Re-read the machine-local hub law alongside vault policy so an
        // operator law update lands without a daemon restart.
        self.law_gate = crate::policy::LawGate::load(&self.home);
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

    /// Confer citizenship on `subject_lct_id` — birth into THIS society's MRH —
    /// by recording a birth certificate in this society's **ledger** (the witness
    /// chain), the authoritative home per the citizenship-is-birth model (dp,
    /// 2026-07-16). The issuing society is this constellation (its sovereign LCT
    /// stands as the society identity until the Society-LCT restructure lands).
    ///
    /// **Fail-closed:** records nothing and returns `None` unless the attestations
    /// meet the ≥3-distinct witness quorum, verified against `resolve_witness_pubkey`
    /// (the registry is that resolver). The recorded event carries both the
    /// certificate AND the backing attestations (the evidence), so any reader of
    /// this ledger can re-verify the quorum — evidence, not a bare verdict.
    ///
    /// This is hestia's conferral lane (members/roles born into the constellation);
    /// the sovereign's own citizenship is conferred by the hub's ledger (it is a
    /// citizen of the hub, its parent society).
    pub fn confer_citizenship<F>(
        &self,
        subject_lct_id: &str,
        citizen_role: &str,
        birth_context: Option<web4_core::BirthContext>,
        attestations: &[web4_core::Attestation],
        resolve_witness_pubkey: F,
    ) -> Result<Option<web4_core::BirthCertificateRef>>
    where
        F: Fn(&str) -> Option<web4_core::PublicKey>,
    {
        let issuing_society = self.sovereign.lct_id();
        let ts = Utc::now();
        let Some((certificate, evidence)) = crate::witness::build_birth_certificate(
            subject_lct_id,
            citizen_role,
            &issuing_society,
            birth_context,
            attestations,
            ts,
            resolve_witness_pubkey,
        ) else {
            return Ok(None); // quorum not met — no birth (fail-closed)
        };
        // The authoritative record: certificate + backing attestations. Its
        // content hash binds the reference the subject LCT will carry.
        let record = web4_core::CitizenshipRecord {
            certificate,
            attestations: evidence,
        };
        let entry_hash = record.content_hash();
        // Record the record in THIS society's ledger (its witness chain) — the
        // authoritative home. The event data IS the CitizenshipRecord, so a
        // reader re-verifies quorum + re-hashes it against any presented reference.
        let entry = self.append_chain(
            "citizenship.conferred",
            serde_json::json!({
                "citizen": subject_lct_id,
                "record": record,
            }),
        )?;
        // The tamper-evident reference the subject LCT carries in `citizenships`:
        // society + ledger locator (chain position) + content hash.
        Ok(Some(web4_core::BirthCertificateRef {
            issuing_society,
            entry_id: entry.chain_position.to_string(),
            entry_hash,
        }))
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
            reason: if success {
                "outcome:success"
            } else {
                "outcome:failure"
            },
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
        let (before, after) = self
            .trust_store
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

    /// The judgment-axis trust key: `<instance_lct>#<role_lct>#judgment`.
    ///
    /// Judgment outcomes (reversals/overrides) get their OWN trust entity, not a
    /// share of the execution scalar. The calibration join (calibration-prd4)
    /// measured why: execution outcomes arrive ~10³/day/machine and judgment
    /// outcomes ~10⁰/day fleet-wide, so a reversal's dip in a shared `t3_average`
    /// refills within minutes and the estimator stays a constant (pinned at the
    /// 0.8 cap for the entire label era). Keying judgment on its own entity means
    /// ONLY judgment events move it — its timescale is its own, and the estimator
    /// can hold variance across a label window.
    pub fn judgment_entity_key(&self, plugin_id: &str, role_lct: &str) -> String {
        format!("{}#judgment", self.trust_entity_key(plugin_id, role_lct))
    }

    /// Read the judgment-axis trust for a `(instance, role)` grain.
    pub fn judgment_for_role(&self, plugin_id: &str, role_lct: &str) -> EntityTrust {
        let key = self.judgment_entity_key(plugin_id, role_lct);
        self.trust_store
            .get(&key)
            .unwrap_or_else(|_| EntityTrust::new(key))
    }

    /// Apply a judgment outcome to the judgment-axis entity and emit the delta
    /// (same bridge as [`apply_outcome_ctx`]). The delta's `action_type`
    /// (`"reversal"`) is what separates this stream from execution deltas in the
    /// sink — the role_lct stays canonical so the hub fold doesn't fragment.
    pub fn apply_judgment_ctx(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
        ctx: &crate::reputation::RepContext,
    ) -> Result<EntityTrust> {
        let key = self.judgment_entity_key(plugin_id, ctx.role_lct);
        let (before, after) = self
            .trust_store
            .update_returning_prior(&key, success, magnitude)?;
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
        state
            .apply_outcome_ctx("claude-code", false, 0.8, &ctx_for(mw))
            .unwrap();
        let mw_trust = state
            .apply_outcome_ctx("claude-code", false, 0.8, &ctx_for(mw))
            .unwrap();
        // Same plugin, interactive-dev role: one success.
        let dev_trust = state
            .apply_outcome_ctx(
                "claude-code",
                true,
                0.8,
                &crate::reputation::RepContext {
                    reason: "outcome:success",
                    ..ctx_for(dev)
                },
            )
            .unwrap();
        // Distinct entities: the two roles carry different entity_ids + scores.
        assert_ne!(mw_trust.entity_id, dev_trust.entity_id);
        assert!(
            mw_trust.entity_id.ends_with(mw),
            "got {}",
            mw_trust.entity_id
        );
        assert!(
            dev_trust.entity_id.ends_with(dev),
            "got {}",
            dev_trust.entity_id
        );
        // The mesh-worker's failures did not touch the dev role's trust.
        assert!(
            dev_trust.talent() > mw_trust.talent(),
            "dev(success) {} must outrank mesh-worker(2 failures) {}",
            dev_trust.talent(),
            mw_trust.talent()
        );
        // Same instance underlies both (the shared member LCT prefix).
        let inst = state.member_lct("claude-code").unwrap();
        assert!(mw_trust.entity_id.starts_with(&inst));
        assert!(dev_trust.entity_id.starts_with(&inst));
        // Re-reading by role recovers the same accrued entity.
        assert_eq!(
            state.trust_for_role("claude-code", mw).entity_id,
            mw_trust.entity_id
        );
    }

    #[test]
    fn chain_grows_with_hash_linkage() {
        let (_dir, state) = make_state();
        let e1 = state
            .append_chain("evt1", serde_json::json!({"a": 1}))
            .unwrap();
        let e2 = state
            .append_chain("evt2", serde_json::json!({"b": 2}))
            .unwrap();
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
    fn confer_citizenship_records_a_birth_cert_in_the_ledger_only_on_quorum() {
        let (_dir, state) = make_state();
        let subject = "lct:web4:mb32:bsubjectcitizen";
        let w: Vec<web4_core::crypto::KeyPair> = (0..3)
            .map(|_| web4_core::crypto::KeyPair::generate())
            .collect();
        let wid: Vec<String> = (0..3).map(|i| format!("lct:web4:member:w{i}")).collect();
        let resolver = {
            let ks: Vec<_> = w.iter().map(|k| k.verifying_key()).collect();
            let wid = wid.clone();
            move |id: &str| wid.iter().position(|x| x == id).map(|i| ks[i].clone())
        };
        let ts = chrono::Utc::now();
        let chain_before = state.chain_len();

        // Below quorum → None, and NOTHING written to the ledger (fail-closed).
        let two: Vec<_> = (0..2)
            .map(|i| crate::witness::attest(subject, &wid[i], ts, &w[i]))
            .collect();
        assert!(
            state
                .confer_citizenship(subject, "lct:web4:role:citizen", None, &two, &resolver)
                .unwrap()
                .is_none()
        );
        assert_eq!(
            state.chain_len(),
            chain_before,
            "no birth on < 3 witnesses = no ledger write"
        );

        // Quorum → the birth cert is recorded in this society's ledger.
        let three: Vec<_> = (0..3)
            .map(|i| crate::witness::attest(subject, &wid[i], ts, &w[i]))
            .collect();
        let cref = state
            .confer_citizenship(subject, "lct:web4:role:citizen", None, &three, &resolver)
            .unwrap()
            .unwrap();
        assert_eq!(cref.issuing_society, state.sovereign.lct_id());
        assert!(
            !cref.entry_hash.is_empty(),
            "reference binds the record content hash"
        );
        assert_eq!(
            state.chain_len(),
            chain_before + 1,
            "conferral wrote one ledger event"
        );
        let recent = state.recent_chain(1);
        assert_eq!(recent[0].event_type, "citizenship.conferred");
        assert_eq!(recent[0].event_data["citizen"], subject);
        // the reference's hash matches the recorded record (tamper-evident bind)
        let record: web4_core::CitizenshipRecord =
            serde_json::from_value(recent[0].event_data["record"].clone()).unwrap();
        assert_eq!(record.content_hash(), cref.entry_hash);
        assert!(
            record.verify_quorum(subject, &resolver),
            "recorded evidence re-verifies"
        );
    }

    #[test]
    fn member_lct_matches_web4core_legacy_derivation_byte_for_byte() {
        // Lockstep contract (hestia-lct-concord 2026-07-10): the alias the hub
        // registry verifies is computed by web4_core::LegacyDerivation::HestiaMember;
        // it MUST reproduce this daemon's member_lct exactly, or a published member
        // LCT's legacy alias fails ingest. Proven here against the live function, not
        // a copy of the formula.
        let (_dir, state) = make_state();
        for plugin in ["alice", "claude-code", "supervisor-timer"] {
            let native = state.member_lct(plugin).unwrap();
            let via_web4core = web4_core::LegacyDerivation::HestiaMember {
                plugin_id: plugin.to_string(),
                sovereign: state.sovereign_lct.clone(),
            }
            .derive();
            assert_eq!(
                native, via_web4core,
                "member_lct must equal the canonical derivation for {plugin}"
            );
        }
    }

    #[test]
    fn operator_bootstrap_is_bounded_and_no_reentry() {
        let (_dir, mut state) = make_state();
        // genesis: empty operator_access → mints exactly one operator
        assert!(!state.vault.policy().operator_access_bootstrapped());
        let first = state.bootstrap_operator_if_genesis().unwrap();
        assert!(first.is_some(), "genesis mints an operator");
        assert!(state.vault.policy().operator_access_bootstrapped());
        assert_eq!(state.vault.policy().operator_access.len(), 1);
        // the credential was written 0600 for the operator to load, and is a
        // valid {lct_id, secret_key_hex} the client can sign with
        let key = state.home.join("operator.key");
        assert!(key.exists());
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            std::fs::metadata(&key).unwrap().permissions().mode() & 0o777,
            0o600
        );
        let cred: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&key).unwrap()).unwrap();
        assert_eq!(cred["lct_id"], first.clone().unwrap());
        assert_eq!(cred["secret_key_hex"].as_str().unwrap().len(), 64); // 32-byte seed hex
        // window shut: re-run is a no-op (no re-entry, no second operator)
        assert!(state.bootstrap_operator_if_genesis().unwrap().is_none());
        assert_eq!(state.vault.policy().operator_access.len(), 1);
    }

    #[test]
    fn member_lct_fails_closed_for_synthetic_and_empty() {
        let (_dir, mut state) = make_state();
        assert!(state.mark_synthetic("conformance-runner", 3).unwrap());
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
            .map(|f| {
                std::io::BufReader::new(f)
                    .lines()
                    .map_while(Result::ok)
                    .collect()
            })
            .unwrap_or_default();
        assert_eq!(lines.len(), 1, "one delta emitted for a real member");
        assert!(
            lines[0].contains(&expected),
            "subject_lct is the member LCT"
        );
        assert!(
            !lines[0].contains("real-plugin"),
            "raw plugin_id never leaks"
        );

        // A synthetic member: trust still updates locally, but NO delta is emitted.
        state.mark_synthetic("synthetic-plugin", 3).unwrap();
        state.apply_outcome("synthetic-plugin", false, 0.7).unwrap();
        let after: Vec<String> = std::fs::File::open(&sink)
            .map(|f| {
                std::io::BufReader::new(f)
                    .lines()
                    .map_while(Result::ok)
                    .collect()
            })
            .unwrap_or_default();
        assert_eq!(
            after.len(),
            1,
            "synthetic plugin emits no delta (fail-closed)"
        );
    }

    #[test]
    fn synthetic_set_persists_across_reopen() {
        let dir = TempDir::new().unwrap();
        let vault_path = dir.path().join("v.enc");

        {
            let vault = Vault::init(vault_path.clone(), "p".into()).unwrap();
            let mut state = ServerState::open(vault, dir.path(), "p").unwrap();
            assert!(state.mark_synthetic("conformance-runner", 3).unwrap());
            assert!(state.mark_synthetic("conformance-runner-py", 3).unwrap());
            // Re-marking the same id is a no-op.
            assert!(!state.mark_synthetic("conformance-runner", 3).unwrap());
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
    fn corrupt_synthetic_doc_fails_startup_not_open() {
        // A present-but-unparseable synthetic set must abort startup: treating
        // it as empty would drop the member_lct exclusion and mint durable
        // member LCTs for synthetic plugins.
        let dir = TempDir::new().unwrap();
        let vault_path = dir.path().join("v.enc");
        let mut vault = Vault::init(vault_path.clone(), "p".into()).unwrap();
        vault
            .put_document("presence", "synthetic", b"{ not valid json".to_vec())
            .unwrap();
        assert!(ServerState::open(vault, dir.path(), "p").is_err());

        // Same for a corrupt legacy plaintext sidecar (no vault doc present).
        let dir2 = TempDir::new().unwrap();
        let vault2 = Vault::init(dir2.path().join("v.enc"), "p".into()).unwrap();
        std::fs::write(dir2.path().join("synthetic.json"), "][").unwrap();
        assert!(ServerState::open(vault2, dir2.path(), "p").is_err());

        // Absent doc stays a fresh install: empty set, startup succeeds.
        let dir3 = TempDir::new().unwrap();
        let vault3 = Vault::init(dir3.path().join("v.enc"), "p".into()).unwrap();
        let state = ServerState::open(vault3, dir3.path(), "p").unwrap();
        assert!(state.synthetic_plugins.is_empty());
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
        assert_eq!(
            state.resolve_plugin_id(Some("00000000-0000-0000-0000-000000000000")),
            None
        );
    }
}
