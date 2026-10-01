//! ONE decision witness for every verdict — one-gate stage A (docs/one-gate-convergence-plan.md).
//!
//! `hestia_witness_decision` was the deny/warn recorder (Sprint E). The common orchestrator needs
//! the same door for `allow`, and needs it to be receipt-validated: a gate may permit a
//! consequential act only once its decision witness is COMMITTED, and "the RPC returned
//! something" is not a commit — every tool `Err`, including a failed chain append, reaches the
//! wire as a successful MCP result carrying `_hestia_error` (handler.rs `call_tool`).
//!
//! This module holds the parts of that contract that are decisions rather than plumbing, so they
//! are testable without a daemon:
//!
//! - **Where each verdict lands.** `warn`/`deny` stay `policy_decision`, unchanged. `allow` is
//!   its own event type, [`ALLOW_EVENT`]. It must NOT be a `policy_decision`: that type is in
//!   `DERIVATION_GOVERNANCE_EVENT_TYPES`, the sparse half of derivation's window that "must not
//!   be crowded out", and allow volume is outcome volume. Several readers also take every
//!   `policy_decision` row as a refusal (`governed_acts`, the retry match, calib_export's gate
//!   negatives, the sibling-role count). An allow written there would move trust scores and push
//!   real denies out of the window.
//! - **What each verdict charges.** `allow` charges nothing, as the daemon's own gate charges
//!   nothing on allow (`risk_magnitude` 0.0 in `tool_query_policy`) and as scope attestation
//!   argues ("letting each one count would let a member farm trust"). `warn`/`deny` keep their
//!   existing Unclassified 0.2/0.5.
//! - **One verdict, one row.** When the gate names an action the daemon itself already ruled
//!   and witnessed (the society-safety path: `begin_action` → `query_policy` writes its own
//!   `policy_decision` and its own Conduct charge), the gate's witness of the SAME verdict for
//!   the SAME member is that row. The reply hands back its hash; nothing is appended and nothing
//!   is charged a second time.

use serde_json::Value;

/// Event type for a witnessed `allow`. Reserved: `hestia_request_witness` cannot forge it.
pub const ALLOW_EVENT: &str = "policy_allow";
/// Event type for a witnessed `warn`/`deny` — the pre-existing type, unchanged.
pub const DECISION_EVENT: &str = "policy_decision";
/// Bound on the caller-reported core digest stored on the row (a full sha256 is 64).
pub const CORE_DIGEST_MAX: usize = 128;

/// The three final verdicts a gate can reach. Anything else is refused before any append.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Allow,
    Warn,
    Deny,
}

impl Verdict {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "allow" => Some(Self::Allow),
            "warn" => Some(Self::Warn),
            "deny" => Some(Self::Deny),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Warn => "warn",
            Self::Deny => "deny",
        }
    }

    pub fn event_type(self) -> &'static str {
        match self {
            Self::Allow => ALLOW_EVENT,
            Self::Warn | Self::Deny => DECISION_EVENT,
        }
    }

    /// The gate-risk charge for this verdict. `None` = no reputation delta at all.
    pub fn risk_magnitude(self) -> Option<f64> {
        match self {
            Self::Allow => None,
            Self::Warn => Some(0.2),
            Self::Deny => Some(0.5),
        }
    }
}

/// The daemon's own witness of its own verdict on one in-flight action, kept on the action so a
/// later decision witness for the same act can be answered with it instead of a duplicate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnDecisionWitness {
    pub decision: String,
    pub entry_hash: String,
    /// The member the daemon attributed the row to (from the action's session).
    pub plugin_id: String,
}

/// The existing row that already witnesses this verdict, if any.
///
/// Same member AND same verdict, or nothing. A different verdict (a warn-rollout seat recording
/// `warn` for a daemon `deny`, a local deny after a daemon warn) is a different decision and gets
/// its own row; a different member is never answered with someone else's record.
pub fn existing_witness<'a>(
    own: Option<&'a OwnDecisionWitness>,
    plugin_id: &str,
    verdict: Verdict,
) -> Option<&'a str> {
    own.filter(|w| w.plugin_id == plugin_id && w.decision == verdict.as_str())
        .map(|w| w.entry_hash.as_str())
}

/// `core_digest` as stored: a string, bounded. Absent or non-string → not stored.
///
/// Lenient on purpose: the deployed refusal shims already send this key (as a hex digest or the
/// literal "unknown"), and refusing their deny records over its format would lose the deny.
pub fn bounded_core_digest(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str)
        .map(|s| s.chars().take(CORE_DIGEST_MAX).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn every_verdict_parses_and_nothing_else_does() {
        for (s, v) in [("allow", Verdict::Allow), ("warn", Verdict::Warn), ("deny", Verdict::Deny)] {
            assert_eq!(Verdict::parse(s), Some(v));
            assert_eq!(v.as_str(), s);
        }
        for bad in ["", "Allow", "escalate", "no-verdict", "permit", "deny "] {
            assert_eq!(Verdict::parse(bad), None, "{bad:?} must be refused");
        }
    }

    #[test]
    fn allow_is_never_a_policy_decision_row() {
        assert_eq!(Verdict::Allow.event_type(), ALLOW_EVENT);
        assert_ne!(ALLOW_EVENT, DECISION_EVENT);
        assert_eq!(Verdict::Warn.event_type(), DECISION_EVENT);
        assert_eq!(Verdict::Deny.event_type(), DECISION_EVENT);
    }

    /// The window guard, stated as a test: an allow row must not enter derivation's sparse
    /// governance half, or allow volume crowds the denies it exists to keep.
    #[test]
    fn allow_rows_stay_out_of_the_governance_window() {
        assert!(!crate::derivation::DERIVATION_GOVERNANCE_EVENT_TYPES.contains(&ALLOW_EVENT));
        assert!(!crate::derivation::DERIVATION_EVENT_TYPES.contains(&ALLOW_EVENT));
        assert!(crate::derivation::DERIVATION_GOVERNANCE_EVENT_TYPES.contains(&DECISION_EVENT));
    }

    #[test]
    fn allow_charges_nothing_and_refusals_keep_their_weights() {
        assert_eq!(Verdict::Allow.risk_magnitude(), None);
        assert_eq!(Verdict::Warn.risk_magnitude(), Some(0.2));
        assert_eq!(Verdict::Deny.risk_magnitude(), Some(0.5));
    }

    #[test]
    fn an_existing_witness_answers_only_the_same_member_and_verdict() {
        let own = OwnDecisionWitness {
            decision: "deny".into(),
            entry_hash: "h1".into(),
            plugin_id: "codex".into(),
        };
        assert_eq!(existing_witness(Some(&own), "codex", Verdict::Deny), Some("h1"));
        assert_eq!(existing_witness(Some(&own), "codex", Verdict::Warn), None, "other verdict");
        assert_eq!(existing_witness(Some(&own), "kimi-code", Verdict::Deny), None, "other member");
        assert_eq!(existing_witness(None, "codex", Verdict::Deny), None);
    }

    #[test]
    fn core_digest_is_bounded_and_never_refused() {
        assert_eq!(bounded_core_digest(Some(&json!("unknown"))), Some("unknown".into()));
        let long = "a".repeat(500);
        assert_eq!(bounded_core_digest(Some(&json!(long))).unwrap().len(), CORE_DIGEST_MAX);
        assert_eq!(bounded_core_digest(Some(&json!(null))), None);
        assert_eq!(bounded_core_digest(Some(&json!(7))), None);
        assert_eq!(bounded_core_digest(None), None);
    }
}
