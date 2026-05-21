//! Policy engine — evaluates a tool call against a `PolicyConfig`.
//!
//! Ports the `PolicyEntity.evaluate(...)` flow from
//! `policy_entity.py`. Sorting is by priority (lower = first). The
//! first matching rule fires unless it's rate-limited under its limit
//! (in which case the rule is skipped).

use sha2::{Digest, Sha256};

use super::matchers::{
    command_lacks, command_matches, target_matches, time_window_matches_now,
};
use super::rate_limit::RateLimiter;
use super::types::{
    PolicyAction, PolicyConfig, PolicyDecision, PolicyEvaluation, PolicyMatch, PolicyRule,
};

/// Hold a policy config + rate-limit state. Cloning the engine gives
/// you the same rule set with independent rate-limit counters; usually
/// you want a single engine per daemon, not per request.
pub struct PolicyEngine {
    config: PolicyConfig,
    /// Sorted ascending by priority for evaluation. Cached at construction.
    sorted_rules: Vec<PolicyRule>,
    /// SHA-256 of the canonical config serialization; used as the policy's
    /// entity_id suffix in audit trails.
    content_hash: String,
    rate_limiter: RateLimiter,
}

impl PolicyEngine {
    pub fn new(config: PolicyConfig) -> Self {
        let mut sorted_rules = config.rules.clone();
        sorted_rules.sort_by_key(|r| r.priority);
        let content_hash = canonical_hash(&config);
        Self {
            config,
            sorted_rules,
            content_hash,
            rate_limiter: RateLimiter::new(),
        }
    }

    pub fn content_hash(&self) -> &str {
        &self.content_hash
    }

    /// Returns the entity_id this policy is known by in audit
    /// constraints. Format: `policy:<sha256-first16>`.
    pub fn entity_id(&self) -> String {
        format!("policy:{}", &self.content_hash[..16])
    }

    pub fn config(&self) -> &PolicyConfig {
        &self.config
    }

    /// Evaluate `action` against this policy. First matching rule wins;
    /// if no rule matches, `default_policy` applies. Rate-limited rules
    /// are skipped *if under their limit* (the rule fires only when the
    /// limit has been exceeded).
    pub fn evaluate(&self, action: &PolicyAction<'_>) -> PolicyEvaluation {
        for rule in &self.sorted_rules {
            if !self.rule_matches(action, &rule.r#match) {
                continue;
            }
            // Rate-limit gate
            if let Some(rl) = &rule.r#match.rate_limit {
                let key = self.rate_limit_key(rule, action);
                let r = self.rate_limiter.check(&key, rl.max_count, rl.window_ms);
                if r.allowed {
                    // Under the limit — record the firing and skip (rule doesn't apply yet)
                    self.rate_limiter.record(&key);
                    continue;
                }
                // Over the limit — rule fires
            }
            let enforced = rule.decision != PolicyDecision::Deny || self.config.enforce;
            let reason = rule
                .reason
                .clone()
                .unwrap_or_else(|| format!("Matched rule: {}", rule.name));
            return PolicyEvaluation {
                decision: rule.decision,
                rule_id: Some(rule.id.clone()),
                rule_name: Some(rule.name.clone()),
                reason,
                enforced,
                constraints: vec![
                    format!("policy:{}", self.entity_id()),
                    format!("decision:{}", rule.decision.as_str()),
                    format!("rule:{}", rule.id),
                ],
            };
        }
        // No rule matched
        PolicyEvaluation {
            decision: self.config.default_policy,
            rule_id: None,
            rule_name: None,
            reason: format!("Default policy: {}", self.config.default_policy.as_str()),
            enforced: self.config.enforce
                || self.config.default_policy != PolicyDecision::Deny,
            constraints: vec![
                format!("policy:{}", self.entity_id()),
                format!("decision:{}", self.config.default_policy.as_str()),
                "rule:default".into(),
            ],
        }
    }

    fn rule_matches(&self, action: &PolicyAction<'_>, m: &PolicyMatch) -> bool {
        // Tool name match
        if let Some(tools) = &m.tools {
            if !tools.iter().any(|t| t == action.tool_name) {
                return false;
            }
        }
        // Category match
        if let Some(cats) = &m.categories {
            if !cats.iter().any(|c| c == action.category) {
                return false;
            }
        }
        // Target pattern match
        if let Some(patterns) = &m.target_patterns {
            let target = match action.target {
                Some(t) => t,
                None => return false,
            };
            if !target_matches(target, patterns, m.target_patterns_are_regex) {
                return false;
            }
        }
        // Full-command pattern match (Bash etc.)
        if let Some(patterns) = &m.command_patterns {
            let cmd = match action.full_command {
                Some(c) => c,
                None => return false,
            };
            if !command_matches(cmd, patterns, m.command_patterns_are_regex) {
                return false;
            }
        }
        // Negative command match
        if let Some(must_not) = &m.command_must_not_contain {
            let cmd = match action.full_command {
                Some(c) => c,
                None => return false,
            };
            if !command_lacks(cmd, must_not) {
                return false;
            }
        }
        // Time window
        if let Some(win) = &m.time_window {
            if !time_window_matches_now(win) {
                return false;
            }
        }
        true
    }

    fn rate_limit_key(&self, rule: &PolicyRule, action: &PolicyAction<'_>) -> String {
        if rule.r#match.tools.is_some() {
            RateLimiter::make_key(&rule.id, &format!("tool:{}", action.tool_name))
        } else if rule.r#match.categories.is_some() {
            RateLimiter::make_key(&rule.id, &format!("category:{}", action.category))
        } else {
            RateLimiter::make_key(&rule.id, "global")
        }
    }
}

/// Compute a stable SHA-256 over the canonical JSON of `config`. Used
/// as the policy's identity in audit constraints.
fn canonical_hash(config: &PolicyConfig) -> String {
    let json = serde_json::to_string(config).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(json.as_bytes());
    let digest = hasher.finalize();
    digest.iter().map(|b| format!("{:02x}", b)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::presets::get_preset;

    fn act<'a>(tool: &'a str, category: &'a str, target: Option<&'a str>) -> PolicyAction<'a> {
        PolicyAction {
            tool_name: tool,
            category,
            target,
            full_command: None,
        }
    }

    #[test]
    fn permissive_allows_everything() {
        let e = PolicyEngine::new(get_preset("permissive").unwrap().config);
        let v = e.evaluate(&act("Bash", "command", Some("rm -rf /")));
        assert_eq!(v.decision, PolicyDecision::Allow);
        assert!(v.rule_id.is_none());
    }

    #[test]
    fn safety_denies_destructive_bash() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        // non-whitelisted target — destructive deny still applies
        let action = PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some("rm -rf /home/user/data"),
            full_command: Some("rm -rf /home/user/data"),
        };
        let v = e.evaluate(&action);
        assert_eq!(v.decision, PolicyDecision::Deny);
        assert_eq!(v.rule_id.as_deref(), Some("deny-destructive-commands"));
        assert!(v.enforced);
    }

    fn bash(cmd: &'static str) -> PolicyAction<'static> {
        PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some(cmd),
            full_command: Some(cmd),
        }
    }

    #[test]
    fn safety_allows_rm_rf_in_tmp() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        for ok in ["rm -rf /tmp/foo", "rm -rf /tmp/a /tmp/b", "rm -r /tmp/x/y"] {
            let v = e.evaluate(&bash(ok));
            assert_eq!(v.decision, PolicyDecision::Allow, "expected allow for {ok:?}");
            assert_eq!(v.rule_id.as_deref(), Some("allow-rm-whitelisted-scratch"));
        }
    }

    #[test]
    fn safety_still_denies_rm_rf_outside_tmp() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        // relative path, non-tmp root, path-escape, and command-chaining all deny
        for bad in [
            "rm -rf v21out",
            "rm -rf /etc",
            "rm -rf /tmp/../etc",
            "rm -rf /tmp/x; rm -rf /",
            "rm -rf /tmp/x && rm -rf /home",
        ] {
            let v = e.evaluate(&bash(bad));
            assert_eq!(v.decision, PolicyDecision::Deny, "expected deny for {bad:?}");
            assert_eq!(v.rule_id.as_deref(), Some("deny-destructive-commands"));
        }
    }

    #[test]
    fn safety_denies_dotenv_read() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let v = e.evaluate(&act("Read", "file_read", Some("/home/u/project/.env")));
        assert_eq!(v.decision, PolicyDecision::Deny);
        assert_eq!(v.rule_id.as_deref(), Some("deny-secret-files"));
    }

    #[test]
    fn safety_warns_on_network() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let v = e.evaluate(&act("WebFetch", "network", Some("https://example.com")));
        assert_eq!(v.decision, PolicyDecision::Warn);
        assert_eq!(v.rule_id.as_deref(), Some("warn-network"));
    }

    #[test]
    fn safety_warns_on_plain_rm() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let action = PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some("rm /tmp/foo"),
            full_command: Some("rm /tmp/foo"),
        };
        let v = e.evaluate(&action);
        assert_eq!(v.decision, PolicyDecision::Warn);
        assert_eq!(v.rule_id.as_deref(), Some("warn-file-delete"));
    }

    #[test]
    fn safety_warns_on_memory_write() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let v = e.evaluate(&act(
            "Write",
            "file_write",
            Some("/home/u/.claude/projects/x/memory/MEMORY.md"),
        ));
        assert_eq!(v.decision, PolicyDecision::Warn);
        assert_eq!(v.rule_id.as_deref(), Some("warn-memory-write"));
    }

    #[test]
    fn safety_default_allows_unmatched() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let v = e.evaluate(&act("Read", "file_read", Some("/etc/hostname")));
        assert_eq!(v.decision, PolicyDecision::Allow);
        assert!(v.rule_id.is_none());
    }

    #[test]
    fn strict_denies_everything_except_listed() {
        let e = PolicyEngine::new(get_preset("strict").unwrap().config);
        let read = e.evaluate(&act("Read", "file_read", Some("/etc/hostname")));
        assert_eq!(read.decision, PolicyDecision::Allow);

        let bash = e.evaluate(&act("Bash", "command", Some("ls")));
        assert_eq!(bash.decision, PolicyDecision::Deny);
        // It's the default rule that fired
        assert!(bash.rule_id.is_none());
    }

    #[test]
    fn audit_only_returns_decisions_but_not_enforced_on_deny() {
        let e = PolicyEngine::new(get_preset("audit-only").unwrap().config);
        let action = PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some("rm -rf /"),
            full_command: Some("rm -rf /"),
        };
        let v = e.evaluate(&action);
        assert_eq!(v.decision, PolicyDecision::Deny);
        // audit-only has enforce=false, so deny is not actually enforced
        assert!(!v.enforced);
    }

    #[test]
    fn git_push_warn_only_when_no_pat() {
        let e = PolicyEngine::new(get_preset("safety").unwrap().config);

        // Without PAT — rule should fire (warn)
        let no_pat = PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some("git"),
            full_command: Some("git push origin main"),
        };
        let v = e.evaluate(&no_pat);
        assert_eq!(v.decision, PolicyDecision::Warn);
        assert_eq!(v.rule_id.as_deref(), Some("warn-git-push-no-pat"));

        // With PAT — rule should NOT fire (default allow)
        let with_pat = PolicyAction {
            tool_name: "Bash",
            category: "command",
            target: Some("git"),
            full_command: Some(
                "git push https://u:$GITHUB_PAT@github.com/dp-web4/hestia.git main",
            ),
        };
        let v = e.evaluate(&with_pat);
        assert_eq!(v.decision, PolicyDecision::Allow);
    }

    #[test]
    fn entity_id_is_stable_for_same_config() {
        let e1 = PolicyEngine::new(get_preset("safety").unwrap().config);
        let e2 = PolicyEngine::new(get_preset("safety").unwrap().config);
        assert_eq!(e1.entity_id(), e2.entity_id());
    }

    #[test]
    fn entity_id_differs_for_different_configs() {
        let e1 = PolicyEngine::new(get_preset("safety").unwrap().config);
        let e2 = PolicyEngine::new(get_preset("strict").unwrap().config);
        assert_ne!(e1.entity_id(), e2.entity_id());
    }
}
