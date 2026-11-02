use hestia::storage::{SqliteChainStore, SqliteInboxStore};
use serde_json::json;

fn stores() -> (tempfile::TempDir, SqliteInboxStore, SqliteChainStore) {
    let dir = tempfile::tempdir().unwrap();
    let key = [0x6du8; 32];
    let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), key).unwrap();
    let chain = SqliteChainStore::open(dir.path().join("witness.db"), key).unwrap();
    (dir, inbox, chain)
}

fn template(witness: &str) -> serde_json::Value {
    json!({
        "witnessEntryHash": witness,
        "to_plugin_id": "bob",
        "kind": "coordination",
        "in_reply_to": null,
        "binding_verified": false,
        "recipient_liveness": "unknown",
        "recipient_liveness_evidence": null,
        "operation_id": "op-1",
        "replayed": false,
    })
}

#[test]
fn same_local_operation_is_one_queue_row_and_same_receipt() {
    let (_dir, inbox, _chain) = stores();
    let binding = r#"{"protocol":"hestia-member-notify-op-v1","to":"bob","kind":"coordination","pointer":"p"}"#;

    let first = inbox.enqueue_member_operation(
        "alice", "op-1", binding,
        "bob", "alice", "role:a", "coordination", Some("p"), "witness-1", None,
        &template("witness-1"), None,
    ).unwrap();
    let again = inbox.enqueue_member_operation(
        "alice", "op-1", binding,
        "bob", "alice", "role:a", "coordination", Some("p"), "witness-1", None,
        &template("witness-1"), None,
    ).unwrap();

    assert_eq!(first.queued_id, again.queued_id);
    assert_eq!(first.witness_hash, "witness-1");
    assert_eq!(inbox.member_pending("bob").unwrap(), 1);
    assert_eq!(first.response_json["queued_id"], again.response_json["queued_id"]);
}

#[test]
fn changed_intent_under_same_operation_is_refused_without_second_row() {
    let (_dir, inbox, _chain) = stores();
    let first_binding = r#"{"to":"bob","pointer":"p"}"#;
    inbox.enqueue_member_operation(
        "alice", "op-1", first_binding,
        "bob", "alice", "role:a", "coordination", Some("p"), "witness-1", None,
        &template("witness-1"), None,
    ).unwrap();

    let err = inbox.enqueue_member_operation(
        "alice", "op-1", r#"{"to":"bob","pointer":"DIFFERENT"}"#,
        "bob", "alice", "role:a", "coordination", Some("DIFFERENT"), "witness-2", None,
        &template("witness-2"), None,
    ).unwrap_err();
    assert!(format!("{err:#}").contains("different send intent"), "{err:#}");
    assert_eq!(inbox.member_pending("bob").unwrap(), 1);
}

#[test]
fn identical_content_with_new_operation_is_an_intentional_second_send() {
    let (_dir, inbox, _chain) = stores();
    let binding = r#"{"to":"bob","pointer":"same"}"#;
    let a = inbox.enqueue_member_operation(
        "alice", "op-a", binding,
        "bob", "alice", "role:a", "coordination", Some("same"), "witness-a", None,
        &template("witness-a"), None,
    ).unwrap();
    let b = inbox.enqueue_member_operation(
        "alice", "op-b", binding,
        "bob", "alice", "role:a", "coordination", Some("same"), "witness-b", None,
        &template("witness-b"), None,
    ).unwrap();

    assert_ne!(a.queued_id, b.queued_id);
    assert_eq!(inbox.member_pending("bob").unwrap(), 2);
}

#[test]
fn operation_namespace_is_scoped_by_authenticated_sender() {
    let (_dir, inbox, _chain) = stores();
    let binding = r#"{"to":"bob","pointer":"same"}"#;
    let a = inbox.enqueue_member_operation(
        "alice", "same-op", binding,
        "bob", "alice", "role:a", "coordination", Some("same"), "witness-a", None,
        &template("witness-a"), None,
    ).unwrap();
    let b = inbox.enqueue_member_operation(
        "carol", "same-op", binding,
        "bob", "carol", "role:c", "coordination", Some("same"), "witness-c", None,
        &template("witness-c"), None,
    ).unwrap();

    assert_ne!(a.queued_id, b.queued_id);
    assert_eq!(inbox.member_pending("bob").unwrap(), 2);
}

#[test]
fn routed_operation_freezes_transport_stamp_in_queue_transaction() {
    let (_dir, inbox, _chain) = stores();
    let binding = r#"{"to":"thor/bob","pointer":"p"}"#;
    let stamp = r#"{"mode":"relay","carrier_lct":"lct:web4:mb32:carrier","version":7}"#;
    let shadow = json!({
        "legacy_member_notice": "witness-1",
        "legacy_egress_row_id": null,
        "delivery_authority": "legacy"
    });

    let op = inbox.enqueue_egress_operation(
        "alice", "route-op", binding,
        "thor", "bob", "alice", "role:a", "coordination", Some("p"),
        "witness-1", Some(stamp), &template("witness-1"), Some(&shadow),
    ).unwrap();

    let pending = inbox.pending_egress(10).unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].id, op.queued_id.unwrap());
    assert_eq!(pending[0].transport_stamp.as_deref(), Some(stamp));

    let stored_shadow: serde_json::Value =
        serde_json::from_str(op.shadow_record_json.as_deref().unwrap()).unwrap();
    assert_eq!(stored_shadow["legacy_egress_row_id"], json!(pending[0].id));
}

#[test]
fn witness_key_recovers_first_session_fact_after_half_commit() {
    let (_dir, _inbox, chain) = stores();
    let key = "member-notify:alice:op-half";
    let first = json!({
        "from_plugin_id": "alice",
        "from_session_id": "first-session",
        "operation_binding": {"to":"bob","pointer":"p"}
    });
    let (entry, inserted) = chain.append_once(
        key, "member_notice", first.clone(), "lct:web4:sovereign"
    ).unwrap();
    assert!(inserted);

    let recovered = chain.event_by_key(key).unwrap().unwrap();
    assert_eq!(recovered.hash, entry.hash);
    assert_eq!(recovered.event_data, first);

    // Rebuilding the act under a retrying session is correctly a different fact.
    let err = chain.append_once(
        key,
        "member_notice",
        json!({
            "from_plugin_id": "alice",
            "from_session_id": "retry-session",
            "operation_binding": {"to":"bob","pointer":"p"}
        }),
        "lct:web4:sovereign",
    ).unwrap_err();
    assert!(format!("{err:#}").contains("different fact"), "{err:#}");
}
