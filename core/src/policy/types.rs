//! Core data types for the policy engine.
//!
//! Ports the dataclasses from `claude-code/plugins/web4-governance/governance/`
//! Python reference implementation. The on-wire shapes (when these
//! cross the MCP boundary) are documented in
//! `web4/web4-standard/core-spec/presence-protocol.md`.

use serde::{Deserialize, Serialize};

/// One of the three allow/deny/warn verdicts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Hash)]
#[serde(rename_all = "lowercase")]
pub enum PolicyDecision {
    Allow,
    Deny,
    Warn,
}

impl PolicyDecision {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Deny => "deny",
            Self::Warn => "warn",
        }
    }
}

/// Rate-limit spec on a single rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RateLimitSpec {
    /// Maximum allowed firings of this rule within the window.
    pub max_count: u32,
    /// Window length in milliseconds.
    pub window_ms: u64,
}

/// Temporal constraints on a rule. The rule only matches if `now`
/// falls inside the specified hours/days. Both fields optional; if
/// both are `None`, time-of-day doesn't gate the rule.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct TimeWindow {
    /// Allowed hours `[start, end]` in 24-h local time. E.g. `(9, 17)` =
    /// 9am to 5pm inclusive.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub allowed_hours: Option<(u8, u8)>,
    /// Allowed days of week. `0` = Sunday, `1` = Monday, …, `6` = Saturday.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub allowed_days: Option<Vec<u8>>,
    /// IANA timezone name (e.g. `"America/Los_Angeles"`). If `None`,
    /// uses the daemon's local time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timezone: Option<String>,
}

/// Match criteria for a rule. All present fields must match (AND logic).
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct PolicyMatch {
    /// Tool names to match (e.g. `["Bash", "Shell"]`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tools: Option<Vec<String>>,

    /// Tool categories to match (e.g. `["file_read", "credential_access"]`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub categories: Option<Vec<String>>,

    /// Glob (default) or regex (if `target_patterns_are_regex`) over the
    /// target string.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_patterns: Option<Vec<String>>,
    #[serde(default)]
    pub target_patterns_are_regex: bool,

    /// Glob/regex over the full Bash command (different from `target`,
    /// which is usually just the first token).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command_patterns: Option<Vec<String>>,
    #[serde(default)]
    pub command_patterns_are_regex: bool,

    /// If any of these strings appear in the full command, the rule does
    /// NOT match. Useful for "git push WITHOUT a PAT" style negative rules.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command_must_not_contain: Option<Vec<String>>,

    /// Time window constraint.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub time_window: Option<TimeWindow>,

    /// Rate limit on rule firing. If under the limit, the rule does NOT
    /// fire (allowed behavior); if over, the rule fires.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rate_limit: Option<RateLimitSpec>,
}

/// A single policy rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyRule {
    pub id: String,
    pub name: String,
    /// Lower number = evaluated first. Resolves the "first-rule-wins" tie.
    pub priority: i32,
    pub decision: PolicyDecision,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    pub r#match: PolicyMatch,
}

/// A complete policy: default verdict + a list of rules + enforcement flag.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyConfig {
    /// Verdict returned when no rule matches.
    pub default_policy: PolicyDecision,
    /// If `false`, the engine returns the decision but marks `enforced = false`
    /// so the caller can run in audit/observation mode.
    pub enforce: bool,
    pub rules: Vec<PolicyRule>,
}

/// Result of evaluating a tool call against a policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyEvaluation {
    pub decision: PolicyDecision,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rule_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rule_name: Option<String>,
    pub reason: String,
    pub enforced: bool,
    /// Stable list of `policy:`, `decision:`, `rule:` namespaced
    /// constraint strings the caller can log/echo. Useful for audit
    /// trails. Always at least three entries.
    #[serde(default)]
    pub constraints: Vec<String>,
}

/// The action being evaluated. Mirrors the orchestrator-side R6Action
/// shape but locally-typed.
#[derive(Debug, Clone)]
pub struct PolicyAction<'a> {
    pub tool_name: &'a str,
    pub category: &'a str,
    pub target: Option<&'a str>,
    pub full_command: Option<&'a str>,
}

/// Named preset alongside its config. Keyed by `name` ("permissive",
/// "safety", "strict", "audit-only").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PresetDefinition {
    pub name: String,
    pub description: String,
    pub config: PolicyConfig,
}
