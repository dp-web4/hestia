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
    /// Strictness rank for combining policies — a stricter verdict wins.
    /// `Allow` < `Warn` < `Deny`. Used to fold a role-overlay verdict into the
    /// base so a self-declared role can only ever tighten law, never loosen it.
    pub fn severity(&self) -> u8 {
        match self {
            Self::Allow => 0,
            Self::Warn => 1,
            Self::Deny => 2,
        }
    }

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

impl PolicyEvaluation {
    /// Agent-facing steering for a blocked call: WHY (rule + reason), FRAME
    /// (boundary, not a tool failure), DON'T (no blind retry), DO (adjust or
    /// ask). Composed daemon-side so every client — the claude-code hook, the
    /// Kimi adapter — surfaces the same text verbatim instead of each
    /// inventing its own. `None` unless this is an enforced deny: warn already
    /// lets the call proceed, and an audit-only would-deny must not tell the
    /// agent to stop retrying a call that actually ran.
    ///
    /// The DO leg says "ask your operator" until the cooperative MCP channel
    /// (`request_scope`, gate-shape note 2026-07-09) is registered — naming a
    /// tool that doesn't exist yet would send agents into a tool-not-found
    /// loop, the exact failure mode this text exists to prevent.
    pub fn guidance(&self) -> Option<String> {
        if self.decision != PolicyDecision::Deny || !self.enforced {
            return None;
        }
        let rule = self.rule_name.as_deref().unwrap_or("policy");
        Some(format!(
            "hestia deny [rule: {rule}] — {reason}. This is a boundary, not a failure: do not \
             re-run the same call. Either adjust your approach to stay in scope, or if you \
             believe the action is legitimately needed, ask your operator and state your \
             rationale — asking builds trust; reaching does not.",
            reason = self.reason
        ))
    }
}

/// Fold a role-overlay evaluation into the base by STRICTEST verdict
/// (`Allow` < `Warn` < `Deny`), so a self-declared role can only ever
/// tighten the base, never loosen it.
///
/// Severity TIES break in favor of the ENFORCED evaluation: if the base
/// carries an audit-only deny on a category the role also (enforced-)denies,
/// a bare severity comparison would let the unenforced base eval win and
/// `deny && enforced` fail — the ratified role law silently defanged by the
/// fold itself (HUB post-hoc review note 1, 2026-07-07). On a full tie the
/// base wins, keeping its attribution.
pub fn fold_strictest(base: PolicyEvaluation, role: PolicyEvaluation) -> PolicyEvaluation {
    let base_rank = (base.decision.severity(), base.enforced);
    let role_rank = (role.decision.severity(), role.enforced);
    if role_rank > base_rank {
        role
    } else {
        base
    }
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

#[cfg(test)]
mod severity_tests {
    use super::*;

    #[test]
    fn severity_orders_allow_below_warn_below_deny() {
        assert!(PolicyDecision::Allow.severity() < PolicyDecision::Warn.severity());
        assert!(PolicyDecision::Warn.severity() < PolicyDecision::Deny.severity());
    }

    fn eval(decision: PolicyDecision, enforced: bool, tag: &str) -> PolicyEvaluation {
        PolicyEvaluation {
            decision,
            rule_id: Some(tag.into()),
            rule_name: None,
            reason: tag.into(),
            enforced,
            constraints: vec![],
        }
    }

    /// Regression pin (HUB review note 1): an audit-only base deny must not
    /// shadow an enforced role deny of equal severity — the fold breaks
    /// severity ties in favor of `enforced`.
    #[test]
    fn fold_breaks_severity_tie_toward_enforced() {
        let base = eval(PolicyDecision::Deny, false, "base-audit-only");
        let role = eval(PolicyDecision::Deny, true, "role-ratified");
        let folded = fold_strictest(base, role);
        assert!(folded.enforced, "enforced role deny must win the tie");
        assert_eq!(folded.rule_id.as_deref(), Some("role-ratified"));
    }

    #[test]
    fn fold_still_prefers_stricter_verdict_and_base_on_full_tie() {
        // Stricter verdict wins regardless of enforcement.
        let folded = fold_strictest(
            eval(PolicyDecision::Warn, true, "base"),
            eval(PolicyDecision::Deny, false, "role"),
        );
        assert_eq!(folded.decision, PolicyDecision::Deny);
        // Full tie → base wins, keeping its attribution.
        let folded = fold_strictest(
            eval(PolicyDecision::Deny, true, "base"),
            eval(PolicyDecision::Deny, true, "role"),
        );
        assert_eq!(folded.rule_id.as_deref(), Some("base"));
    }

    /// Deny-as-redirect: guidance exists exactly for an enforced deny and
    /// carries all four legs (why / frame / don't / do). Warn proceeds and
    /// audit-only would-deny actually ran — steering "don't re-run" there
    /// would be false, so both must stay None.
    #[test]
    fn guidance_only_on_enforced_deny_with_all_four_legs() {
        let mut e = eval(PolicyDecision::Deny, true, "no destructive commands");
        e.rule_name = Some("deny-destructive".into());
        let g = e.guidance().expect("enforced deny must carry guidance");
        assert!(g.contains("deny-destructive"), "WHY: rule name");
        assert!(g.contains("no destructive commands"), "WHY: reason");
        assert!(g.contains("boundary, not a failure"), "FRAME");
        assert!(g.contains("do not re-run the same call"), "DON'T");
        assert!(g.contains("ask your operator"), "DO");

        assert_eq!(eval(PolicyDecision::Warn, true, "w").guidance(), None);
        assert_eq!(eval(PolicyDecision::Deny, false, "audit").guidance(), None);
        assert_eq!(eval(PolicyDecision::Allow, true, "a").guidance(), None);
    }
}
