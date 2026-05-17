//! Type definitions for the Hestia plugin SDK (Rust).
//!
//! Mirrors the TypeScript reference and Python parallel. See ADR-0005 in
//! the repo root for the canonical MCP surface specification.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// Protocol version this SDK targets.
pub const HESTIA_PROTOCOL_VERSION: u32 = 1;

/// Configuration for a `HestiaClient`.
#[derive(Debug, Clone)]
pub struct HestiaClientConfig {
    /// Stable identifier for this plugin (e.g. "claude-code", "openclaw").
    pub plugin_id: String,
    /// Which agent client this plugin is for ("claude-code", "openclaw", ...).
    pub host_agent: String,
    /// Optional semver of the plugin's own code.
    pub plugin_version: Option<String>,
    /// Optional semver of the host agent.
    pub host_agent_version: Option<String>,
    /// Society role this plugin wants. Defaults to "citizen".
    pub requested_role: String,
    /// Override Hestia's MCP endpoint. If `None`, auto-discover.
    pub hestia_endpoint: Option<String>,
}

impl HestiaClientConfig {
    /// Build a config with the required fields. Defaults `requested_role` to "citizen".
    pub fn new(plugin_id: impl Into<String>, host_agent: impl Into<String>) -> Self {
        Self {
            plugin_id: plugin_id.into(),
            host_agent: host_agent.into(),
            plugin_version: None,
            host_agent_version: None,
            requested_role: "citizen".to_string(),
            hestia_endpoint: None,
        }
    }

    pub fn with_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.hestia_endpoint = Some(endpoint.into());
        self
    }

    pub fn with_role(mut self, role: impl Into<String>) -> Self {
        self.requested_role = role.into();
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectResult {
    pub session_id: String,
    pub soft_lct: String,
    pub assigned_role: String,
    pub protocol_version: u32,
}

#[derive(Debug, Clone, Default)]
pub struct ToolCallSpec {
    pub tool_name: String,
    pub target: Option<String>,
    pub parameters: HashMap<String, serde_json::Value>,
    pub atp_stake: Option<f64>,
}

impl ToolCallSpec {
    pub fn new(tool_name: impl Into<String>) -> Self {
        Self {
            tool_name: tool_name.into(),
            ..Default::default()
        }
    }

    pub fn with_target(mut self, target: impl Into<String>) -> Self {
        self.target = Some(target.into());
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct R6Action {
    pub action_id: Uuid,
    pub tool_name: String,
    pub started_at: DateTime<Utc>,
    pub chain_position: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Outcome {
    pub success: bool,
    /// Domain-specific magnitude in `[0..1]`.
    pub magnitude: f64,
    pub error: Option<String>,
    pub result: HashMap<String, serde_json::Value>,
}

impl Outcome {
    pub fn success(magnitude: f64) -> Self {
        Self {
            success: true,
            magnitude,
            error: None,
            result: HashMap::new(),
        }
    }

    pub fn failure(magnitude: f64, error: impl Into<String>) -> Self {
        Self {
            success: false,
            magnitude,
            error: Some(error.into()),
            result: HashMap::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PolicyDecision {
    Allow,
    Deny,
    Warn,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PolicyResult {
    pub decision: PolicyDecision,
    pub reason: String,
    /// Stable identifier for the rule that fired (e.g.
    /// `"deny-destructive-commands"`). `None` when no rule matched
    /// and the default policy applied.
    #[serde(default)]
    pub rule_id: Option<String>,
    /// Human-readable rule name. `None` for default-policy decisions.
    #[serde(default)]
    pub rule_name: Option<String>,
    /// Aliased view of `rule_id`. Kept for v0 SDK back-compat — new
    /// code should read `rule_id`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy_id: Option<String>,
    /// `False` if Hestia is in dry-run mode (decision returned but not enforced).
    #[serde(default = "default_true")]
    pub enforced: bool,
    /// Audit-trail constraint strings (`policy:`, `decision:`, `rule:`).
    /// Always at least three entries when the field is present.
    #[serde(default)]
    pub constraints: Vec<String>,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone)]
pub struct VaultGetOptions {
    pub scope: Vec<String>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VaultValue {
    pub value: String,
    pub approval_token: Option<String>,
}

#[derive(Debug, Clone)]
pub struct VaultSetOptions {
    pub scope: Vec<String>,
    pub tags: Vec<String>,
    pub allowed_consumers: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct T3Roots {
    pub talent: f64,
    pub training: f64,
    pub temperament: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct V3Roots {
    pub valuation: f64,
    pub veracity: f64,
    pub validity: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrustState {
    /// Web4 entity id (e.g. "plugin:claude-code"). Carries the entity-type prefix.
    #[serde(default)]
    pub entity_id: String,
    pub t3: T3Roots,
    pub v3: V3Roots,
    pub level: String,
    pub action_count: u64,
    #[serde(default)]
    pub success_count: u64,
    #[serde(default)]
    pub success_rate: f64,
    pub days_since_last: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OutcomeResult {
    pub witness_entry_hash: String,
    pub updated_trust_state: TrustState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WitnessEntry {
    pub hash: String,
    pub prev_hash: String,
    pub timestamp: String,
    pub event_type: String,
    #[serde(default)]
    pub event_data: HashMap<String, serde_json::Value>,
    pub signer_lct: String,
    pub chain_position: u64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct HistoryFilter {
    pub tool_name: Option<String>,
    pub target_pattern: Option<String>,
    pub since: Option<String>,
    #[serde(default)]
    pub limit: Option<u32>,
    pub outcome: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoryResult {
    pub entries: Vec<WitnessEntry>,
    pub has_more: bool,
}
