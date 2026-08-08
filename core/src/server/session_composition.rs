//! Who acted, for whom — the composition carried on an operator session (Sprint A3).
//!
//! ## What this is for
//!
//! Decision 0014 §2.1: a governed act names an **actor** (the harness that sent it) and a
//! **principal** (the human it was for). Before this, `POST /api/operator/session` accepted
//! `lct_id` alone, so the app signed as the human and the harness vanished from the record —
//! the deputy problem, in the surface built to make humans legible.
//!
//! ## Additive, not a contract break (dp, 2026-08-08)
//!
//! The first plan removed `lct_id`. dp asked what that actually buys, and the answer was
//! *almost nothing*: `lct_id` and `principal` are the same value, and deleting a field from
//! an **auth** path costs a flag day for cosmetics.
//!
//! The real concern hiding in the duplication is narrower — **what if a caller sends
//! `lct_id` and `principal` that disagree?** Resolving that with a silent precedence rule on
//! an authentication path is how these go wrong. So instead:
//!
//! > When `actor` is present, `lct_id` **must** equal `principal`. A mismatch is **refused**,
//! > not resolved.
//!
//! That keeps every existing client working, converts an ambiguity into an explicit refusal,
//! and needs no flag day. `lct_id` survives as the compatibility field, and its presence
//! *without* `actor` is a useful signal that an older client is calling.

use serde_json::Value;

/// The identities a session request carries, after validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionComposition {
    /// Whose signature authenticates the request, and whose LCT the session belongs to.
    /// Always present — this is `lct_id` under the legacy contract.
    pub principal: String,
    /// The harness that sent the request. `None` for a legacy client that predates the
    /// composition. **`None` is a fact, not a default** — it means "this caller did not say",
    /// and a reader must render it as unknown rather than as "the principal acted directly".
    pub actor: Option<String>,
}

/// Why a session request was refused before authentication was even attempted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CompositionError {
    /// No principal at all — neither `principal` nor legacy `lct_id`.
    MissingPrincipal,
    /// `actor` was supplied alongside an `lct_id` that disagrees with `principal`.
    /// Refused rather than resolved: on an auth path, a precedence rule is a silent
    /// decision about whose authority is being exercised.
    PrincipalMismatch { lct_id: String, principal: String },
    /// `actor` equals `principal` — the impersonation shape 0014 §2.1 forbids. A harness
    /// that names itself as the human it acts for has erased the distinction the field
    /// exists to record.
    ActorIsPrincipal { lct: String },
}

impl CompositionError {
    /// Operator-facing reason. Names the act and the disagreement, never a bare "invalid".
    pub fn reason(&self) -> String {
        match self {
            Self::MissingPrincipal => {
                "session request names no principal (neither `principal` nor `lct_id`)".into()
            }
            Self::PrincipalMismatch { lct_id, principal } => format!(
                "session request disagrees with itself: lct_id '{lct_id}' but principal \
                 '{principal}'. Refused rather than resolved — choosing one silently would be \
                 deciding whose authority is exercised."
            ),
            Self::ActorIsPrincipal { lct } => format!(
                "actor and principal are both '{lct}'. A harness must act as itself, never as \
                 the identity it acts for (decision 0014 §2.1)."
            ),
        }
    }
}

/// Read the composition out of a session request body, refusing contradictions.
///
/// Accepts three shapes:
/// - **legacy**: `{lct_id}` → principal, no actor;
/// - **composed**: `{actor, principal, lct_id}` where `lct_id == principal`;
/// - **composed, no legacy field**: `{actor, principal}`.
pub fn compose(body: &Value) -> Result<SessionComposition, CompositionError> {
    let s = |k: &str| {
        body.get(k)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .map(str::to_string)
    };

    let actor = s("actor");
    let principal_field = s("principal");
    let lct_id = s("lct_id");

    let principal = match (&principal_field, &lct_id) {
        (Some(p), Some(l)) if p != l => {
            return Err(CompositionError::PrincipalMismatch {
                lct_id: l.clone(),
                principal: p.clone(),
            })
        }
        (Some(p), _) => p.clone(),
        (None, Some(l)) => l.clone(),
        (None, None) => return Err(CompositionError::MissingPrincipal),
    };

    if let Some(a) = &actor {
        if a == &principal {
            return Err(CompositionError::ActorIsPrincipal { lct: a.clone() });
        }
    }

    Ok(SessionComposition { principal, actor })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_legacy_body_still_works_and_names_no_actor() {
        let c = compose(&json!({"lct_id": "lct:web4:mb32:bhuman"})).expect("legacy accepted");
        assert_eq!(c.principal, "lct:web4:mb32:bhuman");
        assert_eq!(c.actor, None, "absent actor is unknown, never 'the principal acted'");
    }

    #[test]
    fn a_composed_body_carries_both() {
        let c = compose(&json!({
            "actor": "lct:web4:mb32:bapp",
            "principal": "lct:web4:mb32:bhuman",
            "lct_id": "lct:web4:mb32:bhuman",
        }))
        .expect("composed accepted");
        assert_eq!(c.actor.as_deref(), Some("lct:web4:mb32:bapp"));
        assert_eq!(c.principal, "lct:web4:mb32:bhuman");
    }

    /// **The match requirement** (dp's call). Disagreement is refused, not resolved.
    #[test]
    fn a_disagreeing_lct_id_is_refused_not_resolved() {
        let err = compose(&json!({
            "actor": "lct:web4:mb32:bapp",
            "principal": "lct:web4:mb32:bhuman",
            "lct_id": "lct:web4:mb32:bSOMEONE-ELSE",
        }))
        .expect_err("a self-contradicting request must not authenticate");
        assert!(matches!(err, CompositionError::PrincipalMismatch { .. }));
        assert!(err.reason().contains("disagrees with itself"));
    }

    /// The impersonation guard, daemon-side — the app-side twin of
    /// `the_harness_is_not_the_principal`.
    #[test]
    fn an_actor_equal_to_the_principal_is_refused() {
        let err = compose(&json!({
            "actor": "lct:web4:mb32:bhuman",
            "principal": "lct:web4:mb32:bhuman",
        }))
        .expect_err("a harness must not name itself as its principal");
        assert!(matches!(err, CompositionError::ActorIsPrincipal { .. }));
    }

    #[test]
    fn a_body_with_no_principal_is_refused() {
        let err = compose(&json!({"actor": "lct:web4:mb32:bapp"})).expect_err("no principal");
        assert_eq!(err, CompositionError::MissingPrincipal);
    }

    /// Whitespace-only is absence, not a value — otherwise `" "` would authenticate as a
    /// principal named `" "`, and the empty-string default in the old handler did exactly
    /// that shape of thing.
    #[test]
    fn blank_fields_are_absent_not_present() {
        let err = compose(&json!({"lct_id": "   "})).expect_err("blank is not a principal");
        assert_eq!(err, CompositionError::MissingPrincipal);
    }
}
