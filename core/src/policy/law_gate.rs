//! LawGate — the third fold input: hub law evaluated by the canonical engine.
//!
//! Consolidation (thread `hestia-role-orchestration`, 2026-07-10): hestia's gate
//! and the hub daemon are "the same engine by design" (dp), but hestia/core
//! historically ran only its own `PolicyEngine` while the hub evaluated hub
//! law with the canonical `web4-policy` crate — two implementations meant to
//! agree, drifting apart is the seam an immune system can't afford (CBP's
//! dup-flag, confirmed in `hub-to-cbp-two-engines-confirmed-…-2026-07-09.md`).
//!
//! This module closes the seam *structurally*: law semantics evaluate in the ONE
//! canonical crate everywhere. hestia keeps what is genuinely machine-local
//! (matchers, presets, rate limits — `PolicyEngine`); hub-law norms evaluate
//! via `web4_policy::Law` and fold in as a third strictest-wins input:
//!
//! ```text
//! fold_strictest(base_rules, role_overlay, law_eval)
//! ```
//!
//! Law is hub-published *content*, never a runtime dependency: the gate reads a LOCAL
//! copy at `$HESTIA_HOME/law/hub-law.yaml`, refreshed out-of-band (the hub is
//! the authority for what the law *says*; the member machine holds the text it
//! enforces). Absent file ⇒ no third input (exactly today's behavior). Present
//! but INVALID file ⇒ fail-closed: every evaluation denies with a reason naming
//! the parse failure — a member whose law text is corrupt must not silently run
//! law-free (fail-closed+warn default, dp-ratified).
//!
//! Escalation: the canonical `Decision::Escalate` maps to a local **Deny** with
//! an `escalation queued:` reason (gate profile §5 — the immediate effect of an
//! escalate is a blocking deny-with-reason; the sovereign-review queue is a
//! follow-on, never the hot path).

use std::path::Path;

use web4_policy::{Decision, Law, R6Request};

use super::types::{PolicyAction, PolicyDecision, PolicyEvaluation};

/// Filename (under `$HESTIA_HOME/law/`) for the machine-local hub-law copy.
pub const LAW_FILE: &str = "hub-law.yaml";

/// The hub-law gate. Construct via [`LawGate::load`].
#[derive(Debug)]
pub enum LawGate {
    /// A valid law is loaded; evaluations run through `web4_policy::Law`.
    Active { law: Law, sha256: String },
    /// A law file EXISTS but failed to parse/validate. Fail-closed: everything
    /// denies until the operator fixes or removes the file.
    Invalid { error: String },
}

impl LawGate {
    /// Load the machine-local hub law from `<home>/law/hub-law.yaml`.
    ///
    /// - No file → `None` (no third fold input; pre-consolidation behavior).
    /// - Valid file → `Some(Active)`.
    /// - Unreadable/invalid file → `Some(Invalid)` — present-but-broken law
    ///   fails CLOSED, never open.
    pub fn load(home: &Path) -> Option<Self> {
        let path = home.join("law").join(LAW_FILE);
        if !path.exists() {
            return None;
        }
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(e) => {
                return Some(LawGate::Invalid {
                    error: format!("unreadable law file {}: {e}", path.display()),
                });
            }
        };
        match Law::parse_and_validate(&text) {
            Ok(law) => Some(LawGate::Active {
                law,
                sha256: Law::<web4_policy::NoExtension>::sha256_hex_of(&text),
            }),
            Err(e) => Some(LawGate::Invalid {
                error: format!("invalid law file {}: {e}", path.display()),
            }),
        }
    }

    /// Content hash of the loaded law (`None` when invalid). Surfaced so the
    /// operator/dashboard can compare against the hub's published law head.
    pub fn law_sha256(&self) -> Option<&str> {
        match self {
            LawGate::Active { sha256, .. } => Some(sha256),
            LawGate::Invalid { .. } => None,
        }
    }

    /// Evaluate a tool action, in a role, against hub law. Returns a
    /// `PolicyEvaluation` suitable for `fold_strictest` alongside the base and
    /// role-overlay evaluations.
    pub fn evaluate(&self, pa: &PolicyAction<'_>, role: &str) -> PolicyEvaluation {
        let (decision, rule_id, rule_name, reason) = match self {
            LawGate::Invalid { error } => (
                PolicyDecision::Deny,
                Some("law:invalid".to_string()),
                Some("Hub law unparseable".to_string()),
                format!("hub law present but invalid (fail-closed): {error}"),
            ),
            LawGate::Active { law, .. } => {
                let req = R6Request {
                    role: role.to_string(),
                    action: pa.tool_name.to_string(),
                    payload: law_payload(pa),
                    resource: Default::default(),
                };
                let outcome = law.evaluate_outcome(&req);
                let norm = outcome.winning_norm.clone();
                let (decision, reason) = match outcome.decision {
                    Decision::Escalate => (
                        PolicyDecision::Deny,
                        format!(
                            "escalation queued: hub law escalates to '{}' (norm {})",
                            outcome.escalate_to.as_deref().unwrap_or("sovereign"),
                            norm.as_deref().unwrap_or("escalation-trigger"),
                        ),
                    ),
                    d => {
                        let mapped = map_decision(d);
                        let reason = match (&mapped, &norm) {
                            (PolicyDecision::Allow, None) => "hub law: no norm objects".to_string(),
                            (_, Some(id)) => format!("hub law norm '{id}'"),
                            (_, None) => "hub law default".to_string(),
                        };
                        (mapped, reason)
                    }
                };
                (
                    decision,
                    norm.map(|id| format!("law:{id}")),
                    Some("Hub law".to_string()),
                    reason,
                )
            }
        };
        let constraints = vec![
            "policy:hub-law".to_string(),
            format!("decision:{}", decision.as_str()),
            format!("rule:{}", rule_id.as_deref().unwrap_or("law:default")),
        ];
        PolicyEvaluation {
            decision,
            rule_id,
            rule_name,
            reason,
            enforced: true,
            constraints,
        }
    }
}

/// Map the canonical crate's non-escalate verdicts onto hestia's local enum
/// (Escalate is handled at the call site — it becomes Deny-with-queued-reason).
/// Exhaustive on purpose: a future canonical variant is a compile error here,
/// never a silent allow (fail-closed forward-compat, mirroring the gate
/// profile's client rule).
fn map_decision(d: Decision) -> PolicyDecision {
    match d {
        Decision::Allow => PolicyDecision::Allow,
        Decision::Warn => PolicyDecision::Warn,
        Decision::Deny | Decision::Escalate => PolicyDecision::Deny,
    }
}

/// Project the tool action into the R6Request payload so law norms can select
/// on `r6.request.payload.target`, `.category`, `.full_command` (and
/// `r6.request.action` = tool name, `r6.role` = constellation role).
fn law_payload(pa: &PolicyAction<'_>) -> serde_yaml::Value {
    let mut map = serde_yaml::Mapping::new();
    map.insert("category".into(), pa.category.into());
    if let Some(t) = pa.target {
        map.insert("target".into(), t.into());
    }
    if let Some(c) = pa.full_command {
        map.insert("full_command".into(), c.into());
    }
    serde_yaml::Value::Mapping(map)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::fold_strictest;

    fn pa<'a>() -> PolicyAction<'a> {
        PolicyAction {
            tool_name: "Bash",
            category: "execute",
            target: Some("rm"),
            full_command: Some("rm -rf /tmp/x"),
        }
    }

    fn write_law(dir: &Path, yaml: &str) {
        let law_dir = dir.join("law");
        std::fs::create_dir_all(&law_dir).unwrap();
        std::fs::write(law_dir.join(LAW_FILE), yaml).unwrap();
    }

    #[test]
    fn absent_law_is_none() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(LawGate::load(tmp.path()).is_none());
    }

    #[test]
    fn invalid_law_fails_closed() {
        let tmp = tempfile::tempdir().unwrap();
        write_law(tmp.path(), ": not [ valid yaml");
        let gate = LawGate::load(tmp.path()).expect("present file must load as a gate");
        let eval = gate.evaluate(&pa(), "role:constellation:foreign-kimi");
        assert_eq!(eval.decision, PolicyDecision::Deny);
        assert!(eval.enforced);
        assert!(eval.reason.contains("fail-closed"));
        assert!(gate.law_sha256().is_none());
    }

    #[test]
    fn deny_norm_fires_and_folds_strictest() {
        let tmp = tempfile::tempdir().unwrap();
        write_law(
            tmp.path(),
            r#"
version: "1.0.0"
norms:
  - id: no-bash-for-foreign
    selector: r6.request.action
    operator: "=="
    value: Bash
    decision: deny
    priority: 10
"#,
        );
        let gate = match LawGate::load(tmp.path()) {
            Some(g @ LawGate::Active { .. }) => g,
            other => panic!("expected Active law gate, got {other:?}"),
        };
        let law_eval = gate.evaluate(&pa(), "role:constellation:foreign-kimi");
        assert_eq!(law_eval.decision, PolicyDecision::Deny);
        assert_eq!(law_eval.rule_id.as_deref(), Some("law:no-bash-for-foreign"));

        // Base allows; law denies; strictest wins — the third input tightens.
        let base = PolicyEvaluation {
            decision: PolicyDecision::Allow,
            rule_id: None,
            rule_name: None,
            reason: "base allow".into(),
            enforced: true,
            constraints: vec![],
        };
        let folded = fold_strictest(base, law_eval);
        assert_eq!(folded.decision, PolicyDecision::Deny);
    }

    #[test]
    fn escalate_maps_to_deny_with_queued_reason() {
        let tmp = tempfile::tempdir().unwrap();
        write_law(
            tmp.path(),
            r#"
version: "1.0.0"
norms:
  - id: escalate-bash
    selector: r6.request.action
    operator: "=="
    value: Bash
    decision: escalate
    priority: 10
"#,
        );
        let gate = LawGate::load(tmp.path()).unwrap();
        let eval = gate.evaluate(&pa(), "role:any");
        assert_eq!(eval.decision, PolicyDecision::Deny);
        assert!(eval.reason.starts_with("escalation queued:"));
    }

    #[test]
    fn no_norm_fires_maps_allow() {
        let tmp = tempfile::tempdir().unwrap();
        write_law(
            tmp.path(),
            r#"
version: "1.0.0"
norms:
  - id: irrelevant
    selector: r6.request.action
    operator: "=="
    value: SomethingElse
    decision: deny
"#,
        );
        let gate = LawGate::load(tmp.path()).unwrap();
        let eval = gate.evaluate(&pa(), "role:any");
        assert_eq!(eval.decision, PolicyDecision::Allow);
        assert!(gate.law_sha256().is_some());
    }
}
