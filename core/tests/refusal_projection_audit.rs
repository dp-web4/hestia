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

#[test]
fn refusal_field_changes_are_detected_without_exposing_record_contents() {
    use hestia::server::grant_modes::Modes;
    let (_, base) = pair();
    for field in ["member", "path", "recursive", "refused_at", "refused_by", "reason", "request_id", "modes"] {
        let mut changed = base.clone();
        let row = &mut changed.refusals[0];
        match field {
            "member" => row.member = "another-member".into(),
            "path" => row.path = "/other/private".into(),
            "recursive" => row.recursive = false,
            "refused_at" => row.refused_at += 1,
            "refused_by" => row.refused_by = "peer:someone".into(),
            "reason" => row.reason = "private reason".into(),
            "request_id" => row.request_id = Some("private-request".into()),
            "modes" => row.modes = Some(Modes::READ),
            _ => unreachable!(),
        }
        assert_ne!(base.authority_digest(), changed.authority_digest(), "{field}");
        for report in [base.divergence_from(&changed), changed.divergence_from(&base)] {
            assert_eq!(report, vec!["standing refusal projection differs"], "{field}");
            assert!(!format!("{report:?}").contains("private"));
        }
    }
}

#[test]
fn overlapping_refusal_order_changes_observed_record_and_audit() {
    let (_, mut first) = pair();
    let mut second_row = first.refusals[0].clone();
    second_row.path = "/synthetic/work/child".into();
    second_row.reason = "different reason".into();
    first.refusals.push(second_row);
    let mut second = first.clone();
    second.refusals.reverse();
    assert_ne!(first.refusal_for("member", "/synthetic/work/child").unwrap().reason,
               second.refusal_for("member", "/synthetic/work/child").unwrap().reason);
    assert_ne!(first.authority_digest(), second.authority_digest());
    assert!(!first.divergence_from(&second).is_empty());
}

#[test]
fn no_refusal_preserves_the_existing_empty_store_digest() {
    use sha2::{Digest, Sha256};
    let (empty, _) = pair();
    assert_eq!(empty.authority_digest(), hex::encode(Sha256::digest(7_u64.to_be_bytes())));
    assert!(empty.divergence_from(&empty.clone()).is_empty());
}

#[test]
fn streaming_refusal_encoding_keeps_the_prototype_digest() {
    use sha2::{Digest, Sha256};
    let (_, mut store) = pair();
    store.refusals[0].reason = "large reason 🧪".repeat(40_000);
    let r = &store.refusals[0];
    // Independently reconstruct the original 44e6f2c9 whole-buffer encoding.
    let encoded = serde_json::to_vec(&(
        0_usize, &r.member, &r.path, r.recursive, r.refused_at, &r.refused_by,
        &r.reason, &r.request_id, r.modes.map(|m| m.as_letters()),
    )).unwrap();
    let row = format!("refusal\u{1f}{}", hex::encode(Sha256::digest(encoded)));
    let mut digest = Sha256::new();
    digest.update(store.generation.to_be_bytes());
    digest.update((row.len() as u64).to_be_bytes());
    digest.update(row.as_bytes());
    assert_eq!(store.authority_digest(), hex::encode(digest.finalize()));
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
