//! Dashboard snapshot — aggregations consumed by both the web UI and the
//! TUI. Cheap enough to call every 1-2s.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use super::state::ServerState;

/// Top-level dashboard payload.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DashboardSnapshot {
    pub society: SocietyView,
    pub stats: ActivityStats,
    pub trust: Vec<TrustView>,
    pub recent: Vec<RecentEntry>,
    pub delegations: Vec<serde_json::Value>,
    pub hub_connections: Vec<serde_json::Value>,
    pub generated_at: DateTime<Utc>,
}

/// Identity + macro state of this Hestia society.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SocietyView {
    pub sovereign_lct: String,
    pub chain_length: u64,
    pub active_sessions: usize,
    pub vault_entries: usize,
    pub known_plugins: usize,
}

/// Aggregate counts across the witness chain.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivityStats {
    pub total_actions: u64,
    pub successful_actions: u64,
    pub failed_actions: u64,
    /// 0.0–1.0
    pub success_rate: f64,
    /// Tool name → count, descending.
    pub by_tool: Vec<(String, u64)>,
    /// Actions in the last 60 minutes (approximate; counted by timestamp).
    pub actions_last_hour: u64,
}

/// One plugin's trust snapshot.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrustView {
    pub plugin_id: String,
    pub entity_id: String,
    pub level: String,
    pub t3_talent: f64,
    pub t3_training: f64,
    pub t3_temperament: f64,
    pub t3_average: f64,
    pub v3_valuation: f64,
    pub v3_veracity: f64,
    pub v3_validity: f64,
    pub v3_average: f64,
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
        let mut by_tool: BTreeMap<String, u64> = BTreeMap::new();
        let one_hour_ago = Utc::now() - chrono::Duration::hours(1);
        let mut last_hour = 0u64;
        // Per-plugin "last seen" timestamps, used to decide which
        // orchestrators are "active" (= seen in the last hour).
        let mut last_seen_per_plugin: std::collections::HashMap<String, chrono::DateTime<Utc>> =
            std::collections::HashMap::new();

        for e in &stats_window {
            // Track per-plugin last-seen across any event that carries
            // a plugin_id. Outcomes are the main signal now that
            // session_started is no longer written; historical chains
            // may still contain session_started entries with plugin_id.
            if let Some(pid) = e.event_data.get("plugin_id").and_then(|v| v.as_str()) {
                let entry = last_seen_per_plugin
                    .entry(pid.to_string())
                    .or_insert(e.timestamp);
                if e.timestamp > *entry {
                    *entry = e.timestamp;
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
            if let Some(tname) = e.event_data.get("tool_name").and_then(|v| v.as_str()) {
                *by_tool.entry(tname.to_string()).or_insert(0) += 1;
            }
        }
        let mut by_tool_vec: Vec<(String, u64)> = by_tool.into_iter().collect();
        by_tool_vec.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        let success_rate = if total == 0 { 0.0 } else { succ as f64 / total as f64 };

        // Build the trust list, but only for plugins that have been active
        // within the last hour AND are not flagged synthetic. Drops both
        // stale orchestrators (cursor, openclaw seeds) and test harnesses
        // (conformance-runner, fuzzers) from the operator-facing view.
        let known_plugins = self.trust_store.list().unwrap_or_default();
        let trust: Vec<TrustView> = known_plugins
            .iter()
            .filter(|pid| !self.is_synthetic(pid))
            .filter(|pid| {
                last_seen_per_plugin
                    .get(*pid)
                    .map(|ts| *ts > one_hour_ago)
                    .unwrap_or(false)
            })
            .map(|pid| {
                let t = self.trust(pid);
                let t3_avg = t.t3_average();
                let v3_avg = t.v3_average();
                TrustView {
                    plugin_id: pid.clone(),
                    entity_id: t.entity_id.clone(),
                    level: t.trust_level().as_str().to_string(),
                    t3_talent: t.t3.talent,
                    t3_training: t.t3.training,
                    t3_temperament: t.t3.temperament,
                    t3_average: t3_avg,
                    v3_valuation: t.v3.valuation,
                    v3_veracity: t.v3.veracity,
                    v3_validity: t.v3.validity,
                    v3_average: v3_avg,
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

        let delegations = crate::delegation::DelegationStore::load(&self.home)
            .ok()
            .map(|s| s.delegations.iter()
                .map(|d| serde_json::to_value(d).unwrap_or_default())
                .collect())
            .unwrap_or_default();

        let hub_connections = crate::hub::HubStore::load(&self.home)
            .ok()
            .map(|s| s.connections.iter()
                .map(|c| serde_json::to_value(c).unwrap_or_default())
                .collect())
            .unwrap_or_default();

        DashboardSnapshot {
            society: SocietyView {
                sovereign_lct: self.sovereign_lct.clone(),
                chain_length: self.chain_len(),
                active_sessions: self.sessions.len(),
                vault_entries: self.vault.list().len(),
                known_plugins: known_plugins.len(),
            },
            stats: ActivityStats {
                total_actions: total,
                successful_actions: succ,
                failed_actions: fail,
                success_rate,
                by_tool: by_tool_vec,
                actions_last_hour: last_hour,
            },
            trust,
            recent,
            delegations,
            hub_connections,
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
        let state = ServerState::open(vault, dir.path()).unwrap();
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

        let s = state.dashboard_snapshot(20);
        assert_eq!(s.stats.total_actions, 4);
        assert_eq!(s.stats.successful_actions, 3);
        assert_eq!(s.stats.failed_actions, 1);
        assert!((s.stats.success_rate - 0.75).abs() < 1e-9);
        // Read=3, Bash=1
        assert_eq!(s.stats.by_tool[0], ("Read".into(), 3));
        assert_eq!(s.stats.by_tool[1], ("Bash".into(), 1));

        assert_eq!(s.trust.len(), 1);
        assert_eq!(s.trust[0].plugin_id, "a");
        assert_eq!(s.trust[0].action_count, 2);

        assert_eq!(s.recent.len(), 4);
        assert_eq!(s.recent[0].event_type, "outcome");
        assert_eq!(s.recent[0].tool_name.as_deref(), Some("Bash"));
        assert_eq!(s.recent[0].success, Some(false));
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
        assert!(state.mark_synthetic("harness"));

        let s = state.dashboard_snapshot(20);
        assert_eq!(s.trust.len(), 1, "harness should be excluded");
        assert_eq!(s.trust[0].plugin_id, "real");

        // Recent feed still includes both — the chain is authoritative,
        // we only filter aggregations.
        assert_eq!(s.recent.len(), 2);
    }
}
