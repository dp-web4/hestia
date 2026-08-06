//! The four named policy presets. Ports the constants and
//! `SAFETY_RULES` list from `presets.py`.

use super::types::{
    MatchScope, PolicyConfig, PolicyDecision, PolicyMatch, PolicyRule, PresetDefinition,
};

/// Build the safety-preset rule list. SIX rules: rm-whitelist allow, destructive
/// bash, file-delete warn, secret-file reads, memory-file writes, network warns.
///
/// The seventh — a git-push-without-PAT warn — was removed 2026-07-18 (tombstone
/// at the removal site below; the test is `safety_has_six_rules`). This doc comment
/// went on listing it until 2026-08-06, making it the last in-repo source still
/// telling a reader "seven"; it did, to a member that then reported seven to the
/// fleet as the law in force. Keep this list in sync with the vec, or delete it.
///
/// Shell-rule `tools:` lists carry BOTH `"Bash"` and `"Shell"`. Every other
/// layer already treats the two as one tool — `extract::target` (`"Bash" |
/// "Shell"`), `classify` (both → `"command"`), and `handler::tool_query_policy`
/// (substitutes the full command as target for both) — so listing only `"Bash"`
/// made these rules silently vacuous for any adapter whose lineage maps a shell
/// act to `"Shell"`. The gemini adapter does exactly that
/// (`run_shell_command` → `"Shell"`, plugins/gemini/hooks/before_tool.py), which
/// meant the destructive-command deny never fired for a gemini member: no rule
/// matched, so the engine returned allow. Found by nomad on the live rig
/// (2026-07-28) and reproduced against this daemon on cbp. `Shell` here is the
/// *narrow* fix — the alternative, lying in the adapter's lineage map by
/// reporting `run_shell_command` as `"Bash"`, would hide what the member
/// actually ran. See `shell_rules_judge_shell_like_bash` below.
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
            // LAW AS WRITTEN, not a rule id. This string is published to every member at
            // launch (`hestia_operating_law`), so it has to state the whole condition —
            // including the standalone requirement, which is the half that actually trips
            // people. A peer was refused a chained delete-and-recreate and, nine seconds
            // later, reached the same end another way: it never learned the rule, only
            // that one phrasing failed (dp, 2026-07-26: "'rm must be standalone' is a
            // good law").
            reason: Some(
                "rm is PERMITTED when it stands alone and every target is an absolute path \
                 under /tmp. It must be the ONLY command in the call: no &&, ;, |, newline, \
                 backticks or $(...) alongside it, and no .. in any path. Need to delete \
                 then recreate? Send them as two separate commands — chaining is what the \
                 deny catches, not the deletion."
                    .into(),
            ),
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into(), "Shell".into()]),
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
            reason: Some(
                "Destructive command blocked by the safety preset. rm is allowed ONLY \
                 standing alone against absolute /tmp paths (see the allow rule); anything \
                 chained, relative, path-escaping (..) or outside /tmp lands here. This \
                 matches where the command could EXECUTE, not where the text appears: \
                 quoting the token as data (a grep pattern, a quoted heredoc body under \
                 cat/tee, a non-expanding double-quoted string) does not trip it — but \
                 handing that same text to an interpreter (`sh -c`, `eval`, a pipe into a \
                 shell) does, and anything the parser cannot read confidently is matched in \
                 full. If the act is legitimate, appeal it with `hestia_appeal` (this \
                 decision's chain hash + your reason) rather than rephrasing — a rephrase \
                 that reaches the same resource scores 0.35, BELOW plain compliance, and \
                 teaches the society nothing. An appeal is recorded conduct that can change \
                 the law: this sentence exists because one did (adjudication 62cfdffe)."
                    .into(),
            ),
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into(), "Shell".into()]),
                target_patterns: Some(vec![r"rm\s+-".into(), r"mkfs\.".into()]),
                target_patterns_are_regex: true,
                // Judge the act, not the mention. `handler.rs` hands the whole command in
                // as `target`, so without this the rule denies `grep "rm -rf" log` — a
                // read-only search — for saying the word. Ten such denies landed on one
                // member on 2026-07-27. Falls back to raw matching whenever the shell
                // parse is uncertain; see `policy::shell`.
                target_patterns_scope: MatchScope::ExecutablePositions,
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
                tools: Some(vec!["Bash".into(), "Shell".into()]),
                // Matches "rm file" (no flags). Flag variants caught by deny rule above.
                target_patterns: Some(vec![r"rm\s+[^-]".into()]),
                target_patterns_are_regex: true,
                // Same reasoning as the deny above: a warn that fires on the word rather
                // than the act trains members to ignore warns, which is worse than silence.
                target_patterns_scope: MatchScope::ExecutablePositions,
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
            reason: Some("Memory file modification flagged - potential memory poisoning".into()),
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
            description: "Deny destructive bash, deny secret file reads, warn on network".into(),
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
    fn safety_has_six_rules() {
        // Was seven; the stale `warn-git-push-no-pat` rule was removed 2026-07-18
        // (PAT auth deprecated — SSH `git push` just works).
        let p = get_preset("safety").unwrap();
        assert_eq!(p.config.rules.len(), 6);
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

    /// A shell act must be judged by WHAT IT DOES, not by which adapter's name
    /// for the shell reached the daemon. Before 2026-07-28 the shell rules
    /// listed only `"Bash"`, so every rule missed for lineages that report
    /// `"Shell"` (gemini's `run_shell_command`) and the engine fell through to
    /// the default ALLOW — a silent hole, not a visible deny.
    ///
    /// Asserted as an EQUIVALENCE over both verdict and rule id rather than
    /// "Shell denies rm -rf": a decision-only check would pass if `Shell` were
    /// denied by some unrelated rule, and a single-command check would not
    /// notice a future rule that gets added Bash-only. This test fails if the
    /// two tool names ever diverge again, whatever the reason.
    #[test]
    fn shell_rules_judge_shell_like_bash() {
        use crate::policy::{PolicyAction, PolicyEngine};

        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        // deny (destructive), allow (scratch whitelist), warn (plain rm),
        // allow (ordinary command) — one per shell rule plus the fallthrough.
        for cmd in [
            "rm -rf /home/user/data",
            "rm -rf /tmp/scratch",
            "rm /home/user/notes.txt",
            "ls -la /home/user",
        ] {
            let judged = |tool: &'static str| {
                e.evaluate(&PolicyAction {
                    tool_name: tool,
                    category: "command",
                    target: Some(cmd),
                    full_command: Some(cmd),
                })
            };
            let bash = judged("Bash");
            let shell = judged("Shell");
            assert_eq!(
                bash.decision, shell.decision,
                "`{cmd}` judged {:?} as Bash but {:?} as Shell",
                bash.decision, shell.decision
            );
            assert_eq!(
                bash.rule_id, shell.rule_id,
                "`{cmd}` matched {:?} as Bash but {:?} as Shell",
                bash.rule_id, shell.rule_id
            );
        }
    }

    /// The hole this closes was a fallthrough-to-allow, so pin the deny itself
    /// too — if a future refactor made BOTH names allow, the equivalence test
    /// above would still pass.
    #[test]
    fn shell_lineage_destructive_command_is_denied() {
        use crate::policy::{PolicyAction, PolicyEngine};

        let e = PolicyEngine::new(get_preset("safety").unwrap().config);
        let v = e.evaluate(&PolicyAction {
            tool_name: "Shell",
            category: "command",
            target: Some("rm -rf /home/user/data"),
            full_command: Some("rm -rf /home/user/data"),
        });
        assert_eq!(v.decision, PolicyDecision::Deny);
        assert_eq!(v.rule_id.as_deref(), Some("deny-destructive-commands"));
        assert!(v.enforced);
    }
}
