//! Operator-surface authorization — the RWOA trust-gradient applied to hestia's
//! dashboard/operator surface (ratified 2026-07-12, thread `accountability-invariant`).
//!
//! The operator surface is Web4 authenticating with Web4: an operator proves
//! presence by SIGNING a challenge with their LCT (`vault::OperatorIdentity`,
//! the strong evidence — clause W), never a shared secret. This module adds the
//! rest of the gradient on top of that foundation:
//!
//! - **S (stakes):** every operator act is classified by consequence + reversibility
//!   ([`Stakes`]); the class sets the required evidence and whether V applies.
//! - **V (catastrophic veto):** irreversible acts (a secret RELEASE has no undo; an
//!   irreversible law change; an operator-set change that could lock out) are not
//!   authorized by a single signature — they require a law-defined **quorum** of
//!   distinct operator signatures ([`VaultPolicyState::irreversible_quorum`]), or
//!   escalate. Reversible acts are risk-managed on the single operator's evidence.
//! - **A (self-witnessing):** the decision carries the *evidence relied upon and the
//!   stakes assessment*, not just the act ([`AuthzOutcome::evidence_record`]), so
//!   "proceeded because reversible, on operator X's signature" is a challengeable
//!   record, not a vibe.
//!
//! O (preflight) and the challenge/response + middleware that make this reachable
//! live in the HTTP layer; this module is the pure, testable decision core.

use serde_json::json;

use crate::vault::VaultPolicyState;

/// Consequence + reversibility of an operator act (clause S). The gradient:
/// weaker evidence suffices lower down; the irreversible tail triggers V.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stakes {
    /// Reads / observability (dashboard JSON, failure feed, chain query). Low
    /// consequence, fully reversible — an authenticated operator session suffices.
    LowReversible,
    /// Config/policy edits (preset, overrides, rules, per-`(instance,role)` overlay,
    /// adding an operator, deleting a stored secret). High consequence but UNDOABLE —
    /// a single operator's strong evidence (their LCT signature) authorizes.
    HighReversible,
    /// The irreversible tail — a secret RELEASE (a read has no undo), an irreversible
    /// law change, or removing the last operator (lockout). Clause V: requires a
    /// law-defined quorum of distinct operator signatures, or escalate.
    Irreversible,
}

impl Stakes {
    /// Classify an operator-surface act by HTTP method + path (the S classification
    /// of the surface). Unknown/ambiguous operator routes default to the strictest
    /// applicable tier (fail-closed): a write is at least HighReversible.
    pub fn classify(method: &str, path: &str) -> Stakes {
        let m = method.to_ascii_uppercase();
        // Reads are low/reversible — EXCEPT releasing a secret, which is irreversible.
        if m == "GET" {
            // GET /api/vault/<name> releases a secret's value — a read with no undo.
            if path.starts_with("/api/vault/") && path.len() > "/api/vault/".len() {
                return Stakes::Irreversible;
            }
            return Stakes::LowReversible;
        }
        // Removing the last operator or an irreversible law amendment: the caller
        // marks these Irreversible explicitly via `classify_op` below; by path alone
        // a DELETE on the operator set is treated as irreversible (lockout risk).
        if (m == "DELETE" || m == "PUT") && path.starts_with("/api/operator") {
            return Stakes::Irreversible;
        }
        // All other operator writes (policy/vault mutations) are high but reversible.
        Stakes::HighReversible
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Stakes::LowReversible => "low-reversible",
            Stakes::HighReversible => "high-reversible",
            Stakes::Irreversible => "irreversible",
        }
    }

    fn is_irreversible(self) -> bool {
        matches!(self, Stakes::Irreversible)
    }
}

/// The gradient verdict on an operator act given the evidence presented (the set
/// of DISTINCT authorized-operator LCTs whose valid signatures accompany the act).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthzOutcome {
    /// Sufficient preponderance for the stakes — proceed.
    Authorized { stakes: Stakes, signers: Vec<String> },
    /// Clause V: an irreversible act without the law-required quorum. Block and
    /// escalate (collect more operator signatures, or a human gate). NOT a failure —
    /// a recorded, resumable "needs more evidence" state.
    RequiresQuorum { have: u32, need: u32, signers: Vec<String> },
    /// No admissible evidence for the act's stakes (e.g. a high-stakes act with no
    /// valid operator signature, or the surface not bootstrapped). Deny.
    Denied { stakes: Stakes, reason: String },
}

impl AuthzOutcome {
    pub fn is_authorized(&self) -> bool {
        matches!(self, AuthzOutcome::Authorized { .. })
    }

    /// The self-witnessing record (clause A): the act's stakes assessment + the
    /// evidence relied upon + the verdict. Appended to the witness chain with the
    /// act, so the gradient judgment is auditable and challengeable.
    pub fn evidence_record(&self, act: &str) -> serde_json::Value {
        match self {
            AuthzOutcome::Authorized { stakes, signers } => json!({
                "act": act, "verdict": "authorized",
                "stakes": stakes.as_str(), "evidence": "operator-lct-signature",
                "signers": signers,
            }),
            AuthzOutcome::RequiresQuorum { have, need, signers } => json!({
                "act": act, "verdict": "requires-quorum",
                "stakes": "irreversible", "evidence": "operator-lct-signature",
                "signers": signers, "have": have, "need": need,
            }),
            AuthzOutcome::Denied { stakes, reason } => json!({
                "act": act, "verdict": "denied",
                "stakes": stakes.as_str(), "reason": reason,
            }),
        }
    }
}

/// The gradient decision: given the law, an act's `stakes`, and the DISTINCT
/// authorized operators whose valid signatures accompany the act, decide.
///
/// - LowReversible: any authenticated operator (>=1 signer) proceeds.
/// - HighReversible: a single operator's strong evidence authorizes.
/// - Irreversible: requires `law.irreversible_quorum()` distinct signers (clause V);
///   fewer ⇒ RequiresQuorum (escalate).
///
/// `signers` MUST already be de-duplicated and confined to authorized operators
/// (the caller verifies each signature against `operator_access`). Empty ⇒ deny.
pub fn authorize(law: &VaultPolicyState, stakes: Stakes, signers: &[String]) -> AuthzOutcome {
    if !law.operator_access_bootstrapped() {
        return AuthzOutcome::Denied {
            stakes,
            reason: "operator surface not bootstrapped — no authorized operator".into(),
        };
    }
    let n = signers.len() as u32;
    if n == 0 {
        return AuthzOutcome::Denied {
            stakes,
            reason: "no valid operator signature".into(),
        };
    }
    if stakes.is_irreversible() {
        let need = law.irreversible_quorum();
        if n >= need {
            AuthzOutcome::Authorized { stakes, signers: signers.to_vec() }
        } else {
            AuthzOutcome::RequiresQuorum { have: n, need, signers: signers.to_vec() }
        }
    } else {
        // low/high reversible: a single authorized operator's evidence suffices
        AuthzOutcome::Authorized { stakes, signers: signers.to_vec() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vault::policy_state::OperatorIdentity;

    fn law_with_ops(n: usize, quorum: Option<u32>) -> VaultPolicyState {
        let mut law = VaultPolicyState::default();
        for i in 0..n {
            law.operator_access.push(OperatorIdentity {
                lct_id: format!("lct:web4:operator:{i}"),
                public_key_hex: "00".repeat(32),
                label: String::new(),
            });
        }
        law.operator_irreversible_quorum = quorum;
        law
    }

    #[test]
    fn stakes_classification() {
        assert_eq!(Stakes::classify("GET", "/api/dashboard"), Stakes::LowReversible);
        assert_eq!(Stakes::classify("GET", "/api/chain"), Stakes::LowReversible);
        // releasing a secret's value is a read with no undo
        assert_eq!(Stakes::classify("GET", "/api/vault/openai-key"), Stakes::Irreversible);
        // policy edits are high but reversible
        assert_eq!(Stakes::classify("PUT", "/api/policy/rule"), Stakes::HighReversible);
        assert_eq!(Stakes::classify("POST", "/api/policy/instance"), Stakes::HighReversible);
        // operator-set changes risk lockout → irreversible tail
        assert_eq!(Stakes::classify("DELETE", "/api/operator/lct:x"), Stakes::Irreversible);
    }

    #[test]
    fn reversible_acts_pass_on_single_operator() {
        let law = law_with_ops(3, Some(2));
        let one = vec!["lct:web4:operator:0".to_string()];
        assert!(authorize(&law, Stakes::LowReversible, &one).is_authorized());
        assert!(authorize(&law, Stakes::HighReversible, &one).is_authorized());
    }

    #[test]
    fn irreversible_needs_quorum_else_escalates() {
        let law = law_with_ops(3, Some(2));
        let one = vec!["lct:web4:operator:0".to_string()];
        let two = vec!["lct:web4:operator:0".to_string(), "lct:web4:operator:1".to_string()];

        // one signature on an irreversible act → RequiresQuorum (escalate), NOT authorized
        match authorize(&law, Stakes::Irreversible, &one) {
            AuthzOutcome::RequiresQuorum { have, need, .. } => {
                assert_eq!((have, need), (1, 2));
            }
            other => panic!("expected RequiresQuorum, got {other:?}"),
        }
        // quorum met → authorized
        assert!(authorize(&law, Stakes::Irreversible, &two).is_authorized());
    }

    #[test]
    fn no_signature_or_unbootstrapped_denies() {
        let bootstrapped = law_with_ops(1, None);
        assert!(matches!(
            authorize(&bootstrapped, Stakes::HighReversible, &[]),
            AuthzOutcome::Denied { .. }
        ));
        let empty = law_with_ops(0, None);
        assert!(matches!(
            authorize(&empty, Stakes::LowReversible, &["lct:web4:operator:0".into()]),
            AuthzOutcome::Denied { .. }
        ));
    }

    #[test]
    fn evidence_record_is_self_witnessing() {
        let law = law_with_ops(2, Some(2));
        let rec = authorize(&law, Stakes::HighReversible, &["lct:web4:operator:0".into()])
            .evidence_record("PUT /api/policy/rule");
        assert_eq!(rec["verdict"], "authorized");
        assert_eq!(rec["stakes"], "high-reversible");
        assert_eq!(rec["evidence"], "operator-lct-signature");
        assert_eq!(rec["signers"][0], "lct:web4:operator:0");
    }
}
