#[tokio::test]
async fn ordinary_release_must_not_follow_a_newer_hold() {
    let (_tmp, state) = fresh_rest_state(None).await;
    let path = hub_lib::ignition::ignition_path(&state.paths.root);
    std::fs::write(&path, "old").unwrap();
    witness_event_inner(&state, HubEvent::IgnitionHeld {
        tier: hub_lib::law::IgnitionTier::HostKey,
    }).await.unwrap();

    assert!(state.delete_held(&path, hub_lib::events::IgnitionRelease::LawOff));
    std::fs::write(&path, "new").unwrap();
    witness_event_inner(&state, HubEvent::IgnitionHeld {
        tier: hub_lib::law::IgnitionTier::HostKey,
    }).await.unwrap();

    assert!(state.witness_release(hub_lib::events::IgnitionRelease::LawOff, false).await.unwrap());
    assert!(path.exists());
    assert!(hub_lib::ignition::ledger_holds(
        state.ledger.lock().await.entries().iter().map(|e| &e.event)),
        "an old release must not become the latest event behind a new copy");
}
