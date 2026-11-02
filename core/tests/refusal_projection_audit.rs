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

#[tokio::test]
async fn temporary_vault_verifier_rejects_missing_refusal_at_same_generation() {
    let home = tempfile::tempdir().unwrap();
    let vault = hestia::vault::Vault::init(home.path().join("v.enc"), "p".into()).unwrap();
    let shared = hestia::server::build_state(vault, home.path(), "p").unwrap();
    let mut state = shared.lock().await;
    let (_, synthetic_vault) = pair();
    let refusal = synthetic_vault.refusals[0].clone();
    state.commit_standing_scope(|store| {
        store.refusals.push(refusal);
        store.generation += 1;
    }).unwrap();
    assert!(state.verify_standing_projection(10).unwrap().matches);
    // Simulate corruption of the in-memory projection, not a governed mutation.
    state.standing_scope.refusals.clear();
    let audit = state.verify_standing_projection(11).unwrap();
    assert_eq!(audit.runtime_generation, audit.vault_generation);
    assert!(!audit.matches, "the real vault verifier must report the missing refusal");
}
