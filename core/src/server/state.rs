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
    /// HOW the constellation role was established (e.g.
    /// `provisional:declared-by-fire; identity file absent or unreadable at …`),
    /// supplied by the caller at `connect` as `role_basis`. Never normalized:
    /// it is the caller's own account of its provenance, carried onto outcome
    /// chain entries so a *provisional* `mesh-worker` is distinguishable from a
    /// *hydrated* one — the normalized role string alone cannot separate them
    /// (both are the same `&'static str` by construction).
    ///
    /// Captured AT MINT: under Guard A session reuse, the basis is whatever the
    /// FIRST connect for a given `host_session_id` supplied, and a later reuse
    /// carrying a different basis is refused adoption (the minted value is
    /// echoed, not replaced). So `None` records "absent at mint", NOT "the
    /// caller never had a basis" — a session whose first connect raced the
    /// fire's exports reads `null` even if every later connect supplied one
    /// (claude-code review of #238, point 2).
    pub role_basis: Option<String>,
    pub soft_lct: String,
    pub connected_at: DateTime<Utc>,
    /// The caller's stable host-session id (e.g. Claude Code's `session_id`), if supplied. A
    /// DESCRIPTIVE reuse key ONLY — `tool_connect` reuses a live session with a matching value
    /// instead of minting churn per tool call, so one host session = one stable hestia session.
    /// Guard B (HUB ruling 2026-07-24): this is NEVER an authorization discriminator — no policy/authz
    /// decision may key off it (nor off `soft_lct`). It names a session; it never confers capability.
    pub host_session_id: Option<String>,
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

/// An operator's scoped exception to society law for one `(plugin_id, role)`.
///
/// Held in memory only — see `ServerState::instance_grants`. Carries WHO granted it and WHY,
/// because a loosening whose rationale is not recorded is indistinguishable after the fact from
/// a misconfiguration, and this is the one control in the system that can widen what an agent
/// may do.
#[derive(Debug, Clone, serde::Serialize)]
pub struct InstanceGrant {
    /// Preset the grant applies to this member instead of the society baseline.
    pub preset: String,
    /// Operator identity from the challenge-signed session that set it.
    pub granted_by: String,
    pub granted_at: u64,
    pub reason: String,
    /// Wall-clock expiry, when the operator set one. `None` means it lasts until revoked or
    /// until the daemon restarts — which it always eventually does, so no grant is permanent.
    pub expires_at: Option<u64>,
}

impl InstanceGrant {
    pub fn is_live(&self, now: u64) -> bool {
        self.expires_at.is_none_or(|e| now < e)
    }
}

/// A member's request to reach ONE path outside its standing MRH, and the operator's answer.
///
/// WHY THIS EXISTS (dp + kimi-code, 2026-08-02). kimi was directed by dp in-session to read a
/// file outside its granted scope. The plugin gate refused — correctly, the path was outside
/// `HESTIA_WORKSPACE` entirely — and told it to *"request it (request_scope)"*. **That tool did
/// not exist.** 29 MCP tools, none scope-related, and the message never named `hestia_appeal`
/// either. kimi followed the only door it could find, filed an appeal, and reached a mechanism
/// that by design cannot deliver a file.
///
/// Because appeals and scope are DIFFERENT CHANNELS, and must stay so. kimi put it exactly:
///
/// > *"even an upheld appeal doesn't unlock anything. The appeal machinery repairs the trust
/// > record of the deny. It cannot and by design must not edit permissions — otherwise the
/// > appeal would be a backdoor around law, and the whole structure collapses into 'deny,
/// > appeal, proceed anyway.'"*
///
/// So an appeal yields a VERDICT and this yields a GRANT. Nothing here touches conduct scoring,
/// and nothing in the appeal path touches scope.
///
/// SHAPE, inherited from `InstanceGrant` because the reasoning is identical:
///   * **memory only** — never written to `identity.json`. A standing widening is dp's act on
///     that file; this is a session-scoped exception that dies with the daemon, so a grant
///     nobody remembers to revoke expires on its own.
///   * **operator-granted** — the member may ASK; only the operator may answer.
///   * **one path** — a request names a single target, not a prefix tree. A member asking for
///     `path:` and receiving the workspace would be a scope grab wearing a request's clothes.
///   * **disclosed** — visible in `hestia_operating_law`, because a widening the subject cannot
///     see is as much a trapdoor as one it cannot audit.
///
/// kimi also declined to edit its own identity even when dp offered — *"a member widening its
/// own scope silently is exactly the act the law treats as corrosive, sanctioned or not."* This
/// exists so that restraint does not have to cost the work.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ScopeRequest {
    pub id: String,
    /// Caller-asserted, like every other plugin_id here (HST-005).
    pub plugin_id: String,
    pub role: String,
    /// The ONE path being asked for.
    pub path: String,
    /// Why, in the member's words. Required — a scope ask with no stated need is not
    /// decidable, and this is the field whose absence made escalations unrulable.
    pub reason: String,
    pub requested_at: u64,
    pub expires_at: u64,
    /// `None` = still pending. `Some(true)` = granted.
    pub granted: Option<bool>,
    pub decided_by: Option<String>,
    pub decided_at: Option<u64>,
    pub decision_reason: Option<String>,
}

impl ScopeRequest {
    /// Live = granted, and not past its window. A refused or expired request grants nothing,
    /// and an unanswered one grants nothing — the default is always the standing MRH.
    pub fn grants(&self, path: &str, now: u64) -> bool {
        self.granted == Some(true) && now < self.expires_at && self.path == path
    }

    /// One word for the whole record. `expires_at` means the same thing in both phases — the
    /// moment this record stops mattering — so an undecided request that runs out the clock
    /// reads `expired`, and **expired is a refusal, not a retry**, exactly as the escalation
    /// channel already rules. Silence has to decide the same way everywhere or members will
    /// learn that waiting is a strategy.
    pub fn status(&self, now: u64) -> &'static str {
        match self.granted {
            Some(true) if now < self.expires_at => "granted",
            Some(true) => "expired",
            Some(false) => "refused",
            None if now < self.expires_at => "pending",
            None => "expired",
        }
    }
}

/// The disposition projector's cursor row name (inbox.db `projection_cursors`).
/// Lives here rather than in handler.rs because the cursor is initialized at
/// state OPEN — `ServerState::open` — not at the worker's first pass.
pub(crate) const DISPOSITION_PROJECTION_CURSOR: &str = "disposition";

/// How long an undecided scope request stays askable, and the default life of a grant.
///
/// Both are the same 8 hours, and that is not laziness: a request is a question about work
/// happening NOW, and a grant is permission to do that same work. A window that outlives the
/// task turns a scoped exception into a standing one by inattention.
pub const SCOPE_REQUEST_TTL_SECS: u64 = 8 * 3600;

/// THE ASYMMETRY, stated once so neither half drifts (dp, 2026-08-01; amended 2026-08-14):
///
/// | direction           | where it lives                      | survives restart |
/// |---------------------|-------------------------------------|------------------|
/// | TIGHTENING          | vault (`instance_overlays`)         | **yes**          |
/// | LIVE loosening      | memory (`instance_grants`,          | **no**           |
/// |                     |  `scope_requests`)                  |                  |
/// | STANDING loosening  | vault (`scope`/`standing` document) | **yes**          |
///
/// The first two rows are the 2026-08-01 doctrine and are unchanged: a RESTRICTION has to be
/// durable — a member restricted for cause must not be freed by a reboot — and a LIVE
/// permission has to be ephemeral, with the daemon restarting as the backstop that guarantees
/// a grant nobody remembers to revoke dies on its own.
///
/// The third row was added on dp's explicit ruling (2026-08-14, Sprint F R1 "the real fix"):
/// standing member scope needs a daemon surface, or the only durable widening is a
/// member-writable `identity.json` the certified-replica logic rightly refuses. A STANDING
/// permission is durable ON PURPOSE — but it trades the restart backstop for four explicit
/// controls: operator-only mutation (the challenge-signed HTTP surface; no MCP tool), an
/// honoured `expires_at`, a first-class witnessed revoke, and a monotonic `generation` so a
/// consumer can tell WHICH policy a copy is. See `server::standing_scope`.
///
/// None of the three lives in an external plaintext file. Both durable rows are vault↔memory:
/// written into the encrypted vault and read back at startup, never to a plaintext config on
/// disk that could be edited around the gate — which is the hole `#133` recorded, where
/// widening a member's authority was a `json.dump` nobody had to ask permission for.
pub const POLICY_SCOPE_ASYMMETRY: () = ();

/// How much chain the escalation replay scans at startup.
///
/// Bounded on purpose: escalations live at most `DEFAULT_TTL_SECS` (1h) plus a claim window, so
/// anything older than a few thousand entries is terminal by time and cannot be ruled. Scanning
/// the whole chain (96 MB here) to rebuild an hour of state would make every daemon start pay
/// for all of history.
const ESCALATION_REPLAY_SCAN: u64 = 5_000;

/// The mutable core state passed to every request handler.
pub struct ServerState {
    /// In-scope work awaiting attestation, keyed by (plugin_id, role_lct) → (allows, denies).
    ///
    /// WHY THIS EXISTS. Trust could only be earned two ways — be denied and comply, or be
    /// adjudicated by a peer — so a member doing quiet, in-scope, competent work was
    /// literally unmeasurable. On 2026-07-26 kimi-code/member had 2,214 actions at 99.5%
    /// success and read `unmeasured`, while the same agent's interactive-dev grain read
    /// `high` off 40 actions and 25 complied-with denials. The system measured how a member
    /// behaved when caught, not whether it did good work.
    ///
    /// Every ALLOW is the gate — NOT the actor — asserting "this was inside your grant".
    /// That is exactly the not-self-reported evidence the design asks for, and all 17,649 of
    /// them were being discarded because they arrived bundled with the self-reported "it
    /// worked". These counters separate the two claims so the trustworthy half can count.
    ///
    /// In memory on purpose: a restart forfeits at most one partial window, and persisting
    /// a tally would make the ATTESTATION rather than the chain the source of truth.
    pub scope_tally: std::collections::HashMap<(String, String), (u64, u64)>,
    pub vault: Vault,
    pub sessions: HashMap<Uuid, Session>,
    pub actions: HashMap<Uuid, InFlightAction>,
    /// BEHIND AN `Arc` SO A HEAVY READ NEED NOT HOLD THE GLOBAL STATE LOCK.
    ///
    /// The store already locks internally (`conn: Mutex<Connection>`) and is `Send + Sync`, so
    /// holding `state.lock()` across a chain read bought nothing but contention. It cost a
    /// great deal: `/api/governance/ledger` takes 8–15s against the live chain, and it held
    /// this lock for all of it, so every other caller queued behind a UI panel.
    ///
    /// Measured on CBP 2026-08-16, with the dashboard open vs closed:
    ///   `hestia_connect`  3.3–7.0s  ->  0.001s
    /// That is not a latency nuisance. The plugin gate's witness budget is 1.5s and its
    /// escalation round trip is barely more, so while the governance screen was open the gate
    /// could neither witness a refusal nor open an escalation — and the harness kills a hook
    /// at 5s, which the hook's own comments note FAILS OPEN. The governance dashboard was
    /// disabling governance enforcement for every member, silently, while being read.
    ///
    /// The `len()` doc-comment below already diagnosed this exact shape for a different
    /// caller. This is the same lesson applied to the field itself: shared ownership, so the
    /// expensive work happens with the state lock released.
    ///
    /// The disposition projector relies on the same ownership boundary: it clones
    /// this handle while holding `SharedState`, then pages the chain after releasing
    /// that outer lock. The store's internal `Mutex<Connection>` remains the sole
    /// serialization point, and existing field reads dereference transparently.
    pub chain_store: Arc<SqliteChainStore>,
    pub trust_store: TrustStore,
    /// Durable inbound mailbox (entity-edge inbox): still-sealed notices parked
    /// by `hestia_notify {defer: true}` before the hub is ACKed, drained by
    /// `hestia_inbox`. Encrypted at rest under the same storage key as the
    /// witness chain, in its own file (queue ≠ ledger — two persistences).
    /// Shared for the same reason as `chain_store`: the projector's obligations
    /// and cursor live here.
    pub inbox_store: Arc<crate::storage::SqliteInboxStore>,
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
    /// OPERATOR GRANTS — per-`(plugin_id, role)`, and the ONLY input in the whole fold that
    /// may LOOSEN (dp, 2026-08-01).
    ///
    /// Every other input tightens by construction: role overlay, instance overlay and hub law
    /// all fold strictest-wins, so law can only get stricter as it gets more specific. That
    /// invariant is load-bearing and is NOT relaxed here — this is a separate, narrower channel
    /// that sits outside the fold, and three properties are what make it safe to have at all:
    ///
    /// 1. **Memory only.** Never serialized, never written to the vault file. A grant cannot
    ///    outlive the daemon, so the blast radius of forgetting to revoke one is bounded by the
    ///    next restart. Ephemerality is the safety property here — the exact inverse of the
    ///    escalation store, where persistence is the safety property, because a human RULING
    ///    must survive a deploy while a standing GRANT must not.
    /// 2. **Operator-set only.** Reachable through the operator-gated HTTP surface
    ///    (challenge-signed session) and deliberately NOT exposed as an MCP tool. An agent
    ///    cannot change its own policy or another agent's. `no_mcp_tool_can_set_an_operator_grant`
    ///    asserts this rather than leaving it to nobody having written the tool yet.
    /// 3. **Readable by the subject.** An agent can always ask what it is operating under via
    ///    `hestia_operating_law`, which reports the grant and who made it. A loosening the
    ///    subject cannot see is a trapdoor; one it can see is a disclosed exception.
    ///
    /// Society baseline is NOT this. The baseline lives in society law and moves only by
    /// amendment — a grant is a scoped exception to it, never an edit of it.
    pub instance_grants: HashMap<(String, String), InstanceGrant>,
    /// Scope requests and the operator's answers, keyed by request id. See `ScopeRequest`.
    ///
    /// Memory-only for the same reason `instance_grants` is: this widens reach, so it must
    /// expire on its own. It is the ANSWER to the deny text that has been telling members to
    /// "request it" since before there was anywhere to send the request.
    ///
    /// Deliberately keyed by id and not by `(plugin, path)`: the record of an ASK that was
    /// refused is as much of the account as the record of one that was granted, and a map
    /// keyed by target would let a re-ask overwrite a refusal.
    pub scope_requests: HashMap<String, ScopeRequest>,
    /// STANDING scope grants — the third row of `POLICY_SCOPE_ASYMMETRY`: durable,
    /// operator-decided, vault-persisted (`scope`/`standing` document), generation-counted.
    /// Loaded at startup, written back through `persist_standing_scope` on every operator
    /// decision. Mutated ONLY from the operator-gated HTTP surface; no MCP tool reaches it
    /// (`no_mcp_tool_can_mutate_standing_scope`). See `server::standing_scope`.
    pub standing_scope: crate::server::standing_scope::StandingScopeStore,
    /// TRUE while the in-memory standing store is TIGHTER than the persisted vault copy —
    /// set when a revoke's vault write fails after the row was already removed from memory
    /// (memory keeps the tighter state on purpose). While set, the revoke surface accepts a
    /// retry for a row memory no longer holds and re-persists the current state, instead of
    /// 404ing the operator out of the promised recovery (GPT review of #431, blocker 2).
    /// Never persisted: a restart reloads the vault copy, at which point memory and vault
    /// agree again (the grant resurrects, visibly, and a fresh revoke takes the normal path).
    pub standing_scope_dirty: bool,
    /// Hub-law gate (consolidation, 2026-07-10): the third fold input.
    /// `None` = no law file at `$HESTIA_HOME/law/hub-law.yaml` (no-op);
    /// `Some(Invalid)` fails closed. See `policy::law_gate`.
    pub law_gate: Option<crate::policy::LawGate>,
    /// Plugin IDs that self-declared as synthetic (test harnesses,
    /// fuzzers, etc.). Excluded from operator-facing aggregations by
    /// default. Enclosed in the vault (document `presence`/`synthetic`).
    pub synthetic_plugins: HashSet<String>,
    pub home: PathBuf,
    /// Structural per-sender flood guard on the member mesh (Kimi review
    /// 2026-07-24, Finding 2): `member_notify` is law-gateable but default-allow
    /// on a permissive base, so the daemon itself bounds wake volume. This is
    /// not trust law — it is plumbing that keeps a runaway sender from evicting
    /// queued notices (drop-oldest cap) or spinning another member's auto-fire.
    pub member_notify_limiter: crate::policy::RateLimiter,
    /// Single-use OID4VCI `c_nonce`s issued but not yet redeemed.
    pub vci_nonces: HashSet<String>,
    /// Operator-surface auth (RWOA W/O): issued challenges (anti-replay) and
    /// established operator sessions. See `server::operator_auth`.
    pub operator_challenges: crate::server::operator_auth::ChallengeStore,
    pub operator_sessions: crate::server::operator_auth::SessionStore,
    /// Pending human-approval escalations for writes to the governance surface (stage 2 of
    /// dp's 2026-07-29 ruling). In-memory ON PURPOSE: a restart drops them, and every
    /// escalation in flight then reads Expired, which is a deny. Persisting them would let a
    /// write survive a restart nobody witnessed.
    pub gate_escalations: crate::server::gate_escalation::EscalationStore,
}

/// Unix seconds now — the single clock for operator challenge/session TTLs.
pub fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Lexically normalise a scope path so that a grant and a check agree on what "the same file"
/// means, without touching the filesystem.
///
/// Collapses repeated separators, drops `.`, and resolves `..` against the accumulated prefix.
/// Purely textual: it does NOT resolve symlinks and does not stat anything, because the daemon
/// records the grant while the plugin gate enforces it, and the two may not even see the same
/// mount. What this buys is that `/a//b/../b/c` and `/a/b/c` cannot become two different grants
/// — which would let a member hold a grant it cannot use, or an operator revoke one that stays
/// live under another spelling.
///
/// A `..` that would escape the root is dropped rather than kept, so no normalised path can
/// climb above `/`.
pub fn normalize_scope_path(path: &str) -> String {
    let p = path.trim();
    let mut out: Vec<&str> = Vec::new();
    for seg in p.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                out.pop();
            }
            s => out.push(s),
        }
    }
    let joined = out.join("/");
    if p.starts_with('/') {
        format!("/{joined}")
    } else {
        joined
    }
}

/// A durable scope widening that failed part-way, named by WHAT IS TRUE AFTERWARDS.
///
/// The variants are the point. Each says exactly what the chain holds and what the store
/// holds, so an HTTP surface can report the real state instead of a generic 500 that leaves
/// the operator guessing which half landed — and so the one genuinely dangerous case
/// (`LiveButUnconfirmed`) is distinguishable from the two benign ones.
#[derive(Debug)]
pub enum StandingGrantFailure {
    /// Nothing happened. No record, no grant.
    IntentNotWitnessed(anyhow::Error),
    /// The intent is on the chain; the store is untouched. No `scope_granted` exists, so no
    /// reader can conclude the member holds this reach. Retryable.
    NotCommitted {
        intent_hash: String,
        err: anyhow::Error,
    },
    /// The grant IS LIVE and durable, but the success record could not be appended. The intent
    /// is on the chain, so the widening is not unrecorded — it is UNDER-recorded. This is the
    /// variant a caller must surface loudly rather than retry: retrying would commit a second
    /// identical grant (harmless — `add` replaces) but would not undo the missing record.
    LiveButUnconfirmed {
        intent_hash: String,
        err: anyhow::Error,
    },
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
        let chain_store = Arc::new(SqliteChainStore::open(home.join("witness.db"), store_key)?);
        let trust_store = TrustStore::open(home.join("trust"), store_key)?;
        let inbox_store = crate::storage::SqliteInboxStore::open(home.join("inbox.db"), store_key)?;
        // The disposition projection cursor is initialized HERE — synchronously,
        // at state open, before any ruling surface is reachable (revised #480
        // review, blocker 2). The r3 shape initialized it lazily on the worker's
        // first pass, which had a loss window: cursor not yet written + a ruling
        // lands + its fast-path ensure fails = the later cold start jumps to the
        // new tail and permanently skips that ruling. With the watermark written
        // at open, no ruling can ever land before the cursor exists. Cold start
        // still means THE TAIL (history is not backfilled implicitly); on any
        // daemon that already ran once, the row exists and this is a no-op read.
        if inbox_store
            .projection_cursor(DISPOSITION_PROJECTION_CURSOR)?
            .is_none()
        {
            let tail = chain_store.len()?;
            inbox_store.set_projection_cursor(DISPOSITION_PROJECTION_CURSOR, tail)?;
        }
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

        // Standing scope grants (durable loosenings — POLICY_SCOPE_ASYMMETRY row 3).
        // Present-but-unparseable must abort startup like the synthetic set: collapsing a
        // corrupt store to empty would silently drop operator-made durable grants, and a
        // ruling that vanishes without a trace is the exact failure the escalation-replay
        // block above refuses. An ABSENT document is a fresh install and empty is correct.
        let standing_scope: crate::server::standing_scope::StandingScopeStore = {
            use anyhow::Context;
            crate::vault::load_doc(&vault, "scope", "standing", "standing-scope.json").context(
                "standing-scope store unreadable — failing closed instead of dropping \
                 operator-made durable grants",
            )?
        };

        let mut st = Self {
            scope_tally: std::collections::HashMap::new(),
            vault,
            sessions: HashMap::new(),
            actions: HashMap::new(),
            chain_store,
            trust_store,
            inbox_store: Arc::new(inbox_store),
            sovereign_lct,
            sovereign,
            role_registry,
            member_registry,
            shared_context: serde_json::Map::new(),
            policy_engine,
            role_policy_engines,
            instance_policy_engines,
            // Empty at every startup, by design: grants do not survive a restart. Escalations
            // DO — see the rehydrate call after construction. The two are opposite on purpose:
            // a human's ruling must survive a deploy, a standing permission must not.
            instance_grants: HashMap::new(),
            // Same reasoning, same lifetime: a widening dies with the daemon.
            scope_requests: HashMap::new(),
            // The deliberate exception (row 3): standing grants are durable and were just
            // loaded from the vault, so an operator's standing ruling survives the deploy.
            standing_scope,
            // Memory was just loaded FROM the vault, so the two agree by construction.
            standing_scope_dirty: false,
            law_gate,
            synthetic_plugins,
            home: home.to_path_buf(),
            member_notify_limiter: crate::policy::RateLimiter::new(),
            vci_nonces: HashSet::new(),
            operator_challenges: crate::server::operator_auth::ChallengeStore::default(),
            operator_sessions: crate::server::operator_auth::SessionStore::default(),
            gate_escalations: Default::default(),
        };

        // REHYDRATE ESCALATIONS FROM THE CHAIN.
        //
        // Without this, a restart destroyed every pending escalation and every approval a human
        // had already granted. Measured 2026-08-01: dp approved a governance write, a deploy
        // restarted the daemon minutes later, and the ruling was gone — so the act of deploying
        // governance was what destroyed the governance. Under fail-closed with one gate, that is
        // a fleet stopped mid-approval with the approval lost.
        //
        // The chain is read NEWEST-first, so it is reversed: replay amends in arrival order and
        // applying a decision before the open it belongs to would drop it.
        let now = crate::server::gate_escalation::now_secs();
        // A FAILED replay read must not look like "there was nothing to restore". Under
        // `.unwrap_or_default()` a read error silently produced zero live escalations, and the
        // only log line fired when the count was NON-zero — so the failure case was the silent
        // one. That is the worst direction here: every in-flight approval an operator had already
        // granted would be gone, with the daemon reporting nothing at all.
        let mut window = match st.chain_store.read_recent(ESCALATION_REPLAY_SCAN) {
            Ok(w) => w,
            Err(e) => {
                eprintln!(
                    "[hestia] CRITICAL: escalation replay read FAILED ({e}) — live escalations \
                     were NOT restored. Any approval granted before this restart is lost and must \
                     be re-filed. This is not the same as there having been none."
                );
                tracing::error!("escalation replay chain read failed: {e}");
                Vec::new()
            }
        };
        window.reverse();
        let restored = st.gate_escalations.rehydrate(&window, now);
        // Log the zero too. "restored 0" and "did not look" are different facts, and only one of
        // them used to be visible.
        eprintln!("[hestia] restored {restored} live escalation(s) from the chain");
        Ok(st)
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
    /// Apply an operator grant for `(plugin_id, role)`, if one is live.
    ///
    /// ONE implementation for every evaluation site. There are three — `tool_operating_law`
    /// (what a member is told it is under), `tool_query_policy` (what it is told when it asks
    /// about an action), and `gate_direct_tool` (what actually happens). A grant applied to
    /// some of those and not others produces the worst possible failure: the member is told one
    /// law and enforced under another, and whichever surface someone checks will look correct.
    /// Duplicating this by hand is how that happens, so it is written once and called thrice.
    ///
    /// SUBSTITUTION, not a fold. The operator said "this member runs under THIS preset"; taking
    /// the stricter of the two would silently discard the instruction, which is the entire point
    /// of the control. Every other input composes strictest-wins and keeps that invariant intact
    /// — this is the one explicit exception, and it is a separate function so it stays legible
    /// rather than becoming a branch inside a comparator.
    ///
    /// Callers must apply this BEFORE folding hub law, so ratified society law still binds. See
    /// the ordering note at the `gate_direct_tool` call site.
    pub fn apply_instance_grant(
        &self,
        plugin_id: &str,
        role: &str,
        pa: &crate::policy::PolicyAction,
        evaluation: crate::policy::PolicyEvaluation,
    ) -> crate::policy::PolicyEvaluation {
        match self
            .instance_grant(plugin_id, role)
            .and_then(|g| crate::policy::get_preset(&g.preset))
        {
            Some(p) => crate::policy::PolicyEngine::new(p.config).evaluate(pa),
            None => evaluation,
        }
    }

    /// Strictness ordering over the built-in presets, so the daemon can tell a TIGHTENING from a
    /// LOOSENING and route each to the store that fits its lifetime (dp, 2026-08-01).
    ///
    /// `permissive` and `audit-only` both let everything through — audit-only records and does
    /// not enforce — so both rank below the enforcing presets. The exact spacing does not
    /// matter; only the order does, and only to answer one question: does this grant widen what
    /// the member may do, or narrow it?
    pub fn preset_strictness(name: &str) -> u8 {
        match name {
            "permissive" => 0,
            "audit-only" => 1,
            "safety" => 2,
            "strict" => 3,
            // An unknown preset is treated as the strictest thing we know. It cannot be used to
            // widen by being unrecognised.
            _ => u8::MAX,
        }
    }

    /// Is `preset` a loosening relative to the society baseline currently in force?
    pub fn is_loosening(&self, preset: &str) -> bool {
        let society = self.vault.policy().active_preset.clone();
        Self::preset_strictness(preset) < Self::preset_strictness(&society)
    }

    /// The live grant for `(plugin_id, role)`, for surfaces that must DISCLOSE it rather than
    /// merely apply it. A loosening the subject cannot see is a trapdoor.
    ///
    /// Falls back to the wildcard role `*` for the same plugin. dp, 2026-08-01: the operator
    /// selects an AGENT on the dashboard, not an (agent, role) pair — "when an agent is selected
    /// and the chain shows only its actions, clicking the policy button should only change the
    /// policy for the selected agent". A member acts under several roles over its life, and
    /// requiring the operator to know which one is live right now would make the control
    /// unusable at exactly the moment it is reached for: something is stuck and needs unblocking.
    ///
    /// Exact match wins, so a role-specific grant is still expressible and still beats the
    /// wildcard — narrow before broad, which is the same precedence every other layer uses.
    pub fn instance_grant(&self, plugin_id: &str, role: &str) -> Option<&InstanceGrant> {
        let now = crate::server::gate_escalation::now_secs();
        self.instance_grants
            .get(&(plugin_id.to_string(), role.to_string()))
            .or_else(|| {
                self.instance_grants
                    .get(&(plugin_id.to_string(), "*".to_string()))
            })
            .filter(|g| g.is_live(now))
    }

    /// Every live scope grant a member currently holds — what the gate consults, and what
    /// `hestia_operating_law` discloses.
    ///
    /// NOT role-scoped, unlike `instance_grant`. A path grant answers "may this member read
    /// this file for this session", and the member does not change identity when it changes
    /// role. Adding a role dimension here would only create a way for a grant to silently
    /// stop applying midway through the work it was granted for.
    pub fn live_scope_grants(&self, plugin_id: &str) -> Vec<&ScopeRequest> {
        let now = crate::server::gate_escalation::now_secs();
        let mut live: Vec<&ScopeRequest> = self
            .scope_requests
            .values()
            .filter(|r| r.plugin_id == plugin_id && r.granted == Some(true) && now < r.expires_at)
            .collect();
        live.sort_by_key(|r| r.requested_at);
        live
    }

    /// Does this member hold a live grant for exactly this path?
    ///
    /// **Exact match, deliberately.** A grant is for one file. Prefix matching here would turn
    /// "you may read `/x/y/notes.md`" into "you may read everything under `/x/y`", which is the
    /// scope grab this whole mechanism exists to make unnecessary — and it would do it silently,
    /// with the operator's approval attached to the narrower thing they actually read.
    ///
    /// Paths are compared after lexical normalisation only. This is A1: the caller asserts its
    /// own plugin_id and the plugin-side gate does the enforcing, so this answers "is there a
    /// grant of record", not "is this filesystem object reachable". A symlink is still a
    /// symlink; see `docs/GATE_BYPASS_CATALOG.md`.
    pub fn has_scope_grant(&self, plugin_id: &str, path: &str) -> bool {
        let now = crate::server::gate_escalation::now_secs();
        let want = normalize_scope_path(path);
        self.scope_requests
            .values()
            .any(|r| r.plugin_id == plugin_id && r.grants(&want, now))
            // A STANDING grant answers the same question — "is there a grant of record for
            // exactly this path" — so a member re-asking for a path it durably holds hears
            // `already_granted` instead of filing an ask nobody needs to rule on.
            || self.standing_scope.has_live(plugin_id, &want, now)
    }

    /// Every live STANDING grant this member holds (durable row of the asymmetry).
    /// Expiry is filtered at the read, in the store, so no serving surface can leak one.
    pub fn live_standing_grants(
        &self,
        plugin_id: &str,
    ) -> Vec<&crate::server::standing_scope::StandingGrant> {
        let now = crate::server::gate_escalation::now_secs();
        self.standing_scope.live_for(plugin_id, now)
    }

    /// Write the standing-scope store back to its vault document. The vault's own save is
    /// temp-file-and-rename, so the on-disk document is atomic. Prefer the two shaped
    /// entry points below — `commit_standing_scope` for widenings, `apply_standing_revoke`
    /// for tightenings — which encode what a failed persist means for each direction.
    pub fn persist_standing_scope(&mut self) -> Result<()> {
        crate::vault::save_doc(
            &mut self.vault,
            "scope",
            "standing",
            "standing-scope.json",
            &self.standing_scope,
        )
    }

    /// Mutate the standing store through a CANDIDATE that is persisted BEFORE it becomes
    /// live (GPT review of #431, blocker 1). The first version mutated live and "rolled
    /// back" a failed persist by calling `revoke()` — which bumped the generation a second
    /// time and, for a REPLACEMENT, discarded the prior durable grant instead of restoring
    /// it, while the error text claimed the store was unchanged. Here unchangedness is a
    /// property of the construction: on any persist failure the live store was never
    /// touched, generation included, so there is nothing to claim and nothing to restore.
    pub fn commit_standing_scope<F>(&mut self, mutate: F) -> Result<()>
    where
        F: FnOnce(&mut crate::server::standing_scope::StandingScopeStore),
    {
        let mut candidate = self.standing_scope.clone();
        mutate(&mut candidate);
        crate::vault::save_doc(&mut self.vault, "scope", "standing", "standing-scope.json", &candidate)?;
        self.standing_scope = candidate;
        // The vault now holds exactly what memory holds, so any earlier revoke-persist
        // failure has been overtaken: the synced state is the tighter one plus this
        // committed mutation.
        self.standing_scope_dirty = false;
        Ok(())
    }

    /// INTENT → COMMIT → SUCCESS. The one place the ordering of a durable scope widening is
    /// decided, so both doors (`/api/scope/grant` and `/api/scope/decide {standing:true}`)
    /// obey it by construction rather than by each remembering to.
    ///
    /// WHY THIS EXISTS (GPT review of #462, 2026-08-15). Both doors used to
    /// `append_chain("scope_granted", ..)` and THEN `commit_standing_scope(..)`. The ordering
    /// was deliberate and half right: witness-then-widen is correct, because the opposite
    /// order can leave a LIVE grant that nothing recorded. But the event appended first was
    /// named `scope_granted` — a SUCCESS NAME — so a failed vault write left the chain
    /// asserting a grant that never came into force.
    ///
    /// I had documented that outcome and called it "the safe direction, and legible". It is
    /// not. It is safe only against the other ordering; in the auditing direction it is the
    /// worse failure, because a false `scope_granted` is a PHANTOM WIDENING — a reader, the
    /// reputation fold, and the ledger all conclude a member held reach it never had, and
    /// nothing in the chain contradicts them. "Legible" was doing the work of a mechanism.
    ///
    /// The split fixes it without giving up witness-then-widen:
    ///   1. `scope_grant_intent` — the full evidence, named as an ATTEMPT.
    ///   2. the durable commit.
    ///   3. `scope_granted` — appended only once the grant is really in force, carrying
    ///      `intent` so the pair is joinable.
    /// A reader that sees an intent with no matching `scope_granted` is looking at a widening
    /// that did not take effect, which is exactly what happened.
    ///
    /// Old readers are strictly better off, not worse: `scope_granted` now appears only when
    /// it is true. They ignore the new `scope_grant_intent` kind, so a FAILED grant becomes
    /// invisible to them rather than a false success — incomplete beats actively misleading,
    /// and the intent record is there for anyone who looks.
    pub fn witness_and_commit_standing_grant(
        &mut self,
        grant: crate::server::standing_scope::StandingGrant,
        record: serde_json::Value,
    ) -> std::result::Result<(String, String), StandingGrantFailure> {
        // 1. INTENT. Carries the same evidence the success record will, so a failure at step 2
        //    still leaves a complete account of what was attempted and why.
        let intent = self
            .append_chain("scope_grant_intent", record.clone())
            .map_err(StandingGrantFailure::IntentNotWitnessed)?;

        // 2. COMMIT. `commit_standing_scope` persists a candidate before swapping it live, so
        //    on failure the live store is bit-identical — generation included.
        if let Err(err) = self.commit_standing_scope(|st| st.add(grant)) {
            return Err(StandingGrantFailure::NotCommitted {
                intent_hash: intent.hash,
                err,
            });
        }

        // 3. SUCCESS — now, and only now, is `scope_granted` true.
        let mut success = record;
        if let Some(map) = success.as_object_mut() {
            map.insert("intent".into(), serde_json::json!(intent.hash));
            map.insert(
                "standing_generation".into(),
                serde_json::json!(self.standing_scope.generation),
            );
        }
        match self.append_chain("scope_granted", success) {
            Ok(e) => Ok((intent.hash, e.hash)),
            Err(err) => Err(StandingGrantFailure::LiveButUnconfirmed {
                intent_hash: intent.hash,
                err,
            }),
        }
    }

    /// Apply a standing revoke: remove from memory FIRST (a failure may only ever leave
    /// the TIGHTER state in force), then persist. Idempotent by design — revoking a row
    /// memory no longer holds still persists the current state — which is what makes the
    /// failure mode RETRYABLE (GPT review of #431, blocker 2): after a failed vault write
    /// the row is gone from memory, so a retry that demanded in-memory existence would 404
    /// the operator out of the promised recovery while the vault still held the grant,
    /// waiting to resurrect it at the next restart. `standing_scope_dirty` tracks the
    /// memory-tighter-than-vault window so the HTTP surface can tell a legitimate retry
    /// from a typo.
    pub fn apply_standing_revoke(&mut self, member: &str, path: &str) -> Result<()> {
        self.standing_scope.revoke(member, path);
        match self.persist_standing_scope() {
            Ok(()) => {
                self.standing_scope_dirty = false;
                Ok(())
            }
            Err(e) => {
                self.standing_scope_dirty = true;
                Err(e)
            }
        }
    }

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

    /// Resolve a chain-entry pointer — full hash or an abbreviation of it.
    ///
    /// The chain's public identifier is its hash: appeals cite `deny_hash`,
    /// adjudications cite `claim_ref`, mesh notices carry
    /// `hestia://adjudication/<hash>`, and the operating law cites rulings by an
    /// eight-character prefix. Every one of those is a POINTER, and until this
    /// existed no read surface could follow one — `recent_chain` is the only
    /// exposed reader and it is a count-window over the tail, so an entry more
    /// than a few hundred events old was addressable and unreachable at the same
    /// time. That is the filtered-window illusion one level up: the reference
    /// looks resolvable, and the failure to resolve it looks like absence.
    ///
    /// Returns the matches (0, 1, or several on an ambiguous prefix) and lets the
    /// caller report which case it is. `Err` means the pointer was malformed.
    /// Ambiguity is reported, not resolved — but the report must not lie about
    /// its own scale, so this cap bounds the ENTRIES LISTED only; the count
    /// beside them comes from `chain_prefix_match_count` and is uncapped.
    pub const CHAIN_POINTER_LIST_CAP: u64 = 8;

    pub fn chain_by_pointer(&self, hash_or_prefix: &str) -> Result<Vec<ChainEntry>> {
        // Validate BEFORE branching on length. The full-hash arm is an equality
        // match that would happily return "no such entry" for a 64-character
        // non-hash, which is the malformed-reads-as-absent conflation this
        // resolver was written to remove.
        let ptr = crate::storage::chain::validate_hash_pointer(hash_or_prefix)?;
        if ptr.len() == 64 {
            return Ok(self.chain_store.read_by_hash(&ptr)?.into_iter().collect());
        }
        self.chain_store
            .read_by_hash_prefix(&ptr, Self::CHAIN_POINTER_LIST_CAP)
    }

    /// True number of entries a prefix matches, for the ambiguity report only.
    pub fn chain_prefix_match_count(&self, prefix: &str) -> Result<u64> {
        self.chain_store.count_by_hash_prefix(prefix)
    }

    /// Apply an outcome to the trust state for a plugin.
    pub fn apply_outcome(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
    ) -> Result<EntityTrust> {
        let ctx = crate::reputation::RepContext {
            // Same reasoning as `tool_record_outcome`: this wrapper takes
            // `success` as a PARAMETER, so it cannot establish whether a
            // failure was member conduct or an environmental one. Held.
            // (Only test callers reach it today; classifying it honestly now
            // means a future production caller inherits the safe answer rather
            // than an inherited claim.)
            class: crate::reputation::DeltaClass::Unclassified,
            role_lct: crate::reputation::V1_CONSTELLATION_ROLE,
            action_type: "outcome",
            action_target: "",
            action_id: "",
            rule_triggered: "",
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

    /// The adjudicated-V3 grain for an `(instance, role)` pair — Stage 1 of the
    /// T3-from-V3 arc. A DEDICATED entity for the same reason `#judgment`
    /// exists: the ~10^3/day execution stream refills any shared scalar within
    /// minutes, and the execution entity's stored V3 is a saturating action
    /// counter (+0.01/outcome), not value. Only adjudications move this one.
    pub fn adjudicated_entity_key(&self, plugin_id: &str, role_lct: &str) -> String {
        format!("{}#adjudicated", self.trust_entity_key(plugin_id, role_lct))
    }

    /// Read the adjudicated-V3 trust for a grain (receipts + derivation read this).
    pub fn adjudicated_for_role(&self, plugin_id: &str, role_lct: &str) -> EntityTrust {
        let key = self.adjudicated_entity_key(plugin_id, role_lct);
        self.trust_store
            .get(&key)
            .unwrap_or_else(|_| EntityTrust::new(key))
    }

    /// Apply one adjudicated V3 observation to the subject's `#adjudicated`
    /// grain and emit the role-scoped delta (action_type `"adjudication"`
    /// separates the stream in the bridge sink; Stage 4 drains it to the hub).
    pub fn apply_adjudication_ctx(
        &self,
        subject_plugin_id: &str,
        dimension: web4_core::v3::ValueDimension,
        score: f64,
        ctx: &crate::reputation::RepContext,
    ) -> Result<EntityTrust> {
        let key = self.adjudicated_entity_key(subject_plugin_id, ctx.role_lct);
        let (before, after) = self
            .trust_store
            .update_v3_returning_prior(&key, dimension, score)?;
        if let Some(subject_lct) = self.member_lct(subject_plugin_id) {
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

    /// Resolve a plugin_id from a session_id provided in tool args. FAIL-CLOSED: an absent or
    /// unresolvable session_id yields None (deny) — never the most-recently-connected session. That
    /// former fallback was ambient authority and it races under exactly the concurrency the session
    /// coordinator manages (same class as the session/own fix, dfe4c6f; §5.5 defect, McNugget). WHO on
    /// the credential path must be an explicit, resolvable session, not whoever connected last.
    pub fn resolve_plugin_id(&self, session_id: Option<&str>) -> Option<String> {
        let uuid = Uuid::parse_str(session_id?).ok()?;
        self.sessions.get(&uuid).map(|s| s.plugin_id.clone())
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
            class: crate::reputation::DeltaClass::Conduct,
            role_lct: role,
            action_type: "outcome",
            action_target: "",
            action_id: "",
            rule_triggered: "",
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

    /// THE ALIAS GUARD REACHES NOTHING ITS CALL SITES CLAIM. Measured 2026-08-06.
    ///
    /// Three surfaces decide "same entity wearing two names" by comparing
    /// `member_lct(a) == member_lct(b)`, and each cites the same evidence: codex
    /// acting as `codex` while its gate witnesses as `codex-cli`, "the measured case
    /// on this fleet".
    ///
    ///   - `handler.rs` `select_arbiter` pool filter — drops same-entity candidates
    ///   - `handler.rs` `tool_arbitrate_appeal`  — `same_entity` before eligibility
    ///   - `handler.rs` `tool_open_appeals`      — `same_entity` in `you_may_rule`
    ///
    /// None of them can. `member_lct` is sha256 over the TRIMMED RAW STRING (note
    /// `legacy_alias` is derivation provenance, label↔LCT — it does not relate two
    /// members). So the comparison is true iff the two ids are equal after trimming,
    /// which `arbiter::eligibility` clause 1 already refuses on, one line earlier. The
    /// guard's entire reach beyond clause 1 is WHITESPACE, pinned below.
    ///
    /// THE ALIAS IS NOT MISSING — IT IS UNREAD. `derivation::alias_target` resolves
    /// `IDENTITY_ALIAS_EVENT` records, and the chain carries one, witnessed by the
    /// operator 2026-07-26, for precisely `codex-cli → codex`. Its only caller is the
    /// dashboard, for display. So a ratified governance fact about who is one actor
    /// governs nothing on the path whose comments cite it.
    ///
    /// AND THE OBVIOUS WIRING IS A NO-OP. `alias_target` scans a chain window; the
    /// appeal path's is `APPEAL_CHAIN_WINDOW = 20_000`, which on 2026-08-06 reached
    /// back only to 08-01 — the 07-26 alias record had already scrolled out. Passing
    /// the existing window returns None and changes nothing while reviewing like a
    /// fix. A correct repair needs a durable alias index rebuilt at load, as
    /// `member_registry` and `role_registry` already are — not a window scan over a
    /// chain that rotates past governance facts. Assert the EFFECT at the read.
    ///
    /// See `member_lct_is_stable_per_plugin_and_distinct_across_plugins`: the
    /// invariant that makes this guard inert is itself a tested, deliberate property.
    #[test]
    fn the_member_lct_alias_guard_reaches_only_whitespace() {
        let (_dir, state) = make_state();
        let same_entity = |a: &str, b: &str| {
            let (x, y) = (state.member_lct(a), state.member_lct(b));
            x.is_some() && x == y
        };
        // The cited case. Distinct strings => distinct hashes => the guard is silent.
        assert!(
            !same_entity("codex", "codex-cli"),
            "if this ever passes an alias map was added — update the three call-site \
             comments, which have claimed this since before one existed"
        );
        // Nor any other two-names-one-actor shape a reader might assume is covered.
        assert!(!same_entity("claude-code", "claude"));
        assert!(!same_entity("kimi-code", "kimi"));
        // What it DOES add over clause 1's `p.arbiter == p.appellant` string compare.
        assert!(same_entity("codex", " codex "), "trim is the guard's whole reach");
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
                role_basis: None,
                soft_lct: "lct:test:a".into(),
                connected_at: Utc::now(),
                host_session_id: None,
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
                role_basis: None,
                soft_lct: "lct:test:b".into(),
                connected_at: Utc::now() + chrono::Duration::seconds(1),
                host_session_id: None,
            },
        );

        assert_eq!(
            state.resolve_plugin_id(Some(&sid_a.to_string())),
            Some("alice".into())
        );
        // FAIL-CLOSED: absent session_id resolves to None, NOT the most-recent session (the ambient-
        // authority fallback was removed — §5.5; a caller that doesn't identify itself gets no identity).
        assert_eq!(state.resolve_plugin_id(None), None);
        // unknown session_id resolves to None (no fallback)
        assert_eq!(
            state.resolve_plugin_id(Some("00000000-0000-0000-0000-000000000000")),
            None
        );
    }

    fn a_grant(member: &str, path: &str) -> crate::server::standing_scope::StandingGrant {
        crate::server::standing_scope::StandingGrant {
            member: member.into(),
            path: path.into(),
            granted_at: 1_000,
            granted_by: "operator".into(),
            reason: "forced-failure fixture".into(),
            expires_at: None,
            request_id: None,
        }
    }

    /// Chain-ordered (OLDEST first). `read_recent` returns newest-first, and asserting on its
    /// raw order made a correct implementation look reversed — the assertion was wrong, not
    /// the code. Sorting by `chain_position` here states the property the tests actually mean.
    fn kinds(state: &ServerState) -> Vec<String> {
        let mut es = state.chain_store.read_recent(50).unwrap();
        es.sort_by_key(|e| e.chain_position);
        es.into_iter().map(|e| e.event_type).collect()
    }

    fn position_of(state: &ServerState, hash: &str) -> u64 {
        state
            .chain_store
            .read_recent(50)
            .unwrap()
            .into_iter()
            .find(|e| e.hash == hash)
            .unwrap_or_else(|| panic!("{hash} is not on the chain"))
            .chain_position
    }

    /// THE HAPPY ARM. Both records land, in order, and the success record joins to its intent.
    #[test]
    fn a_durable_grant_witnesses_intent_then_commits_then_success() {
        let (_dir, mut state) = make_state();
        let before = kinds(&state).len();
        let (intent_hash, granted_hash) = state
            .witness_and_commit_standing_grant(
                a_grant("kimi-code", "/w/hestia"),
                serde_json::json!({"plugin_id": "kimi-code", "path": "/w/hestia"}),
            )
            .expect("the happy path commits");

        let ks = kinds(&state);
        let added: Vec<&String> = ks.iter().skip(before).collect();
        assert_eq!(
            added,
            vec!["scope_grant_intent", "scope_granted"],
            "intent must precede success, and both must exist: {ks:?}"
        );
        assert_ne!(intent_hash, granted_hash);
        // The ORDERING invariant, stated directly rather than inferred from list order.
        assert!(
            position_of(&state, &intent_hash) < position_of(&state, &granted_hash),
            "the intent must sit strictly BELOW the success on the chain — that ordering is \
             the whole guarantee: a reader scanning forward can never meet a `scope_granted` \
             whose grant had not yet committed"
        );
        assert!(state.standing_scope.has_live("kimi-code", "/w/hestia", 1_000));

        // The pair must be JOINABLE — an intent nobody can match to its outcome is only half
        // a record.
        let success = state
            .chain_store
            .read_recent(50)
            .unwrap()
            .into_iter()
            .find(|e| e.hash == granted_hash)
            .unwrap();
        assert_eq!(
            success.event_data["intent"].as_str(),
            Some(intent_hash.as_str()),
            "the success record must name the intent it completes"
        );
    }

    /// THE FORCED-FAILURE ARM (GPT review of #462) — the arm the old ordering got wrong.
    ///
    /// The failure is injected by putting a DIRECTORY where the vault's atomic-write temp file
    /// must go (`storage::save` writes `<vault>.enc.tmp` then renames). That is deliberate:
    /// it fails ONLY the vault, leaves the chain's `witness.db` fully writable, and does not
    /// depend on file permissions — which are unreliable under root and on NTFS mounts, so a
    /// chmod-based version of this test would silently pass by not failing at all.
    #[test]
    fn a_failed_commit_leaves_an_intent_and_no_scope_granted() {
        let (dir, mut state) = make_state();

        // Land one good grant first, so the test proves the failure is caused by the
        // injection and not by the mechanism never having worked.
        state
            .witness_and_commit_standing_grant(
                a_grant("kimi-code", "/w/first"),
                serde_json::json!({"plugin_id": "kimi-code", "path": "/w/first"}),
            )
            .expect("control: the mechanism works before the injection");
        let gen_before = state.standing_scope.generation;
        let kinds_before = kinds(&state);

        // Inject: a directory cannot be opened as the temp file.
        std::fs::create_dir(dir.path().join("v.enc.tmp")).unwrap();

        let err = state
            .witness_and_commit_standing_grant(
                a_grant("codex", "/w/second"),
                serde_json::json!({"plugin_id": "codex", "path": "/w/second"}),
            )
            .expect_err("the vault write must fail with a directory in the temp path");

        let intent_hash = match err {
            StandingGrantFailure::NotCommitted { intent_hash, .. } => intent_hash,
            other => panic!("expected NotCommitted, got {other:?}"),
        };

        // 1. The store is bit-identical — the grant did NOT come into force.
        assert_eq!(
            state.standing_scope.generation, gen_before,
            "a failed commit must not move the generation"
        );
        assert!(
            !state.standing_scope.has_live("codex", "/w/second", 1_000),
            "the grant must not be live"
        );

        // 2. THE POINT: the chain gained an INTENT and NO `scope_granted`. Under the old
        //    ordering this arm left a `scope_granted` for a grant that never existed — a
        //    phantom widening that every reader, including the reputation fold, would believe.
        let added: Vec<String> = kinds(&state).into_iter().skip(kinds_before.len()).collect();
        assert_eq!(
            added,
            vec!["scope_grant_intent".to_string()],
            "a failed durable grant must leave its INTENT and nothing that claims success"
        );

        // 3. The intent is findable, so the attempt is auditable rather than merely absent.
        let intent = state
            .chain_store
            .read_recent(50)
            .unwrap()
            .into_iter()
            .find(|e| e.hash == intent_hash)
            .expect("the intent must be on the chain");
        assert_eq!(intent.event_data["plugin_id"].as_str(), Some("codex"));
    }
}
