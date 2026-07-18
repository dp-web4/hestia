//! The four named policy presets. Ports the constants and
//! `SAFETY_RULES` list from `presets.py`.

use super::types::{
    PolicyConfig, PolicyDecision, PolicyMatch, PolicyRule, PresetDefinition,
};

/// Build the safety-preset rule list. Lifted verbatim from `presets.py`:
/// destructive bash, secret-file reads, memory-file writes, network warns,
/// git-push-without-PAT warn.
fn safety_rules() -> Vec<PolicyRule> {
    vec![
        // Whitelist: allow `rm` (incl. -rf) when EVERY target is an absolute
        // path under a whitelisted scratch root (/tmp). Priority 0 so it wins
        // over the destructive-deny (priority 1) via first-match. Guards:
        // the regex permits ONLY `/tmp/...` absolute args (no relative paths,
        // no other roots), and `command_must_not_contain` rejects `..`
        // (path escape) and shell metacharacters (command chaining) even if
        // the regex were fooled. Relative `rm -rf foo`, `rm -rf /tmp/../etc`,
        // `rm -rf /etc`, and `rm -rf /tmp/x; rm -rf /` all still hit the deny.
        PolicyRule {
            id: "allow-rm-whitelisted-scratch".into(),
            name: "Allow rm in whitelisted scratch dirs (/tmp)".into(),
            priority: 0,
            decision: PolicyDecision::Allow,
            reason: Some("rm confined to whitelisted scratch dir (/tmp) — permitted".into()),
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into()]),
                command_patterns: Some(vec![
                    // require >=1 flag (the `-rf` case); flagless `rm /tmp/x`
                    // still falls through to the plain-rm warn rule.
                    r"^\s*rm\s+(-{1,2}[A-Za-z]+\s+)+/tmp/[^\s;&|`$()]+(\s+/tmp/[^\s;&|`$()]+)*\s*$"
                        .into(),
                ]),
                command_patterns_are_regex: true,
                command_must_not_contain: Some(vec![
                    "..".into(),
                    ";".into(),
                    "&".into(),
                    "|".into(),
                    "`".into(),
                    "$(".into(),
                ]),
                ..Default::default()
            },
        },
        PolicyRule {
            id: "deny-destructive-commands".into(),
            name: "Block destructive shell commands".into(),
            priority: 1,
            decision: PolicyDecision::Deny,
            reason: Some("Destructive command blocked by safety preset".into()),
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into()]),
                target_patterns: Some(vec![r"rm\s+-".into(), r"mkfs\.".into()]),
                target_patterns_are_regex: true,
                ..Default::default()
            },
        },
        PolicyRule {
            id: "warn-file-delete".into(),
            name: "Warn on file deletion".into(),
            priority: 2,
            decision: PolicyDecision::Warn,
            reason: Some("File deletion flagged - use with caution".into()),
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into()]),
                // Matches "rm file" (no flags). Flag variants caught by deny rule above.
                target_patterns: Some(vec![r"rm\s+[^-]".into()]),
                target_patterns_are_regex: true,
                ..Default::default()
            },
        },
        PolicyRule {
            id: "deny-secret-files".into(),
            name: "Block reading secret/credential files".into(),
            priority: 3,
            decision: PolicyDecision::Deny,
            reason: Some("Credential/secret file access denied by safety preset".into()),
            r#match: PolicyMatch {
                categories: Some(vec!["file_read".into(), "credential_access".into()]),
                target_patterns: Some(vec![
                    // env + general secrets
                    "**/.env".into(),
                    "**/.env.*".into(),
                    "**/credentials.*".into(),
                    "**/*secret*".into(),
                    "**/token*.json".into(),
                    "**/auth*.json".into(),
                    "**/*apikey*".into(),
                    // AWS
                    "**/.aws/credentials".into(),
                    "**/.aws/config".into(),
                    // SSH
                    "**/.ssh/id_*".into(),
                    "**/.ssh/config".into(),
                    // Package managers
                    "**/.npmrc".into(),
                    "**/.pypirc".into(),
                    // DB/service
                    "**/.netrc".into(),
                    "**/.pgpass".into(),
                    "**/.my.cnf".into(),
                    // Container/k8s
                    "**/.docker/config.json".into(),
                    "**/.kube/config".into(),
                    // GPG
                    "**/.gnupg/*".into(),
                    "**/.gpg/*".into(),
                ]),
                target_patterns_are_regex: false,
                ..Default::default()
            },
        },
        PolicyRule {
            id: "warn-memory-write".into(),
            name: "Warn on agent memory file modifications".into(),
            priority: 4,
            decision: PolicyDecision::Warn,
            reason: Some(
                "Memory file modification flagged - potential memory poisoning".into(),
            ),
            r#match: PolicyMatch {
                categories: Some(vec!["file_write".into()]),
                target_patterns: Some(vec![
                    "**/MEMORY.md".into(),
                    "**/memory.md".into(),
                    "**/memory/**/*.md".into(),
                    "**/.web4/**/memory*".into(),
                    "**/.claude/**/memory*".into(),
                ]),
                ..Default::default()
            },
        },
        // (removed 2026-07-18) The `warn-git-push-no-pat` preset advised embedding a GITHUB_PAT in
        // the push URL and claimed "git push without PAT will fail on WSL". Both are stale and wrong:
        // PAT auth was deprecated long ago in favor of SSH remotes, over which a plain `git push`
        // succeeds. The warn steered agents toward a deprecated, less-secure (secret-in-URL) method.
        PolicyRule {
            id: "warn-network".into(),
            name: "Warn on network access".into(),
            priority: 10,
            decision: PolicyDecision::Warn,
            reason: Some("Network access flagged by safety preset".into()),
            r#match: PolicyMatch {
                categories: Some(vec!["network".into()]),
                ..Default::default()
            },
        },
    ]
}

/// Get a preset by name. The four built-ins:
/// `"permissive"`, `"safety"`, `"strict"`, `"audit-only"`.
pub fn get_preset(name: &str) -> Option<PresetDefinition> {
    match name {
        "permissive" => Some(PresetDefinition {
            name: "permissive".into(),
            description: "Pure observation — no rules, all actions allowed".into(),
            config: PolicyConfig {
                default_policy: PolicyDecision::Allow,
                enforce: false,
                rules: vec![],
            },
        }),
        "safety" => Some(PresetDefinition {
            name: "safety".into(),
            description:
                "Deny destructive bash, deny secret file reads, warn on network".into(),
            config: PolicyConfig {
                default_policy: PolicyDecision::Allow,
                enforce: true,
                rules: safety_rules(),
            },
        }),
        "strict" => Some(PresetDefinition {
            name: "strict".into(),
            description: "Deny everything except Read, Glob, Grep, and TodoWrite".into(),
            config: PolicyConfig {
                default_policy: PolicyDecision::Deny,
                enforce: true,
                rules: vec![PolicyRule {
                    id: "allow-read-tools".into(),
                    name: "Allow read-only tools".into(),
                    priority: 1,
                    decision: PolicyDecision::Allow,
                    reason: Some("Read-only tool permitted by strict preset".into()),
                    r#match: PolicyMatch {
                        tools: Some(vec![
                            "Read".into(),
                            "Glob".into(),
                            "Grep".into(),
                            "TodoWrite".into(),
                        ]),
                        ..Default::default()
                    },
                }],
            },
        }),
        "audit-only" => Some(PresetDefinition {
            name: "audit-only".into(),
            description:
                "Same rules as safety but enforce=false (dry-run, logs what would be blocked)"
                    .into(),
            config: PolicyConfig {
                default_policy: PolicyDecision::Allow,
                enforce: false,
                rules: safety_rules(),
            },
        }),
        _ => None,
    }
}

/// Stable list of the four built-in preset names.
pub const PRESET_NAMES: &[&str] = &["permissive", "safety", "strict", "audit-only"];

/// List all built-in presets.
pub fn list_presets() -> Vec<PresetDefinition> {
    PRESET_NAMES.iter().filter_map(|n| get_preset(n)).collect()
}

pub fn is_preset_name(name: &str) -> bool {
    PRESET_NAMES.contains(&name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_four_presets_resolve() {
        for name in PRESET_NAMES {
            let p = get_preset(name).unwrap_or_else(|| panic!("preset {name}"));
            assert_eq!(p.name, *name);
        }
    }

    #[test]
    fn permissive_is_empty_allow() {
        let p = get_preset("permissive").unwrap();
        assert_eq!(p.config.default_policy, PolicyDecision::Allow);
        assert!(!p.config.enforce);
        assert!(p.config.rules.is_empty());
    }

    #[test]
    fn safety_has_seven_rules() {
        let p = get_preset("safety").unwrap();
        assert_eq!(p.config.rules.len(), 7);
        assert!(p.config.enforce);
        assert_eq!(p.config.default_policy, PolicyDecision::Allow);
    }

    #[test]
    fn strict_denies_by_default() {
        let p = get_preset("strict").unwrap();
        assert_eq!(p.config.default_policy, PolicyDecision::Deny);
        assert!(p.config.enforce);
        assert_eq!(p.config.rules.len(), 1);
        assert_eq!(p.config.rules[0].id, "allow-read-tools");
    }

    #[test]
    fn audit_only_is_safety_without_enforce() {
        let safety = get_preset("safety").unwrap();
        let audit = get_preset("audit-only").unwrap();
        assert_eq!(safety.config.rules.len(), audit.config.rules.len());
        assert!(safety.config.enforce);
        assert!(!audit.config.enforce);
    }

    #[test]
    fn unknown_preset_returns_none() {
        assert!(get_preset("paranoid").is_none());
    }
}
