//! Dashboard snapshot — aggregations consumed by both the web UI and the
//! TUI. Cheap enough to call every 1-2s.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use super::state::ServerState;
use web4_trust_core::EntityTrust;

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
    PolicyView { preset: "safety".into(), enforce: true }
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
    pub generated_at: DateTime<Utc>,
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
        tool_name: d.get("tool_name").and_then(|v| v.as_str()).map(String::from),
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
    }
}

impl ServerState {
    /// Build the dashboard snapshot. Reads up to `recent_limit` chain
    /// entries for the live feed; aggregates over the full chain for stats.
    pub fn dashboard_snapshot(&self, recent_limit: u64) -> DashboardSnapshot {
        // For activity stats, scan the recent window plus a wider sample.
        // The chain can be huge; cap the stats window at 10k entries which
        // is plenty for an "actions seen" picture without scanning forever.
        let stats_window = self
            .chain_store
            .read_recent(10_000)
            .unwrap_or_default();

        let mut total = 0u64;
        let mut succ = 0u64;
        let mut fail = 0u64;
        let mut denied = 0u64;
        let mut policy_decisions: Vec<RecentEntry> = Vec::new();
        let mut deny_kept = 0usize;
        let mut warn_kept = 0usize;
        let mut by_tool: BTreeMap<String, u64> = BTreeMap::new();
        let one_hour_ago = Utc::now() - chrono::Duration::hours(1);
        let mut last_hour = 0u64;
        // Per-plugin slices of the same window, keyed by the human plugin_id:
        // (total, succ, fail, denied, last_hour, by_tool). Backs the chip filter.
        #[allow(clippy::type_complexity)]
        let mut per_plugin: BTreeMap<String, (u64, u64, u64, u64, u64, BTreeMap<String, u64>)> =
            BTreeMap::new();
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
            if let Some(pid) = e.event_data.get("plugin_id").and_then(|v| v.as_str()) {
                let role = e
                    .event_data
                    .get("role_lct")
                    .and_then(|v| v.as_str())
                    .unwrap_or(crate::reputation::DEFAULT_CONSTELLATION_ROLE);
                let key = self.trust_entity_key(pid, role);
                let entry = active_entities
                    .entry(key)
                    .or_insert((e.timestamp, pid.to_string(), role.to_string()));
                if e.timestamp > entry.0 {
                    entry.0 = e.timestamp;
                }
            }
            // A policy denial blocks the tool before it runs, so it never
            // produces an `outcome`. Count it separately (not as a failure).
            if e.event_type == "policy_decision"
                && e.event_data.get("decision").and_then(|v| v.as_str()) == Some("deny")
            {
                denied += 1;
                if let Some(pid) = e.event_data.get("plugin_id").and_then(|v| v.as_str()) {
                    per_plugin.entry(pid.to_string()).or_default().3 += 1;
                }
            }
            // Collect policy decisions for the warn/deny feed filters across the
            // wider stats window (denies can be older than `recent_limit`). Cap
            // warn and deny INDEPENDENTLY so frequent warns can't crowd out the
            // rarer denies — a single shared cap made the deny list look empty.
            if e.event_type == "policy_decision" {
                let dec = e.event_data.get("decision").and_then(|v| v.as_str());
                let keep = match dec {
                    Some("deny") if deny_kept < 300 => { deny_kept += 1; true }
                    Some("warn") if warn_kept < 300 => { warn_kept += 1; true }
                    _ => false,
                };
                if keep {
                    policy_decisions.push(flatten_entry(e.clone()));
                }
            }
            if e.event_type != "outcome" {
                continue;
            }
            total += 1;
            if e.timestamp > one_hour_ago {
                last_hour += 1;
            }
            let success = e
                .event_data
                .get("success")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if success {
                succ += 1;
            } else {
                fail += 1;
            }
            let tname = e.event_data.get("tool_name").and_then(|v| v.as_str());
            if let Some(tname) = tname {
                *by_tool.entry(tname.to_string()).or_insert(0) += 1;
            }
            // Same slice, per plugin.
            if let Some(pid) = e.event_data.get("plugin_id").and_then(|v| v.as_str()) {
                let p = per_plugin.entry(pid.to_string()).or_default();
                p.0 += 1;
                if success { p.1 += 1 } else { p.2 += 1 }
                if e.timestamp > one_hour_ago {
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
        let success_rate = if total == 0 { 0.0 } else { succ as f64 / total as f64 };

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
        active_sorted.sort_by(|a, b| (&a.1 .1, &a.1 .2).cmp(&(&b.1 .1, &b.1 .2)));
        let trust: Vec<TrustView> = active_sorted
            .into_iter()
            .map(|(key, (_ts, pid, _role))| {
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
                TrustView {
                    plugin_id: pid.clone(),
                    entity_id: t.entity_id.clone(),
                    level: t.trust_level().as_str().to_string(),
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
                }
            })
            .collect();

        // Recent feed: flatten the outcome / session_started / etc. shape.
        let recent: Vec<RecentEntry> = self
            .chain_store
            .read_recent(recent_limit)
            .unwrap_or_default()
            .into_iter()
            .map(flatten_entry)
            .collect();

        let delegations = crate::delegation::DelegationStore::load(&self.vault)
            .ok()
            .map(|s| s.delegations.iter()
                .map(|d| serde_json::to_value(d).unwrap_or_default())
                .collect())
            .unwrap_or_default();

        let profile = crate::profile::ProfileStore::load(&self.vault)
            .ok()
            .and_then(|s| serde_json::to_value(&s.present(&crate::profile::Visibility::Private)).ok());

        let constellation = crate::constellation::ConstellationStore::load(&self.vault)
            .ok()
            .and_then(|s| serde_json::to_value(&s.proof()).ok());

        let hub_connections = crate::hub::HubStore::load(&self.vault)
            .ok()
            .map(|s| s.connections.iter()
                .map(|c| serde_json::to_value(c).unwrap_or_default())
                .collect())
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
        for t in &trust {
            if crate::orchestrators::lookup(&t.plugin_id).is_none() {
                orchestrators.push(serde_json::json!({
                    "id": t.plugin_id,
                    "name": t.plugin_id,
                    "running": true,
                    "engaged": true,
                    "installed": true,
                    "connected": true,
                    "plugin_available": false,
                }));
            }
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
                    .unwrap_or_default().trim_matches('"').to_string(),
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
        assert_eq!(s.stats.total_actions, 4, "denies excluded from executed-tool total");
        assert_eq!(s.stats.successful_actions, 3);
        assert_eq!(s.stats.failed_actions, 1);
        assert_eq!(s.stats.denied_actions, 2, "denies counted separately");
        assert!((s.stats.success_rate - 0.75).abs() < 1e-9, "denies don't move success_rate");
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
