//! The two issuance-bound rules a credential carries (PRD §7.1).
//!
//! Six independent reviews converged on one defect: `kind` is not a property of a credential.
//! A credential is not *either* consumable *or* presentable — an mTLS keypair is a consumed
//! secret whose derived half is presentable; an invitation pin is shown *by* using it. So a
//! credential carries **two orthogonal rules, both set at issuance**, and neither default
//! requires a guess:
//!
//! - **Release rule** — *who may come to hold it.* Default: only the mechanism that consumes
//!   it, in a live session for that consumption. A bearer secret is the degenerate case where
//!   the release set is a single consuming mechanism — not a different *kind* of thing.
//! - **Presentation rule** — *to whom it may be shown, what is disclosed, how many times.*
//!   Default: disclose nothing. An object with **no** presentation rule is not silently
//!   classified — presenting it **escalates to the owner**. Never silently released, never
//!   silently denied.
//!
//! **Scope of this module: the schema, not the enforcement.** These types give §7's rule a
//! place to live and `hestia_vault_set` a parameter to record. Consulting them on the release
//! and presentation paths — and backfilling the existing corpus on *both* axes before the rule
//! goes live (a release-only backfill would fire an owner escalation on every presentation of
//! every legacy credential, kimi) — are the following increments. Both new `VaultEntry` fields
//! are `Option`, `#[serde(default)]`, so every existing vault loads unchanged and behaves
//! exactly as today until enforcement lands.

use serde::{Deserialize, Serialize};

/// Axis 1 — **who may come to hold this credential.**
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum ReleaseRule {
    /// The §7.1 default: only the mechanism that actually consumes it, inside a live session
    /// for that consumption. Expresses a bearer secret too — its release set is one consumer.
    ConsumerOnly,
    /// An explicit set of principals (plugin/member ids) permitted to hold it. An empty set is
    /// deny-all — the leak-safe direction — and is a *recorded* decision, not the absence of one.
    Holders { principals: Vec<String> },
}

impl ReleaseRule {
    /// The safe default when a rule is being authored without a stated one.
    pub fn default_safe() -> Self {
        ReleaseRule::ConsumerOnly
    }
}

/// To whom a credential may be shown. **The discriminating field (§7.1):** a verifier fixed at
/// issuance needs no further rules; a verifier chosen at presentation time needs them, and the
/// credential cannot be presented without them.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum PresentationAudience {
    /// Show to no one. The safe default; a `Nobody` audience cannot be presented, and an
    /// attempt escalates to the owner rather than resolving silently either way.
    Nobody,
    /// A verifier fixed at issuance (this key, `github.com`). Needs no further audience rule.
    Fixed { verifier: String },
    /// Any verifier chosen at presentation time, drawn from a recorded set. The case that
    /// *needs* the rule — an empty set is again a recorded deny, not an absent decision.
    AnyOf { verifiers: Vec<String> },
}

/// What is disclosed on presentation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum Disclosure {
    /// Disclose nothing (default). Pairs with `Nobody`.
    Nothing,
    /// Disclose the stored secret itself — a bearer/consumable presented directly. Widening an
    /// entry to this is a privilege-widening act and is gate-governed (§5.6); the schema only
    /// records the intent.
    FullSecret,
    /// Disclose a value *derived* from the secret, never the secret (an mTLS public key, a DID
    /// proof). The common presentable case.
    Derived,
}

/// Axis 2 — **to whom it may be shown, what is disclosed, how many times.**
///
/// A `VaultEntry` holding `None` for this rule is *unrecorded*, which is NOT the same as
/// holding a `PresentationRule` that discloses nothing: `None` means "no rule authored →
/// escalate to the owner on presentation," while an authored `Nobody`/`Nothing` rule is the
/// owner's explicit decision that the object is not presentable. The distinction is exactly
/// what §9 criterion 2's presentation half tests.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PresentationRule {
    /// To whom it may be shown.
    pub audience: PresentationAudience,
    /// What is disclosed.
    pub disclose: Disclosure,
    /// How many times it may be presented. `None` = unbounded; `Some(1)` is single-use, which
    /// requires a durable nullifier set (§7.1, §9 row 2) that the enforcement increment must
    /// name — recorded here so the requirement is *expressible*, refused elsewhere until built.
    #[serde(default)]
    pub max_uses: Option<u32>,
}

impl PresentationRule {
    /// The safe default: show to no one, disclose nothing, unbounded (moot under `Nobody`).
    /// Authoring THIS is the owner deciding the object is not presentable — distinct from the
    /// `None`-on-the-entry state, which escalates.
    pub fn disclose_nothing() -> Self {
        PresentationRule {
            audience: PresentationAudience::Nobody,
            disclose: Disclosure::Nothing,
            max_uses: None,
        }
    }

    /// Can this rule be presented without escalating? Only when the audience is fixed at
    /// issuance — the whole point of the discriminating field. A presentation-time audience
    /// (`AnyOf`) is presentable, but choosing the verifier is where the presentation-path
    /// enforcement (next increment) does its work.
    pub fn is_self_sufficient(&self) -> bool {
        matches!(self.audience, PresentationAudience::Fixed { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The safe defaults are the ones §7.1 names, and they are values, not guesses.
    #[test]
    fn defaults_are_leak_safe_and_disclose_nothing() {
        assert_eq!(ReleaseRule::default_safe(), ReleaseRule::ConsumerOnly);
        let p = PresentationRule::disclose_nothing();
        assert_eq!(p.audience, PresentationAudience::Nobody);
        assert_eq!(p.disclose, Disclosure::Nothing);
        assert!(!p.is_self_sufficient(), "Nobody must not be presentable without escalation");
    }

    /// A fixed-verifier rule is self-sufficient; a presentation-time one is not "no rule" but
    /// also not free — it is the case that needs the rule.
    #[test]
    fn fixed_verifier_is_self_sufficient_any_of_is_not() {
        let fixed = PresentationRule {
            audience: PresentationAudience::Fixed { verifier: "github.com".into() },
            disclose: Disclosure::Derived,
            max_uses: None,
        };
        assert!(fixed.is_self_sufficient());
        let anyof = PresentationRule {
            audience: PresentationAudience::AnyOf { verifiers: vec!["hub-a".into()] },
            disclose: Disclosure::Derived,
            max_uses: Some(1),
        };
        assert!(!anyof.is_self_sufficient());
    }

    /// The rules round-trip through serde with a stable, self-describing shape (a `kind` tag),
    /// so a stored rule reads back as itself — the interface `hestia_vault_set` records against.
    #[test]
    fn rules_round_trip_through_serde() {
        for r in [ReleaseRule::ConsumerOnly, ReleaseRule::Holders { principals: vec!["p".into()] }] {
            let j = serde_json::to_string(&r).unwrap();
            assert_eq!(serde_json::from_str::<ReleaseRule>(&j).unwrap(), r);
        }
        let p = PresentationRule {
            audience: PresentationAudience::AnyOf { verifiers: vec!["a".into(), "b".into()] },
            disclose: Disclosure::Derived,
            max_uses: Some(1),
        };
        let j = serde_json::to_string(&p).unwrap();
        assert_eq!(serde_json::from_str::<PresentationRule>(&j).unwrap(), p);
    }
}
