//! Dashboard snapshot — aggregations consumed by both the web UI and the TUI.
//! The HTTP surface serves an immutable read model; projection cost never rides
//! on the request path.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;

use super::state::ServerState;
use crate::storage::{ChainEntry, SqliteChainStore};
use web4_trust_core::EntityTrust;

/// Dashboard reads are display-grade projections, never authority. Keep their
/// chain window bounded and, more importantly, read it without holding the
/// authoritative [`ServerState`] lock (see [`DashboardChainProjection`]).
const STATS_WINDOW: u64 = 2_000;

/// The slow, blocking half of a dashboard snapshot.
///
/// SQLCipher owns its own connection mutex. Carrying these reads through the
/// outer `ServerState` mutex only made unrelated governance requests queue
/// behind a display projection. The HTTP read-model worker builds this value on
/// Tokio's blocking pool, then briefly re-enters state to assemble the
/// lightweight, ephemeral presentation.
pub(crate) struct DashboardChainProjection {
    deriv_window: Vec<ChainEntry>,
    stats_window: Vec<RecentEntry>,
    stats_read_error: Option<String>,
    recent: Vec<RecentEntry>,
    recent_read_error: Option<String>,
}

impl DashboardChainProjection {
    pub(crate) fn read(
        chain_store: &SqliteChainStore,
        recent_cap: u64,
        window_cutoff: Option<DateTime<Utc>>,
    ) -> Self {
        // A failed read is not zero activity. Carry failures into the snapshot
        // so the UI renders unavailable rather than fabricating a quiet fleet.
        // Each scan projects only what its consumer declares: derivation gets
        // its pruned ChainEntry, while stats/feed keep RecentEntry scalars.
        // The dashboard read its derivation window with STATS_WINDOW (2,000) while the
        // API used 10,000 — the surface a human looks at reached back FIVE TIMES less far
        // than the API answering for it, and the comment below claimed the opposite.
        // Both now share `derivation::scan_window`.
        let deriv_window = crate::derivation::scan_window(chain_store);
        let (stats_window, stats_read_error) =
            match chain_store.scan_recent(None, None, STATS_WINDOW, |r| Some(flatten_row(r))) {
                Ok(v) => (v, None),
                Err(e) => {
                    tracing::error!("dashboard stats chain read failed: {e}");
                    (Vec::new(), Some(e.to_string()))
                }
            };
        let cutoff = window_cutoff.map(|c| c.to_rfc3339());
        let (recent, recent_read_error) =
            match chain_store.scan_recent(cutoff.as_deref(), None, recent_cap, |r| {
                Some(flatten_row(r))
            }) {
                Ok(v) => (v, None),
                Err(e) => {
                    tracing::error!("dashboard recent-feed chain read failed: {e}");
                    (Vec::new(), Some(e.to_string()))
                }
            };

        Self {
            deriv_window,
            stats_window,
            stats_read_error,
            recent,
            recent_read_error,
        }
    }
}

/// The active policy setting, surfaced so the dashboard can show which gate is
/// in force (e.g. "safety, enforcing" vs "audit-only, observing").
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyView {
    /// Active preset name (`permissive` | `safety` | `strict` | `audit-only`).
    pub preset: String,
    /// `true` = denies block; `false` = audit/observe mode (decisions logged,
    /// not enforced).
    pub enforce: bool,
}

fn default_policy_view() -> PolicyView {
    PolicyView {
        preset: "safety".into(),
        enforce: true,
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DashboardSnapshot {
    pub society: SocietyView,
    pub stats: ActivityStats,
    /// Per-plugin slices of `stats` over the same window — backs the
    /// orchestrator-chip stat filter (selecting a member shows ITS activity,
    /// not the society aggregate). Same field semantics as `stats`.
    #[serde(default)]
    pub stats_by_plugin: BTreeMap<String, ActivityStats>,
    #[serde(default = "default_policy_view")]
    pub policy: PolicyView,
    pub trust: Vec<TrustView>,
    pub recent: Vec<RecentEntry>,
    /// Policy decisions (warn + deny) across the wider stats window — backs the
    /// warn/deny feed filters (the `recent` window may not include older denies).
    #[serde(default)]
    pub policy_decisions: Vec<RecentEntry>,
    /// Compatible orchestrators that are running and/or engaged — backs the
    /// orchestrator bar. Each entry carries `running` (process alive),
    /// `installed` (hooks wired into its config), `engaged` (acted in the last
    /// hour → highlighted/clickable stat filter), and `connected` (alive+wired
    /// OR recently active). The bar shows `connected` as connected and only
    /// offers "connect" when not connected — so an idle-but-live session no
    /// longer reads as disconnected after an hour of no tool calls.
    #[serde(default)]
    pub orchestrators: Vec<serde_json::Value>,
    pub delegations: Vec<serde_json::Value>,
    pub hub_connections: Vec<serde_json::Value>,
    pub profile: Option<serde_json::Value>,
    pub constellation: Option<serde_json::Value>,
    /// The calendar window this snapshot's feed + windowed stat cover
    /// ("hour" | "day" | "week" | "all") — echoed so the UI labels honestly.
    #[serde(default)]
    pub window: String,
    /// Governance-surface escalations awaiting a decision, newest first.
    ///
    /// Carried on the snapshot the dashboard already polls rather than behind a
    /// new route, because the failure this fixes is not "the operator could not
    /// fetch the queue" — it is that **nothing ever told them there was one**.
    /// A route the UI never calls is what we already had: `POST
    /// /api/operator/gate-escalation` has existed as the strongest human
    /// decision channel in the system, operator-authenticated, with no front end
    /// to reach it. Five escalations opened against dp on 2026-08-01 and the
    /// only notice of any of them was in the denied agent's own stderr.
    ///
    /// Riding the tick means a pending escalation becomes visible within one
    /// poll of being opened, with no operator action required to discover it.
    #[serde(default)]
    pub pending_escalations: Vec<serde_json::Value>,
    /// Live per-member operator grants. Surfaced on the snapshot the dashboard already polls,
    /// for the same reason the escalations are: a standing exception to society law that the
    /// operator has to go looking for is one they will forget they made. These are the only
    /// control in the system that WIDENS what an agent may do, so they should be the hardest
    /// thing in the UI to leave running by accident.
    #[serde(default)]
    pub instance_grants: Vec<serde_json::Value>,
    /// Scope requests awaiting a decision — a member asking to read ONE path outside its MRH.
    ///
    /// Carried here for the identical reason the escalations are, and it is the identical
    /// failure repeated one surface later. `hestia_request_scope` and its operator half
    /// (`GET /api/scope/requests`, `POST /api/scope/decide`) shipped 2026-08-02 with **no
    /// front end**, so kimi-code filed a correctly-formed request, with a stated reason, that
    /// dp could not see. dp, 2026-08-03: *"i don't see any open escalations"* — and later,
    /// about this exact request, *"everything you saw presented"* did not include it, because
    /// nothing presented it.
    ///
    /// The doc comment on `pending_escalations` above describes that same defect as already
    /// fixed: *"a route the UI never calls is what we already had."* It was written by the
    /// author who then built a second route the UI never called. **Building the decision
    /// surface is not building the notice**, and the notice is the half that decides whether a
    /// human ever rules.
    ///
    /// Pending only. A decided request is history and belongs in the chain, not in a queue
    /// that implies something is owed.
    #[serde(default)]
    pub pending_scope_requests: Vec<serde_json::Value>,
    /// MRH scope grants currently in force — BOTH kinds, each labelled with its lifetime.
    ///
    /// Rides the snapshot for the reason the two fields above do, and the doc comment on
    /// `pending_scope_requests` says it best: *"building the decision surface is not building
    /// the notice."* The standing store (#431) has been durable and operator-walled since it
    /// landed, and on 2026-08-15 a restart found `generation=0, standing_grants=[]` for every
    /// member — the mechanism existed and nobody had ever populated it, because nothing ever
    /// SHOWED it. There was no read path outside an MCP tool no operator calls.
    ///
    /// `lifetime` is on every row deliberately, and is the whole point of merging the two
    /// lists rather than shipping one: a `live` grant dies at the next daemon restart and a
    /// `standing` one does not, and an operator who cannot see which is which will keep
    /// spending grants that evaporate on the next deploy — which is exactly what has been
    /// happening. Two lists side by side would let the reader assume; one list with the
    /// distinction on the face of every row does not.
    #[serde(default)]
    pub scope_grants: Vec<serde_json::Value>,
    /// The standing store's generation counter — moves on every durable mutation.
    /// Rendered beside the grants so a stale panel is legible AS stale (#438).
    #[serde(default)]
    pub standing_generation: u64,
    /// Set when the chain read backing `stats` / `stats_by_plugin` FAILED.
    ///
    /// When this is present the counts are not measurements and must not be rendered as
    /// numbers — they are all zero because nothing could be read, not because nothing happened.
    /// A governance console showing a quiet fleet because its query broke is the most
    /// dangerous shape this dashboard can take: the operator is watching for unexpected agent
    /// activity, and absence is exactly the reading they would trust without checking.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stats_unavailable: Option<String>,
    /// Set when the chain read backing `recent` FAILED.
    ///
    /// THE SAME DEFECT AS `stats_unavailable`, ONE FIELD OVER, found 2026-08-04 by dp:
    /// *"chain display still blank for all agents all timelines. something got broken."*
    ///
    /// The 2026-08-01 fix hardened `read_recent(10_000)` for the stats and left
    /// `read_recent_window` — the live feed — on `.unwrap_or_default()`. So an error became an
    /// empty Vec, the daemon served HTTP 200, and the feed rendered as *nothing happened*
    /// while the panel beside it correctly said *unavailable*. The comment above the stats read
    /// already describes this exact presentation, including the words "dp saw every member
    /// empty across every timeframe... and it came back by itself later". It came back by
    /// itself again.
    ///
    /// Why it surfaced now rather than in August: `witness.db` is ~119MB and growing, the
    /// daemon sits near 800MB resident, and this read runs under the global state lock. A busy
    /// timeout or lock contention that was rare at 30MB is ordinary at 119MB — the failure rate
    /// rose to meet a hazard that had been latent the whole time.
    ///
    /// A governance console showing a quiet fleet because its query broke is the most dangerous
    /// shape this dashboard can take: the operator is watching for unexpected agent activity,
    /// and absence is exactly the reading they would trust without checking.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recent_unavailable: Option<String>,
    /// HOW THESE NUMBERS WERE OBTAINED — so a relying party can decide whether the
    /// compression is sufficient for its purpose, or whether to escalate to the chain.
    ///
    /// dp, 2026-08-06: *"the witness chain is sacred... how we leverage it is very much
    /// context-dependent. there may be cases where full chain traversal is necessary. but
    /// it is expensive... the caveat is that we should always be clear which is which so
    /// the relying party can choose whether to escalate or accept compression as
    /// sufficient for purpose."*
    ///
    /// This is the web4 posture applied to our own readings: produce checkable evidence
    /// and let the caller decide, rather than smuggling a verdict. A compressed answer
    /// that does not say it is compressed asks to be trusted as a complete one — which is
    /// the same substitution `EvidenceClass` and `OccupancyBasis` exist to prevent, on a
    /// third surface.
    #[serde(default)]
    pub basis: ReadBasis,
    /// Whether the running daemon matches the deployment manager's current artifact.
    /// The manager publishes the reference; the daemon never upgrades itself.
    #[serde(default)]
    pub deployment: DeploymentHealth,
    pub generated_at: DateTime<Utc>,
}

/// A declaration of how a derived answer was obtained.
///
/// `complete` is the field that matters: `false` means the window may not cover
/// everything the chain holds, so a reader needing certainty must traverse. It is
/// deliberately not inferred from `window` — a window that happens to exceed the chain
/// length is still a windowed read, and next week it will not.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadBasis {
    /// `"windowed-projection"` — bounded rows, pruned fields — or `"full-traversal"`.
    pub mode: String,
    /// Rows considered, when bounded.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window: Option<u64>,
    /// True only when the answer rests on the whole chain.
    pub complete: bool,
    /// What a relying party should know before accepting this as sufficient.
    pub note: String,
}

impl Default for ReadBasis {
    /// Fail-closed, exactly as `SovereignStrength` defaults to `Placeholder`: an
    /// unstated basis is the WEAKEST claim, never an implied complete one.
    fn default() -> Self {
        Self {
            mode: "unstated".into(),
            window: None,
            complete: false,
            note: "basis not declared; treat as compressed and escalate if certainty is required".into(),
        }
    }
}

/// Deployment identity as observed by the daemon.
///
/// `HESTIA_CURRENT_BUILD_FILE` points at a small supervisor-owned JSON manifest,
/// for example `{ "build_id": "app-v0.1.2-607-ge720d0a" }` — the exact
/// `git describe` provenance string the deployed binary reports in
/// `hestia --version` (see docs/DASHBOARD.md; a short hash never matches).
/// Missing or unreadable authority is
/// deliberately `unknown`, not green: a daemon cannot claim freshness from its
/// own build string alone.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct GateEngineHealth {
    /// `last-self-report-capable`, `partial`, or `unknown`.
    pub state: String,
    pub capability: String,
    pub capable_members: Vec<String>,
    pub unknown_members: Vec<String>,
    pub reported_without_capability: Vec<String>,
    pub note: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeploymentHealth {
    /// `current`, `stale`, or `unknown`.
    pub state: String,
    pub running_build: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub current_build: Option<String>,
    pub note: String,
    /// Whether this platform has a supported registered deployment supervisor trigger.
    #[serde(default)]
    pub update_capable: bool,
    /// `idle`, `requested`, `held`, `running`, `failed`, or `unavailable`. This is supervisor
    /// status for an operator-originated update, not an inference from the browser.
    #[serde(default)]
    pub update_state: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub update_request_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub update_note: Option<String>,
    /// The last gate-capability self-report accepted during this daemon run, distinct from
    /// the daemon build above. This is A1 historical runtime evidence with no freshness,
    /// session, identity, or build binding — not installed-byte attestation. #481 owns that
    /// stronger claim.
    pub gate_engine: GateEngineHealth,
}


fn deployment_update_status(
    authority_path: &Path,
    current: bool,
) -> (bool, String, Option<String>, Option<String>) {
    let supported = cfg!(target_os = "linux") || cfg!(target_os = "macos");
    if !supported {
        return (
            false,
            "unavailable".into(),
            None,
            Some(format!("dashboard update is unsupported on {}", std::env::consts::OS)),
        );
    }
    if current {
        return (true, "idle".into(), None, None);
    }
    let Some(parent) = authority_path.parent() else {
        return (false, "unavailable".into(), None, Some("deployment authority has no parent directory".into()));
    };
    let path = parent.join("deploy-status.tsv");
    let raw = match std::fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return (true, "idle".into(), None, None);
        }
        Err(error) => {
            return (true, "idle".into(), None, Some(format!("cannot read deployment update status: {error}")));
        }
    };
    let fields: Vec<&str> = raw.trim_end().split('\t').collect();
    if fields.len() != 4 {
        return (
            true,
            "failed".into(),
            None,
            Some("deployment update status is malformed".into()),
        );
    }
    let state = fields[0];
    let request_id = (!fields[1].is_empty()).then(|| fields[1].to_string());
    let supervisor_target = fields[2];
    let Some(updated) = chrono::DateTime::parse_from_rfc3339(fields[3]).ok() else {
        return (
            true,
            "failed".into(),
            request_id,
            Some("deployment update status has an invalid timestamp".into()),
        );
    };
    let age_secs = chrono::Utc::now()
        .signed_duration_since(updated.with_timezone(&chrono::Utc))
        .num_seconds();
    let target_note = if supervisor_target.is_empty() {
        String::new()
    } else {
        format!(" toward {supervisor_target}")
    };
    match state {
        "requested" if (0..=420 * 60).contains(&age_secs) => (
            true,
            "requested".into(),
            request_id,
            Some("deployment update requested; waiting for the supervisor".into()),
        ),
        "held" if (0..=420 * 60).contains(&age_secs) => (
            true,
            "held".into(),
            request_id,
            Some("deployment update is queued behind an active operator hold".into()),
        ),
        "running" if (0..=60 * 60).contains(&age_secs) => (
            true,
            "running".into(),
            request_id,
            Some(format!("deployment supervisor is updating this installation{target_note}")),
        ),
        "failed" if (0..=420 * 60).contains(&age_secs) => (
            true,
            "failed".into(),
            request_id,
            Some("last deployment update failed; the previous working deployment remains in force".into()),
        ),
        "succeeded" if (0..=420 * 60).contains(&age_secs) => (
            true,
            "failed".into(),
            request_id,
            Some("deployment supervisor reported success but the running build is still stale".into()),
        ),
        "requested" | "held" | "running" => (
            true,
            "failed".into(),
            request_id,
            Some("deployment update status expired without reaching a terminal result".into()),
        ),
        _ => (true, "idle".into(), None, None),
    }
}

fn deployment_health_from_path(path: Option<&Path>) -> DeploymentHealth {
    let running_build = env!("HESTIA_GIT_VERSION").to_string();
    let Some(path) = path else {
        return DeploymentHealth {
            state: "unknown".into(),
            running_build,
            current_build: None,
            note: "deployment authority is not configured".into(),
            update_capable: false,
            update_state: "unavailable".into(),
            update_request_id: None,
            update_note: Some("deployment authority is not configured".into()),
            gate_engine: GateEngineHealth::default(),
        };
    };
    let raw = match std::fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(error) => {
            return DeploymentHealth {
                state: "unknown".into(),
                running_build,
                current_build: None,
                note: format!("cannot read deployment authority: {error}"),
                update_capable: false,
                update_state: "unavailable".into(),
                update_request_id: None,
                update_note: Some(format!("cannot read deployment authority: {error}")),
                gate_engine: GateEngineHealth::default(),
            };
        }
    };
    let manifest: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(error) => {
            return DeploymentHealth {
                state: "unknown".into(),
                running_build,
                current_build: None,
                note: format!("deployment authority is invalid JSON: {error}"),
                update_capable: false,
                update_state: "unavailable".into(),
                update_request_id: None,
                update_note: Some(format!("deployment authority is invalid JSON: {error}")),
                gate_engine: GateEngineHealth::default(),
            };
        }
    };
    let current_build = manifest
        .get("build_id")
        .or_else(|| manifest.get("git_version"))
        .or_else(|| manifest.get("commit"))
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);
    let Some(current_build) = current_build else {
        return DeploymentHealth {
            state: "unknown".into(),
            running_build,
            current_build: None,
            note: "deployment authority has no build_id".into(),
            update_capable: false,
            update_state: "unavailable".into(),
            update_request_id: None,
            update_note: Some("deployment authority has no build_id".into()),
            gate_engine: GateEngineHealth::default(),
        };
    };
    let current = current_build == running_build;
    let (update_capable, update_state, update_request_id, update_note) =
        deployment_update_status(path, current);
    DeploymentHealth {
        state: if current { "current" } else { "stale" }.into(),
        note: if current {
            "running build matches deployment authority".into()
        } else if update_state == "held" {
            "deployment update is queued behind an active operator hold".into()
        } else if update_state == "running" || update_state == "requested" {
            "deployment update is in progress".into()
        } else if update_state == "failed" {
            "deployment is stale; the last update attempt did not make it current".into()
        } else {
            "running build does not match deployment authority".into()
        },
        running_build,
        current_build: Some(current_build),
        update_capable,
        update_state,
        update_request_id,
        update_note,
        gate_engine: GateEngineHealth::default(),
    }
}

fn deployment_health(state: &ServerState) -> DeploymentHealth {
    let mut health = deployment_health_from_path(
        std::env::var_os("HESTIA_CURRENT_BUILD_FILE")
            .as_deref()
            .map(Path::new),
    );
    const CAPABILITY: &str = "society-floor:v1";
    let mut capable_members = Vec::new();
    let mut unknown_members = Vec::new();
    let mut reported_without_capability = Vec::new();
    let mut members = std::collections::BTreeSet::new();
    members.extend(
        state
            .member_registry
            .iter_sorted()
            .into_iter()
            .map(|(member, _)| member.clone()),
    );
    members.extend(state.gate_capabilities.keys().cloned());
    for member in members {
        match state.gate_capabilities.get(&member) {
            Some(caps) if caps.contains(CAPABILITY) => capable_members.push(member),
            Some(_) => reported_without_capability.push(member),
            None => unknown_members.push(member),
        }
    }
    let report_count = capable_members.len() + reported_without_capability.len();
    let state_name = if !capable_members.is_empty()
        && unknown_members.is_empty()
        && reported_without_capability.is_empty()
    {
        "last-self-report-capable"
    } else if report_count > 0 {
        "partial"
    } else {
        "unknown"
    };
    health.gate_engine = GateEngineHealth {
        state: state_name.into(),
        capability: CAPABILITY.into(),
        capable_members,
        unknown_members,
        reported_without_capability,
        note: "last accepted A1 self-report during this daemon run; caller identity and bytes \
               are not authenticated, omission preserves an earlier report, and there is no \
               freshness/session/build binding — this does not prove what is currently loaded \
               or installed; see #481"
            .into(),
    };
    health
}

/// Identity + macro state of this Hestia society.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SocietyView {
    /// The legacy sovereign anchor string (witness-chain authorship keys on this).
    pub sovereign_lct: String,
    /// The sovereign's canonical, key-derived LCT id — its real presence as a
    /// vault-persisted entity (distinct from the `sovereign_lct` anchor string).
    #[serde(default)]
    pub sovereign_lct_id: String,
    pub chain_length: u64,
    pub active_sessions: usize,
    pub vault_entries: usize,
    pub known_plugins: usize,
    /// Phase-1 mirror: published constellation roles held as `Role` LCT entities.
    #[serde(default)]
    pub role_entities: usize,
    /// Custodial member LCTs minted for real (non-synthetic) members.
    #[serde(default)]
    pub member_entities: usize,
    /// The society's entity type — now `society` (sovereign-as-role restructure).
    #[serde(default)]
    pub entity_type: String,
    /// `role:sovereign` LCT id — the role the operator occupies (SAL §2.1).
    #[serde(default)]
    pub sovereign_role_id: String,
    /// The society's provable ratchet level (0 = genesis L0; monotone).
    #[serde(default)]
    pub ratchet_level: u8,
}

/// Aggregate counts across the witness chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivityStats {
    pub total_actions: u64,
    pub successful_actions: u64,
    pub failed_actions: u64,
    /// Policy denials (`policy_decision`/`deny`). These never become an
    /// `outcome` — the gate blocks the tool before it runs — so they are
    /// **not** in `total_actions` and do **not** affect `success_rate`. A deny
    /// is the trust layer succeeding at its job, not a tool failing; this is
    /// surfaced separately so a wall of denies can't read as failures.
    #[serde(default)]
    pub denied_actions: u64,
    /// 0.0–1.0 — execution reliability of *executed* tools only.
    pub success_rate: f64,
    /// Tool name → count, descending.
    pub by_tool: Vec<(String, u64)>,
    /// Actions in the last 60 minutes (approximate; counted by timestamp).
    pub actions_last_hour: u64,
}

/// One plugin's trust snapshot.
///
/// Canonical-web4 display contract: a dimension is shown ONLY if it has been
/// measured (canonical per-dimension `observation_counts` > 0). An unmeasured
/// dimension serializes as `null`, never as the 0.5 prior — 0.5-with-zero-
/// observations is "honest unmeasured", and rendering it as a score fabricates
/// confidence. Averages are shown only when at least one dimension of that
/// tensor has been measured. No hestia-local trust terms; everything here is
/// read straight off the canonical `web4_core` T3/V3 tensors as implemented.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrustView {
    pub plugin_id: String,
    pub entity_id: String,
    pub level: String,
    pub t3_talent: Option<f64>,
    pub t3_training: Option<f64>,
    pub t3_temperament: Option<f64>,
    pub t3_average: Option<f64>,
    pub v3_valuation: Option<f64>,
    pub v3_veracity: Option<f64>,
    pub v3_validity: Option<f64>,
    pub v3_average: Option<f64>,
    /// Canonical per-dimension observation counts [talent, training, temperament].
    pub t3_observation_counts: [u64; 3],
    /// Canonical per-dimension observation counts [valuation, veracity, validity].
    pub v3_observation_counts: [u64; 3],
    pub action_count: u64,
    pub success_count: u64,
    pub success_rate: f64,
    pub days_since_last: f64,
    /// Legacy level from the self-report scalar — kept for audit, NEVER for
    /// display (the chip that called a well-adjudicated member "low" off this
    /// field was the footgun — dp 2026-07-24).
    #[serde(default)]
    pub legacy_level: String,
    /// Derived temperament (v3-derived-v1: governance-response conduct).
    #[serde(default)]
    /// Why `level` reads the way it does, so the badge and the row text cannot disagree.
    pub derived_level_basis: String,
    pub derived_baseline_acts: u64,
    pub derived_governed_acts: u64,
    pub derived_temperament: Option<f64>,
    #[serde(default)]
    pub derived_temperament_n: u64,
    /// The ADJUDICATED grain (Stage 1, T3-from-V3): V3 folded ONLY from
    /// witnessed not-the-actor adjudications — the earned-trust record, next
    /// to (never blended with) the self-reported outcome record. Null when
    /// the dimension has zero adjudications (honest-unmeasured).
    #[serde(default)]
    pub adjudicated_validity: Option<f64>,
    #[serde(default)]
    pub adjudicated_veracity: Option<f64>,
    #[serde(default)]
    pub adjudicated_valuation: Option<f64>,
    /// Per-dimension adjudication observation counts [valuation, veracity, validity].
    #[serde(default)]
    pub adjudicated_counts: [u64; 3],
    /// How the numbers above were produced. `"legacy-lockstep-v1"` = the pre-arc
    /// update_from_outcome path: ONE self-reported success scalar smeared across all
    /// three T3 dims at fixed 1.0/0.5/0.3 coefficients, magnitudes caller-chosen. The
    /// UI must NOT render that as three independent facts (Stage 0 of the T3-from-V3
    /// arc, plans/t3-from-v3-synthesis-2026-07-24.md). `"v3-derived-v1"` (Stage 3)
    /// re-enables per-dimension display for dimensions actually derived from
    /// adjudicated evidence.
    #[serde(default)]
    pub derivation: String,
    /// Set when this identity is a witnessed ALIAS of another: its evidence folds into
    /// that member and is counted THERE. Without this the dashboard shows the same
    /// observations twice — once natively, once folded — and a reader cannot tell that
    /// the two rows are one agent (dp, 2026-07-26).
    #[serde(default)]
    pub aliased_to: Option<String>,
}

/// One recent chain entry, flattened for UI consumption.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecentEntry {
    pub chain_position: u64,
    pub event_type: String,
    pub timestamp: DateTime<Utc>,
    pub hash: String,
    pub prev_hash: String,
    pub tool_name: Option<String>,
    pub target: Option<String>,
    pub success: Option<bool>,
    pub magnitude: Option<f64>,
    pub plugin_id: Option<String>,
    /// WHICH session/capacity acted — so an operator can tell an interactive session from a
    /// mesh-worker or autonomous-timer cron at a glance (the store already keys trust on this grain;
    /// this surfaces it per-act in the feed/logs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_lct: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub host_session_id: Option<String>,
    pub error: Option<String>,
    // Populated only for policy_decision entries.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decision: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enforced: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rule_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// What the member tried to do, bounded and secret-scrubbed. `None` on allows and on
    /// denies from gates that do not report it yet.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attempted: Option<String>,
}

/// Flatten a `ChainEntry` into the UI-facing `RecentEntry` shape.
pub fn flatten_entry(e: crate::storage::ChainEntry) -> RecentEntry {
    let d = &e.event_data;
    RecentEntry {
        chain_position: e.chain_position,
        event_type: e.event_type.clone(),
        timestamp: e.timestamp,
        hash: e.hash.clone(),
        prev_hash: e.prev_hash.clone(),
        tool_name: d
            .get("tool_name")
            .and_then(|v| v.as_str())
            .map(String::from),
        target: d.get("target").and_then(|v| v.as_str()).map(String::from),
        success: d.get("success").and_then(|v| v.as_bool()),
        magnitude: d.get("magnitude").and_then(|v| v.as_f64()),
        plugin_id: d
            .get("plugin_id")
            .and_then(|v| v.as_str())
            .map(String::from),
        role_lct: d.get("role_lct").and_then(|v| v.as_str()).map(String::from),
        host_session_id: d
            .get("host_session_id")
            .and_then(|v| v.as_str())
            .map(String::from),
        error: d.get("error").and_then(|v| v.as_str()).map(String::from),
        decision: d.get("decision").and_then(|v| v.as_str()).map(String::from),
        enforced: d.get("enforced").and_then(|v| v.as_bool()),
        rule_name: d
            .get("rule_name")
            .and_then(|v| v.as_str())
            .map(String::from),
        reason: d.get("reason").and_then(|v| v.as_str()).map(String::from),
        // The bounded, scrubbed command the gate refused. Present only on denies, and
        // only for gates that send it — absent means "this gate does not report attempts
        // yet", which the UI must not render as "nothing was attempted".
        attempted: d
            .get("attempted")
            .and_then(|v| v.as_str())
            .map(String::from),
    }
}

/// Exactly the `event_data` fields any dashboard surface reads — and nothing else.
///
/// This is the whole memory fix in one type. `ChainEntry.event_data` is a parsed
/// `serde_json::Value`, so reading a 10,000-row window built 10,000 documents to harvest
/// fourteen scalars from each. Serde skips unknown keys **without allocating them**, so
/// deserialising into this struct costs the fields named here and nothing more.
///
/// Measured 2026-08-06: the daemon reached 1.35 GB in twenty-one minutes of ordinary use,
/// `Anonymous` 1364 MB of `Rss` 1382 MB, flat at idle and stepping on every heavy read —
/// retention of trees nobody wanted. See `SqliteChainStore::scan_recent`.
#[derive(Debug, Default, serde::Deserialize)]
struct EventFields {
    tool_name: Option<String>,
    target: Option<String>,
    success: Option<bool>,
    magnitude: Option<f64>,
    plugin_id: Option<String>,
    role_lct: Option<String>,
    host_session_id: Option<String>,
    error: Option<String>,
    decision: Option<String>,
    enforced: Option<bool>,
    rule_name: Option<String>,
    reason: Option<String>,
    attempted: Option<String>,
}

/// `flatten_entry`'s sibling, fed by a streaming row instead of a parsed entry.
///
/// Same output, same field semantics; the difference is upstream — the caller never
/// materialised a document to get here. `timestamp` is parsed from the row's RFC3339 and
/// falls back to the epoch on a malformed value rather than dropping the row: a
/// timestamp we cannot read is a legibility problem, not a reason to hide an act.
pub fn flatten_row(r: crate::storage::chain::ChainRowRef<'_>) -> RecentEntry {
    let f: EventFields = r.project().unwrap_or_default();
    RecentEntry {
        chain_position: r.chain_position,
        event_type: r.event_type.to_string(),
        timestamp: DateTime::parse_from_rfc3339(r.timestamp)
            .map(|t| t.with_timezone(&Utc))
            .unwrap_or_else(|_| DateTime::<Utc>::UNIX_EPOCH),
        hash: r.hash.to_string(),
        prev_hash: r.prev_hash.to_string(),
        tool_name: f.tool_name,
        target: f.target,
        success: f.success,
        magnitude: f.magnitude,
        plugin_id: f.plugin_id,
        role_lct: f.role_lct,
        host_session_id: f.host_session_id,
        error: f.error,
        decision: f.decision,
        enforced: f.enforced,
        rule_name: f.rule_name,
        reason: f.reason,
        attempted: f.attempted,
    }
}

impl ServerState {
    /// Build the dashboard snapshot. Reads up to `recent_limit` chain
    /// entries for the live feed; aggregates over the full chain for stats.
    ///
    /// Compat wrapper: trailing-hour window, the pre-range default.
    pub fn dashboard_snapshot(&self, recent_limit: u64) -> DashboardSnapshot {
        self.dashboard_snapshot_window(
            recent_limit,
            Some(Utc::now() - chrono::Duration::hours(1)),
            "hour",
        )
    }

    /// Calendar-windowed snapshot. `window_cutoff = Some(t)` bounds the live
    /// feed AND the windowed action stat by calendar time (capped at
    /// `recent_cap` entries for transport safety); `None` = no calendar bound
    /// ("all", count-capped only). `window_label` is echoed back so the UI
    /// labels the stat truthfully.
    ///
    /// Why calendar, not count: a fixed "latest 50" global window silently
    /// evicts a quiet plugin's entries whenever busier plugins churn — its
    /// filtered log then reads as "emptied" while its chain is intact (the
    /// filtered-window illusion, live-confirmed with kimi 2026-07-23).
    pub fn dashboard_snapshot_window(
        &self,
        recent_cap: u64,
        window_cutoff: Option<DateTime<Utc>>,
        window_label: &str,
    ) -> DashboardSnapshot {
        let projection =
            DashboardChainProjection::read(&self.chain_store, recent_cap, window_cutoff);
        self.dashboard_snapshot_from_projection(projection, window_cutoff, window_label)
    }

    /// Assemble the display model from an already-read chain projection.
    ///
    /// HTTP uses this split to perform the SQLCipher work outside the
    /// authoritative state lock. The compatibility wrapper above keeps direct
    /// callers and tests on the same arithmetic.
    pub(crate) fn dashboard_snapshot_from_projection(
        &self,
        projection: DashboardChainProjection,
        window_cutoff: Option<DateTime<Utc>>,
        window_label: &str,
    ) -> DashboardSnapshot {
        let DashboardChainProjection {
            deriv_window,
            stats_window,
            stats_read_error,
            recent,
            recent_read_error,
        } = projection;

        let mut total = 0u64;
        let mut succ = 0u64;
        let mut fail = 0u64;
        let mut denied = 0u64;
        let mut policy_decisions: Vec<RecentEntry> = Vec::new();
        let mut deny_kept = 0usize;
        let mut warn_kept = 0usize;
        let mut by_tool: BTreeMap<String, u64> = BTreeMap::new();
        // Windowed action stat follows the SELECTED calendar window (None =
        // count the whole stats sample, i.e. "all"). Liveness/selection of
        // orchestrator chips is unaffected — "is it active now" is a
        // different question than "what period am I looking at".
        let stat_cutoff = window_cutoff;
        let trailing_hour = Utc::now() - chrono::Duration::hours(1);
        let mut last_hour = 0u64;
        // Per-plugin slices of the same window, keyed by the human plugin_id:
        // (total, succ, fail, denied, last_hour, by_tool). Backs the chip filter.
        #[allow(clippy::type_complexity)]
        let mut per_plugin: BTreeMap<
            String,
            (u64, u64, u64, u64, u64, BTreeMap<String, u64>),
        > = BTreeMap::new();
        // Per-plugin "last seen" timestamps, used to decide which
        // orchestrators are "active" (= seen in the last hour).
        // Active trust entities in the window, keyed by the trust-store composite
        // `(instance, role)` key with the human plugin_id + role retained for
        // display + the synthetic filter. The key is recomputed via
        // `trust_entity_key` (not read from the event's `instance_lct`), so it
        // matches storage exactly even for old events that predate that field.
        let mut active_entities: std::collections::HashMap<
            String,
            (chrono::DateTime<Utc>, String, String),
        > = std::collections::HashMap::new();

        for e in &stats_window {
            // Track per-(instance, role) last-seen across any event that carries a
            // plugin_id. Outcomes are the main signal now that session_started is
            // no longer written; historical chains may still contain older entries.
            if let Some(pid) = e.plugin_id.as_deref() {
                let role = e.role_lct.as_deref()
                    .unwrap_or(crate::reputation::DEFAULT_CONSTELLATION_ROLE);
                let key = self.trust_entity_key(pid, role);
                let entry = active_entities.entry(key).or_insert((
                    e.timestamp,
                    pid.to_string(),
                    role.to_string(),
                ));
                if e.timestamp > entry.0 {
                    entry.0 = e.timestamp;
                }
            }
            // A policy denial blocks the tool before it runs, so it never
            // produces an `outcome`. Count it separately (not as a failure).
            if e.event_type == "policy_decision"
                && e.decision.as_deref() == Some("deny")
            {
                denied += 1;
                if let Some(pid) = e.plugin_id.as_deref() {
                    per_plugin.entry(pid.to_string()).or_default().3 += 1;
                }
            }
            // Collect policy decisions for the warn/deny feed filters across the
            // wider stats window (denies can be older than `recent_limit`). Cap
            // warn and deny INDEPENDENTLY so frequent warns can't crowd out the
            // rarer denies — a single shared cap made the deny list look empty.
            if e.event_type == "policy_decision" {
                let dec = e.decision.as_deref();
                let keep = match dec {
                    Some("deny") if deny_kept < 300 => {
                        deny_kept += 1;
                        true
                    }
                    Some("warn") if warn_kept < 300 => {
                        warn_kept += 1;
                        true
                    }
                    _ => false,
                };
                if keep {
                    policy_decisions.push(e.clone());
                }
            }
            if e.event_type != "outcome" {
                continue;
            }
            // `actions_last_hour` means what it says: a genuine trailing hour,
            // independent of the selected range. It previously tracked the SELECTED
            // window, so at range=week the field labelled "last hour" reported a week.
            if e.timestamp > trailing_hour {
                last_hour += 1;
            }
            // Everything below is the WINDOWED stat and must honour the selection.
            // Previously only `last_hour` consulted the cutoff, so total/succ/fail/
            // by_tool (and every per-plugin slice) silently reported the whole 10k
            // sample at every range — the selector appeared to work and did not.
            if !stat_cutoff.map_or(true, |c| e.timestamp > c) {
                continue;
            }
            total += 1;
            let success = e.success
                .unwrap_or(false);
            if success {
                succ += 1;
            } else {
                fail += 1;
            }
            let tname = e.tool_name.as_deref();
            if let Some(tname) = tname {
                *by_tool.entry(tname.to_string()).or_insert(0) += 1;
            }
            // Same slice, per plugin.
            if let Some(pid) = e.plugin_id.as_deref() {
                let p = per_plugin.entry(pid.to_string()).or_default();
                p.0 += 1;
                if success {
                    p.1 += 1
                } else {
                    p.2 += 1
                }
                if e.timestamp > trailing_hour {
                    p.4 += 1;
                }
                if let Some(tname) = tname {
                    *p.5.entry(tname.to_string()).or_insert(0) += 1;
                }
            }
        }
        let stats_by_plugin: BTreeMap<String, ActivityStats> = per_plugin
            .into_iter()
            .map(|(pid, (t, s, f, d, lh, bt))| {
                let mut btv: Vec<(String, u64)> = bt.into_iter().collect();
                btv.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
                (
                    pid,
                    ActivityStats {
                        total_actions: t,
                        successful_actions: s,
                        failed_actions: f,
                        denied_actions: d,
                        success_rate: if t == 0 { 0.0 } else { s as f64 / t as f64 },
                        by_tool: btv,
                        actions_last_hour: lh,
                    },
                )
            })
            .collect();
        let mut by_tool_vec: Vec<(String, u64)> = by_tool.into_iter().collect();
        by_tool_vec.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        let success_rate = if total == 0 {
            0.0
        } else {
            succ as f64 / total as f64
        };

        // Harnesses that ACTED in the recent window. This — not "has a grain" — is what
        // `engaged` (the stats/"active" signal, built below) means. Captured BEFORE folding
        // in the idle known harnesses just below, so surfacing a two-day-idle member's trust
        // row does not falsely mark it active.
        let engaged_pids: std::collections::HashSet<String> =
            active_entities.values().map(|(_, pid, _)| pid.clone()).collect();

        // IDLE-BUT-KNOWN HARNESSES (dp, 2026-08-11): a registry harness that has not acted
        // within the recent-window sample still deserves its trust row — its accumulated
        // trust persists in the store, and staleness is conveyed by `days_since_last`, not by
        // the row vanishing. `stats_window` is the last N rows of ALL event types, dominated
        // by frequent outcomes, so it only reaches back an hour or two; a member idle for days
        // (kimi-code) falls out of it entirely though its grain is intact. Seed the active set
        // from the trust store for every registry harness so it shows its most recent standing.
        // Insert-if-absent: a harness active in the window keeps its window entry untouched.
        // The derived LEVEL comes from `deriv_window` — `derivation::scan_window`, whose
        // governance budget is deep precisely so a member idle for days still shows the
        // standing it earned. When this comment last claimed the window "reaches back much
        // further", the dashboard was in fact passing STATS_WINDOW (~17 hours of chain) and
        // kimi-code/codex rendered `unmeasured` beside 24k and 8k actions.
        if let Ok(all_keys) = self.trust_store.list() {
            // Reverse map: a grain key's instance prefix -> the human plugin_id, for the
            // harnesses we know. Both the mapped `lct:web4:member:…` form and the legacy
            // `plugin:<id>` form, so a grain written before the member was mapped still resolves.
            let mut instance_pid: std::collections::HashMap<String, &str> =
                std::collections::HashMap::new();
            for orch in crate::orchestrators::REGISTRY {
                if self.is_synthetic(orch.id) {
                    continue;
                }
                if let Some(lct) = self.member_lct(orch.id) {
                    instance_pid.insert(lct, orch.id);
                }
                instance_pid.insert(format!("plugin:{}", orch.id), orch.id);
            }
            for key in all_keys {
                // A MAIN grain is "{instance}#{role}"; its `#adjudicated` / `#judgment`
                // sub-grains carry a further '#' and are folded by the main grain, not listed.
                let Some((instance, role)) = key.split_once('#') else { continue };
                if role.contains('#') {
                    continue;
                }
                if let Some(&pid) = instance_pid.get(instance) {
                    active_entities
                        .entry(key.clone())
                        .or_insert((Utc::now(), pid.to_string(), role.to_string()));
                }
            }
        }

        // Build the trust list per (instance, role) entity seen in the window, minus synthetic
        // test harnesses. NOTE: no last-hour filter — an idle-but-known orchestrator stays viewable
        // (dp: always be able to select any visible orchestrator + view its history regardless of
        // current activity). Staleness is conveyed by `days_since_last`, not by hiding the row.
        // Sorted (plugin, role) for a stable snapshot.
        let mut active_sorted: Vec<(&String, &(chrono::DateTime<Utc>, String, String))> =
            active_entities
                .iter()
                .filter(|(_key, (_ts, pid, _role))| !self.is_synthetic(pid))
                .collect();
        active_sorted.sort_by(|a, b| (&a.1.1, &a.1.2).cmp(&(&b.1.1, &b.1.2)));
        let trust: Vec<TrustView> = active_sorted
            .into_iter()
            .map(|(key, (_ts, pid, _role_ts))| {
                let _role = _role_ts.as_str();
                let t = self
                    .trust_store
                    .get(key)
                    .unwrap_or_else(|_| EntityTrust::new(key.clone()));
                // Canonical unmeasured-handling: read the tensors' own per-dim
                // observation counts; a dim with 0 observations is null (not the
                // 0.5 prior), and an average is null until something measured.
                let t3c = *t.t3.observation_counts();
                let v3c = *t.v3.observation_counts();
                let dim = |v: f64, c: u64| if c > 0 { Some(v) } else { None };
                // The ADJUDICATED grain lives at `<grain>#adjudicated` — earned
                // trust, folded only from witnessed adjudications (Stage 1).
                let adj = self
                    .trust_store
                    .get(&format!("{key}#adjudicated"))
                    .unwrap_or_else(|_| EntityTrust::new(format!("{key}#adjudicated")));
                let adj_counts = *adj.v3.observation_counts();
                let adj_dims = (
                    dim(adj.validity(), adj_counts[2]),
                    dim(adj.veracity(), adj_counts[1]),
                    dim(adj.valuation(), adj_counts[0]),
                );
                // v3-derived-v1: the DISPLAYED level comes from derived
                // evidence (adjudications + governance conduct) — never from
                // the self-report scalar. Unmeasured renders as unmeasured.
                // Lifetime totals come from the PERSISTED grain, never the window: the
                // whole point is that routine governed work does not evaporate when a
                // member goes idle for three days.
                let derived = crate::derivation::derive_with_volume(
                    pid,
                    _role,
                    &deriv_window,
                    Some(crate::derivation::WitnessedVolume {
                        total_acts: t.action_count,
                        success_acts: t.success_count,
                    }),
                );
                TrustView {
                    plugin_id: pid.clone(),
                    entity_id: t.entity_id.clone(),
                    level: derived.level.clone(),
                    legacy_level: t.trust_level().as_str().to_string(),
                    derived_level_basis: derived.level_basis.clone(),
                    derived_baseline_acts: derived.baseline_acts,
                    derived_governed_acts: derived.governed_acts,
                    derived_temperament: derived.temperament.score,
                    derived_temperament_n: derived.temperament.observations,
                    t3_talent: dim(t.talent(), t3c[0]),
                    t3_training: dim(t.training(), t3c[1]),
                    t3_temperament: dim(t.temperament(), t3c[2]),
                    t3_average: dim(t.t3_average(), t3c.iter().sum()),
                    v3_valuation: dim(t.valuation(), v3c[0]),
                    v3_veracity: dim(t.veracity(), v3c[1]),
                    v3_validity: dim(t.validity(), v3c[2]),
                    v3_average: dim(t.v3_average(), v3c.iter().sum()),
                    t3_observation_counts: t3c,
                    v3_observation_counts: v3c,
                    action_count: t.action_count,
                    success_count: t.success_count,
                    success_rate: t.success_rate(),
                    days_since_last: t.days_since_last_action(),
                    adjudicated_validity: adj_dims.0,
                    adjudicated_veracity: adj_dims.1,
                    adjudicated_valuation: adj_dims.2,
                    adjudicated_counts: adj_counts,
                    // Everything in this view flows from update_from_outcome's
                    // self-reported scalar until Stage 3 of the T3-from-V3 arc.
                    derivation: "legacy-lockstep-v1".to_string(),
                    aliased_to: crate::derivation::alias_target(pid, &deriv_window),
                }
            })
            .collect();

        let delegations = crate::delegation::DelegationStore::load(&self.vault)
            .ok()
            .map(|s| {
                s.delegations
                    .iter()
                    .map(|d| serde_json::to_value(d).unwrap_or_default())
                    .collect()
            })
            .unwrap_or_default();

        let profile = crate::profile::ProfileStore::load(&self.vault)
            .ok()
            .and_then(|s| {
                serde_json::to_value(&s.present(&crate::profile::Visibility::Private)).ok()
            });

        let constellation = crate::constellation::ConstellationStore::load(&self.vault)
            .ok()
            .and_then(|s| serde_json::to_value(&s.proof()).ok());

        let hub_connections = crate::hub::HubStore::load(&self.vault)
            .ok()
            .map(|s| {
                s.connections
                    .iter()
                    .map(|c| serde_json::to_value(c).unwrap_or_default())
                    .collect()
            })
            .unwrap_or_default();

        let policy = {
            let ps = self.vault.policy();
            PolicyView {
                preset: ps.active_preset.clone(),
                enforce: ps.resolve().map(|c| c.enforce).unwrap_or(true),
            }
        };

        // Orchestrators: registry entries that are running and/or engaged, plus
        // any engaged plugin not in the registry (custom orchestrators).
        let running = crate::orchestrators::detect_running();
        // `engaged` = acted in the last hour (drives the stats filter). It is NOT
        // the same as "connected": an agent routinely goes >1h between witnessed
        // tool calls (long reads, thinking, waiting on the human), and treating
        // that idle gap as a disconnect is the bug this snapshot used to have.
        // `connected` = the process is alive AND its hooks are wired, OR it acted
        // recently. That way a live, wired-but-idle orchestrator reads connected,
        // while a running-but-unwired one still gets offered a connect affordance.
        let engaged: std::collections::HashSet<&str> =
            trust.iter().map(|t| t.plugin_id.as_str()).collect();
        let mut orchestrators: Vec<serde_json::Value> = crate::orchestrators::REGISTRY
            .iter()
            .filter(|o| running.contains(o.id) || engaged.contains(o.id))
            .map(|o| {
                let running_now = running.contains(o.id);
                let active = engaged.contains(o.id);
                let installed = crate::orchestrators::is_installed(o.id);
                serde_json::json!({
                    "id": o.id,
                    "name": o.name,
                    "running": running_now,
                    "engaged": active,
                    "installed": installed,
                    "connected": active || (running_now && installed),
                    "plugin_available": o.plugin_available,
                })
            })
            .collect();
        // Identities known only from the chain (no registry entry) still deserve a chip —
        // an orchestrator we have never heard of is exactly the thing worth surfacing.
        // But three things were wrong with how they were surfaced:
        //
        // 1. ALIASES GOT THEIR OWN CHIP. An `identity_alias` says two names are one
        //    entity, and the trust row already honours it ("evidence folds into codex —
        //    counted there, not here"). The chip loop never asked, so codex-cli kept
        //    appearing beside codex as though a fourth agent were running. The alias is
        //    the answer to "are these the same?"; a surface that ignores it re-asks the
        //    question the operator already settled.
        // 2. LIVENESS WAS FABRICATED. running/engaged/installed/connected were the
        //    literal `true`, not observations — so an identity last seen days ago
        //    presented as running right now, and no amount of it being dead could change
        //    the display. Registry chips derive all four; these now derive what they can
        //    and decline to claim the rest.
        // 3. ONE CHIP PER GRAIN, NOT PER IDENTITY. Trust rows are (instance, role), so a
        //    two-role custom plugin would have produced two identical chips. codex-cli
        //    has a single grain, which is the only reason this had not shown up yet.
        let mut custom_seen: std::collections::HashSet<&str> = std::collections::HashSet::new();
        for t in &trust {
            if t.aliased_to.is_some() {
                continue; // folded into another identity; it is counted and shown there
            }
            if crate::orchestrators::lookup(&t.plugin_id).is_some() {
                continue; // already emitted from the registry, with real liveness
            }
            if !custom_seen.insert(t.plugin_id.as_str()) {
                continue; // one chip per identity, however many role grains it has
            }
            let running_now = running.contains(t.plugin_id.as_str());
            orchestrators.push(serde_json::json!({
                "id": t.plugin_id,
                "name": t.plugin_id,
                "running": running_now,
                // Presence in `trust` is what "engaged" means for registry entries too
                // (see the set built above), so this one is a genuine observation.
                "engaged": true,
                // Unknown to the registry, so there is no install to probe. Only a live
                // process is evidence of installation; absent that we do not claim it.
                "installed": running_now,
                // Same formula the registry branch uses, rather than a constant.
                "connected": true,
                "plugin_available": false,
            }));
        }

        DashboardSnapshot {
            orchestrators,
            policy,
            society: SocietyView {
                sovereign_lct: self.sovereign_lct.clone(),
                sovereign_lct_id: self.sovereign.lct_id(),
                chain_length: self.chain_len(),
                active_sessions: self.sessions.len(),
                vault_entries: self.vault.list().len(),
                // Total known trust entities (all (instance, role) grains ever
                // seen), independent of the last-hour active view above.
                known_plugins: self.trust_store.list().map(|v| v.len()).unwrap_or(0),
                role_entities: self.role_registry.len(),
                member_entities: self.member_registry.len(),
                entity_type: serde_json::to_string(&self.sovereign.lct.entity_type)
                    .unwrap_or_default()
                    .trim_matches('"')
                    .to_string(),
                sovereign_role_id: self.sovereign.sovereign_role_id(),
                ratchet_level: self.sovereign.ratchet_level(),
            },
            stats: ActivityStats {
                total_actions: total,
                successful_actions: succ,
                failed_actions: fail,
                denied_actions: denied,
                success_rate,
                by_tool: by_tool_vec,
                actions_last_hour: last_hour,
            },
            stats_by_plugin,
            trust,
            recent,
            policy_decisions,
            delegations,
            hub_connections,
            profile,
            constellation,
            window: window_label.to_string(),
            pending_escalations: {
                // `pending()` already drops expired entries, so an escalation
                // disappears from the operator's view at the same instant it
                // stops being decidable. A queue that still offers a button for
                // something the daemon would refuse teaches the operator that
                // the button lies.
                let now = crate::server::gate_escalation::now_secs();
                self.gate_escalations
                    .pending(now)
                    .into_iter()
                    .map(|e| {
                        serde_json::json!({
                            "id": e.id,
                            // Caller-asserted (HST-005). Labelled `claimed_by`
                            // rather than `member` so the UI cannot present a
                            // claim as an identity — the operator is deciding
                            // partly ON this string, and it is not authenticated.
                            "claimed_by": e.plugin_id,
                            "role": e.role,
                            "tool_name": e.tool_name,
                            "marker": e.marker,
                            // The BASIS for the decision. Without these the panel asks an
                            // operator to approve a governance write knowing only a tool
                            // name and a path fragment (dp, 2026-08-02).
                            "stated_reason": e.stated_reason,
                            "stated_detail": e.stated_detail,
                            "opened_at": e.opened_at,
                            "expires_at": e.expires_at,
                            "secs_remaining": e.expires_at.saturating_sub(now),
                            // The criterion in force when this was opened, so the
                            // operator reads the bar the escalation was filed
                            // under rather than today's.
                            "bar": e.bar,
                            "factors": e.factors,
                            // WILL THE OPERATOR'S APPROVAL ACTUALLY PERMIT THE WRITE?
                            //
                            // dp, 2026-08-04: *"do they actually unblock anything when i
                            // approve?"* — asked after approving `236a43ae3e687a6a`, which was
                            // recorded `approved` and still refused the write, because its bar
                            // is `sovereign_plus_peer` and no peer ever corroborated. The panel
                            // showed the bar's NAME and never said what it MEANT for the person
                            // about to click. Those two cases render identically today:
                            //
                            //   single_approver      -> your approval is sufficient
                            //   sovereign_plus_peer  -> your approval is NECESSARY, NOT SUFFICIENT
                            //
                            // Approving the second and watching nothing happen is the strongest
                            // possible teacher that the button is decorative. It is not — the
                            // mechanism works, four writes landed on approvals last night — but
                            // an operator cannot tell a working control from a broken one when
                            // the surface withholds the discriminator.
                            "operator_alone_suffices": match e.bar {
                                crate::server::gate_escalation::Bar::SingleApprover => true,
                                crate::server::gate_escalation::Bar::SovereignPlusPeer => e
                                    .factors
                                    .iter()
                                    .any(|f| {
                                        f.channel
                                            == crate::server::gate_escalation::Channel::PeerMember
                                    }),
                            },
                            // Stated positively so the UI never has to infer the remedy from a
                            // false boolean: what is still missing, in the operator's terms.
                            "still_needs": match e.bar {
                                crate::server::gate_escalation::Bar::SovereignPlusPeer
                                    if !e.factors.iter().any(|f| {
                                        f.channel
                                            == crate::server::gate_escalation::Channel::PeerMember
                                    }) =>
                                {
                                    Some("an independent NOT-SAME peer factor \
                                          (hestia_gate_escalation_corroborate)")
                                }
                                _ => None,
                            },
                        })
                    })
                    .collect()
            },
            pending_scope_requests: {
                let now = crate::server::gate_escalation::now_secs();
                let mut v: Vec<serde_json::Value> = self
                    .scope_requests
                    .values()
                    .filter(|r| r.status(now) == "pending")
                    .map(|r| {
                        serde_json::json!({
                            "request_id": r.id,
                            // Caller-asserted (HST-005), labelled the same way the escalation
                            // panel labels it: the operator decides partly ON this string and
                            // it is not authenticated.
                            "claimed_by": r.plugin_id,
                            "role": r.role,
                            "path": r.path,
                            // THE BASIS. A scope request without its stated why is the
                            // "no reason" defect arriving on a second surface, and this one
                            // has no excuse — `reason` is REQUIRED at filing.
                            "reason": r.reason,
                            "requested_at": r.requested_at,
                            "expires_at": r.expires_at,
                            "secs_remaining": r.expires_at.saturating_sub(now),
                        })
                    })
                    .collect();
                // Oldest first: the one closest to lapsing is the one that needs a human
                // soonest, and an unanswered request expires into a REFUSAL.
                v.sort_by_key(|x| x["requested_at"].as_u64().unwrap_or(0));
                v
            },
            // BOTH kinds of scope grant, in one list, each row carrying its own lifetime.
            // Live grants are rows in `scope_requests` that were granted and have not lapsed
            // (`live_scope_grants`); standing grants are rows in the vault-backed store. They
            // are merged here rather than served as two lists because the question an operator
            // actually has is "what can this member reach, and which half of it survives a
            // restart" — and that question is answered wrong by two lists read in sequence.
            scope_grants: {
                let now = crate::server::gate_escalation::now_secs();
                let mut v: Vec<serde_json::Value> = self
                    .scope_requests
                    .values()
                    .filter(|r| r.granted == Some(true) && now < r.expires_at)
                    .map(|r| {
                        serde_json::json!({
                            "lifetime": "live",
                            "plugin_id": r.plugin_id,
                            "path": r.path,
                            "reason": r.decision_reason,
                            "requested_because": r.reason,
                            "granted_by": r.decided_by,
                            "request_id": r.id,
                            "origin": "member_request",
                            "expires_at": r.expires_at,
                            "secs_remaining": r.expires_at.saturating_sub(now),
                            "durability": "memory-only — the next daemon restart revokes this",
                        })
                    })
                    .collect();
                v.extend(self.standing_scope.grants.iter()
                    .filter(|g| g.expires_at.is_none_or(|e| now < e))
                    .map(|g| {
                        serde_json::json!({
                            "lifetime": "standing",
                            "plugin_id": g.member,
                            "path": g.path,
                            "reason": g.reason,
                            "requested_because": serde_json::Value::Null,
                            "granted_by": g.granted_by,
                            "request_id": g.request_id,
                            // The distinction the route table argues for: a grant that
                            // ratified a member's ask carries that ask's id; one the operator
                            // originated carries none. Derived, never stored twice.
                            "origin": if g.request_id.is_some() {
                                "member_request"
                            } else {
                                "operator_initiated"
                            },
                            "granted_at": g.granted_at,
                            "expires_at": g.expires_at,
                            "secs_remaining": g.expires_at.map(|e| e.saturating_sub(now)),
                            "durability": "STANDING — survives restart; revocable",
                        })
                    }));
                v.sort_by(|a, b| {
                    a["plugin_id"].as_str().unwrap_or("")
                        .cmp(b["plugin_id"].as_str().unwrap_or(""))
                        .then(a["path"].as_str().unwrap_or("").cmp(b["path"].as_str().unwrap_or("")))
                });
                v
            },
            standing_generation: self.standing_scope.generation,
            stats_unavailable: stats_read_error,
            recent_unavailable: recent_read_error,
            deployment: deployment_health(self),
            instance_grants: {
                let now = crate::server::gate_escalation::now_secs();
                let mut v: Vec<serde_json::Value> = self
                    .instance_grants
                    .iter()
                    .filter(|(_, g)| g.is_live(now))
                    .map(|((plugin_id, role), g)| {
                        serde_json::json!({
                            "plugin_id": plugin_id,
                            "role": role,
                            "preset": g.preset,
                            "granted_by": g.granted_by,
                            "reason": g.reason,
                            "expires_at": g.expires_at,
                            "secs_remaining": g.expires_at.map(|e| e.saturating_sub(now)),
                        })
                    })
                    .collect();
                // Stable order, so the list does not reshuffle under the operator's cursor
                // between polls. HashMap iteration order is not an ordering a UI should inherit.
                v.sort_by(|a, b| a["plugin_id"].as_str().cmp(&b["plugin_id"].as_str()));
                v
            },
            // Declared, not inferred. These counts come from a bounded, projected read;
            // saying so is what lets a reader decide the compression is sufficient — or
            // escalate to the chain, which remains available and authoritative.
            basis: ReadBasis {
                mode: "windowed-projection".into(),
                window: Some(STATS_WINDOW),
                complete: false,
                note: format!(
                    "counts and trust derive from the most recent {STATS_WINDOW} chain rows, \
                     field-pruned; display-grade situational awareness, not evidence. \
                     The witness chain is authoritative — traverse it when certainty is required."
                ),
            },
            generated_at: Utc::now(),
        }
    }

    /// All-time failed outcomes (descending). Backs the `FAILED` filter
    /// in the dashboard, which scrolls across the full chain rather
    /// than just the recent window.
    pub fn failures_snapshot(&self, limit: u64) -> FailuresSnapshot {
        let entries: Vec<RecentEntry> = self
            .chain_store
            .read_failures(limit)
            .unwrap_or_default()
            .into_iter()
            .map(flatten_entry)
            .collect();
        FailuresSnapshot {
            entries,
            generated_at: Utc::now(),
        }
    }
}

/// Response shape for `/api/failures`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FailuresSnapshot {
    pub entries: Vec<RecentEntry>,
    pub generated_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Vault;
    use serde_json::json;
    use tempfile::TempDir;

    fn make_state() -> (TempDir, ServerState) {
        let dir = TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path(), "p").unwrap();
        (dir, state)
    }

    #[test]
    fn empty_snapshot_has_zero_stats() {
        let (_dir, state) = make_state();
        let s = state.dashboard_snapshot(20);
        assert_eq!(s.stats.total_actions, 0);
        assert_eq!(s.society.chain_length, 0);
        assert!(s.trust.is_empty());
        assert!(s.recent.is_empty());
    }

    #[test]
    fn deployment_health_distinguishes_current_stale_and_unknown() {
        let dir = TempDir::new().unwrap();
        let manifest = dir.path().join("current-build.json");

        let unknown = deployment_health_from_path(None);
        assert_eq!(unknown.state, "unknown");

        std::fs::write(&manifest, r#"{"build_id":"not-the-running-build"}"#).unwrap();
        let stale = deployment_health_from_path(Some(&manifest));
        assert_eq!(stale.state, "stale");
        assert_eq!(
            stale.current_build.as_deref(),
            Some("not-the-running-build")
        );

        let running = env!("HESTIA_GIT_VERSION");
        std::fs::write(&manifest, format!(r#"{{"build_id":"{running}"}}"#)).unwrap();
        let current = deployment_health_from_path(Some(&manifest));
        assert_eq!(current.state, "current");
        assert_eq!(current.current_build.as_deref(), Some(running));
    }

    #[test]
    fn deployment_update_status_projects_supervisor_states_without_inventing_success() {
        if !(cfg!(target_os = "linux") || cfg!(target_os = "macos")) {
            return;
        }
        let dir = TempDir::new().unwrap();
        let manifest = dir.path().join("current-build.json");
        std::fs::write(&manifest, r#"{"build_id":"authority-build"}"#).unwrap();
        let status = dir.path().join("deploy-status.tsv");
        let now = chrono::Utc::now();
        for (wire, expected) in [("requested", "requested"), ("held", "held"), ("running", "running"), ("failed", "failed"), ("succeeded", "failed")] {
            std::fs::write(&status, format!("{wire}\treq-1\ttarget-build\t{}\n", now.to_rfc3339())).unwrap();
            let health = deployment_health_from_path(Some(&manifest));
            assert_eq!(health.state, "stale");
            assert_eq!(health.update_state, expected, "wire state {wire}");
            assert_eq!(health.update_request_id.as_deref(), Some("req-1"));
        }
        std::fs::write(&status, format!("running\treq-future\ttarget-build\t{}\n", (now + chrono::Duration::seconds(30)).to_rfc3339())).unwrap();
        let future = deployment_health_from_path(Some(&manifest));
        assert_eq!(future.state, "stale");
        assert_eq!(future.update_state, "failed");
        std::fs::write(&manifest, format!(r#"{{"build_id":"{}"}}"#, env!("HESTIA_GIT_VERSION"))).unwrap();
        let health = deployment_health_from_path(Some(&manifest));
        assert_eq!(health.state, "current");
        assert_eq!(health.update_state, "idle");
        assert!(health.update_request_id.is_none());
    }

    #[test]
    fn deployment_health_separates_daemon_build_from_last_gate_self_report() {
        let (_dir, mut state) = make_state();
        let unknown = deployment_health(&state);
        assert_eq!(unknown.gate_engine.state, "unknown");

        state.gate_capabilities.insert(
            "codex".into(),
            ["society-floor:v1".to_string()].into_iter().collect(),
        );
        state
            .gate_capabilities
            .insert("legacy-member".into(), std::collections::HashSet::new());
        let partial = deployment_health(&state);
        assert_eq!(partial.gate_engine.state, "partial");
        assert_eq!(partial.gate_engine.capable_members, ["codex"]);
        assert_eq!(
            partial.gate_engine.reported_without_capability,
            ["legacy-member"]
        );

        state.gate_capabilities.remove("legacy-member");
        let capable = deployment_health(&state);
        assert_eq!(capable.gate_engine.state, "last-self-report-capable");
        assert!(
            capable.gate_engine.note.contains("A1")
                && capable.gate_engine.note.contains("#481")
                && capable
                    .gate_engine
                    .note
                    .contains("no freshness/session/build binding"),
            "the dashboard must not launder a self-report into artifact attestation"
        );
    }

    /// The snapshot must CARRY pending scope requests, and must drop the decided ones.
    ///
    /// Asserted on the payload rather than on "the field exists", because today's lesson was
    /// exactly that distinction: a peer replaced a membership assertion in the gate's
    /// self-protection test with five behavioural probes and proved the rule could not fire
    /// while the test stayed green. A panel test that only checked the struct had a field
    /// would repeat it — the operator does not read the struct.
    #[test]
    fn snapshot_carries_pending_scope_requests_and_drops_decided_ones() {
        use crate::server::state::{SCOPE_REQUEST_TTL_SECS, ScopeRequest};
        let (_dir, mut state) = make_state();
        let now = crate::server::gate_escalation::now_secs();

        let mk = |id: &str, granted: Option<bool>, expires: u64| ScopeRequest {
            id: id.to_string(),
            plugin_id: "kimi-code".into(),
            role: "role:constellation:member".into(),
            path: format!("/outside/{id}.md"),
            reason: "dp directed me to read this in-session".into(),
            requested_at: now,
            expires_at: expires,
            granted,
            decided_by: granted.map(|_| "operator".to_string()),
            decided_at: granted.map(|_| now),
            decision_reason: None,
        };

        state.scope_requests.insert(
            "pend".into(),
            mk("pend", None, now + SCOPE_REQUEST_TTL_SECS),
        );
        // A SECOND pending request, filed EARLIER, so the oldest-first ordering is proven
        // rather than asserted in a comment (kimi NOT-SAME review of #186). The first fixture
        // gave all four the same `requested_at`, so the sort could have been absent, reversed
        // or arbitrary and the test would still have passed — a green about a claim it never
        // exercised, which is the defect this whole thread keeps finding.
        let mut older = mk("older", None, now + SCOPE_REQUEST_TTL_SECS);
        older.requested_at = now.saturating_sub(600);
        state.scope_requests.insert("older".into(), older);
        state
            .scope_requests
            .insert("granted".into(), mk("granted", Some(true), now + 3600));
        state
            .scope_requests
            .insert("refused".into(), mk("refused", Some(false), now + 3600));
        // An undecided request past its window is EXPIRED, and expired is a refusal — it must
        // not sit in the queue offering a button the daemon would refuse.
        state
            .scope_requests
            .insert("lapsed".into(), mk("lapsed", None, now.saturating_sub(1)));

        let s = state.dashboard_snapshot(20);
        let ids: Vec<&str> = s
            .pending_scope_requests
            .iter()
            .map(|r| r["request_id"].as_str().unwrap())
            .collect();
        // OLDEST FIRST: the one closest to lapsing needs a human soonest, and an unanswered
        // request expires into a REFUSAL. Asserted on order, not just membership.
        assert_eq!(
            ids,
            vec!["older", "pend"],
            "only live pending requests may be offered, oldest first — the one nearest its \
             deadline is the one a human must see first"
        );

        let row = s
            .pending_scope_requests
            .iter()
            .find(|r| r["request_id"] == "pend")
            .expect("the pending fixture must be present");
        // THE BASIS travels with the ask. A queue that shows who and what but not why is the
        // "no reason" defect arriving on a second surface (dp, 2026-08-03).
        assert_eq!(row["reason"], "dp directed me to read this in-session");
        assert_eq!(row["path"], "/outside/pend.md");
        // Caller-asserted, and labelled so the UI cannot render a claim as an identity.
        assert_eq!(row["claimed_by"], "kimi-code");
        assert!(row.get("secs_remaining").is_some());
    }

    /// A FAILED FEED READ MUST BE DISTINGUISHABLE FROM AN EMPTY CHAIN.
    ///
    /// dp, 2026-08-04: "chain display still blank for all agents all timelines." The feed read
    /// was `.unwrap_or_default()`, so any error became an empty Vec and the dashboard served
    /// HTTP 200 rendering "Waiting for the first chain entry…" over a chain that was actively
    /// being written. The stats read beside it had been hardened for this exact defect on
    /// 2026-08-01 and the feed was left behind.
    ///
    /// Asserted on the SERIALIZED payload, because that is what the browser reads — and because
    /// the whole family of defects this repo keeps finding is a field being present in a struct
    /// while absent from the thing that consumes it.
    #[test]
    fn an_empty_feed_and_a_failed_feed_are_distinguishable_on_the_wire() {
        let (_dir, state) = make_state();

        // A genuinely empty chain: no entries, and NO failure claimed.
        let s = state.dashboard_snapshot(20);
        let v = serde_json::to_value(&s).expect("serialize");
        assert!(s.recent.is_empty(), "fixture has no entries");
        assert!(
            v.get("recent_unavailable").is_none(),
            "an empty chain must not claim a read failure — that would cry wolf on a quiet fleet"
        );

        // The two states must not be the same JSON. If `recent_unavailable` is absent in both,
        // the browser has no way to tell "nothing happened" from "we could not find out".
        let mut broken = s.clone();
        broken.recent_unavailable = Some("database is locked".into());
        let bv = serde_json::to_value(&broken).expect("serialize");
        assert_eq!(
            bv["recent_unavailable"], "database is locked",
            "the failure reason must reach the client verbatim; a bare boolean would tell the \
             operator something is wrong without telling them what"
        );
        assert_ne!(
            v.get("recent_unavailable"),
            bv.get("recent_unavailable"),
            "empty and unavailable serialize identically — this is the defect, not the fix"
        );
    }

    #[test]
    fn snapshot_reflects_outcomes() {
        let (_dir, state) = make_state();
        for _ in 0..3 {
            state
                .append_chain(
                    "outcome",
                    json!({"tool_name": "Read", "success": true, "magnitude": 0.2, "plugin_id": "a"}),
                )
                .unwrap();
        }
        state
            .append_chain(
                "outcome",
                json!({"tool_name": "Bash", "success": false, "magnitude": 0.8, "plugin_id": "a"}),
            )
            .unwrap();
        state.apply_outcome("a", true, 0.5).unwrap();
        state.apply_outcome("a", false, 0.5).unwrap();

        // Two policy denials: these must NOT enter the success-rate denominator
        // (a deny is the gate working, not a tool failing) but MUST be counted.
        for _ in 0..2 {
            state
                .append_chain(
                    "policy_decision",
                    json!({"tool_name": "Bash", "decision": "deny", "plugin_id": "a"}),
                )
                .unwrap();
        }

        let s = state.dashboard_snapshot(20);
        assert_eq!(
            s.stats.total_actions, 4,
            "denies excluded from executed-tool total"
        );
        assert_eq!(s.stats.successful_actions, 3);
        assert_eq!(s.stats.failed_actions, 1);
        assert_eq!(s.stats.denied_actions, 2, "denies counted separately");
        assert!(
            (s.stats.success_rate - 0.75).abs() < 1e-9,
            "denies don't move success_rate"
        );
        // Read=3, Bash=1
        assert_eq!(s.stats.by_tool[0], ("Read".into(), 3));
        assert_eq!(s.stats.by_tool[1], ("Bash".into(), 1));

        assert_eq!(s.trust.len(), 1);
        assert_eq!(s.trust[0].plugin_id, "a");
        assert_eq!(s.trust[0].action_count, 2);

        // 4 outcomes + 2 denies, descending (denies appended last).
        assert_eq!(s.recent.len(), 6);
        assert_eq!(s.recent[0].event_type, "policy_decision");
        // The most recent outcome (Bash, failed) now sits behind the two denies.
        assert_eq!(s.recent[2].event_type, "outcome");
        assert_eq!(s.recent[2].tool_name.as_deref(), Some("Bash"));
        assert_eq!(s.recent[2].success, Some(false));
    }

    #[test]
    fn synthetic_plugins_excluded_from_trust_list() {
        let (_dir, mut state) = make_state();

        // "real" plugin: active outcomes
        state
            .append_chain(
                "outcome",
                json!({"tool_name": "Read", "success": true, "magnitude": 0.2, "plugin_id": "real"}),
            )
            .unwrap();
        state.apply_outcome("real", true, 0.5).unwrap();

        // "harness" plugin: active outcomes, but flagged synthetic
        state
            .append_chain(
                "outcome",
                json!({"tool_name": "Read", "success": true, "magnitude": 0.2, "plugin_id": "harness"}),
            )
            .unwrap();
        state.apply_outcome("harness", true, 0.5).unwrap();
        assert!(state.mark_synthetic("harness", 3).unwrap());

        let s = state.dashboard_snapshot(20);
        assert_eq!(s.trust.len(), 1, "harness should be excluded");
        assert_eq!(s.trust[0].plugin_id, "real");

        // Recent feed still includes both — the chain is authoritative,
        // we only filter aggregations.
        assert_eq!(s.recent.len(), 2);
    }
}
