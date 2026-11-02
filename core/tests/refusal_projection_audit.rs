//! Synthetic regression: projection verification must see durable ask-policy drift.
use hestia::server::standing_scope::{StandingRefusal, StandingScopeStore};

fn pair() -> (StandingScopeStore, StandingScopeStore) {
    let mut runtime = StandingScopeStore::default();
    runtime.generation = 7;
    let mut vault = runtime.clone();
    vault.refusals.push(StandingRefusal {
        member: "member".into(),
        path: "/synthetic/work".into(),
        recursive: true,
        refused_at: 1,
        refused_by: "operator".into(),
        reason: "synthetic".into(),
        request_id: None,
        modes: None,
    });
    assert!(runtime.refusal_for("member", "/synthetic/work/child").is_none());
    assert!(vault.refusal_for("member", "/synthetic/work/child").is_some());
    (runtime, vault)
}

#[test]
fn missing_refusal_changes_projection_digest() {
    let (runtime, vault) = pair();
    assert_ne!(runtime.authority_digest(), vault.authority_digest());
}

#[test]
fn missing_refusal_is_reported_as_projection_divergence() {
    let (runtime, vault) = pair();
    assert!(!runtime.divergence_from(&vault).is_empty());
    assert!(!vault.divergence_from(&runtime).is_empty());
}
