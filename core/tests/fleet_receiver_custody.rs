//! F3 receiver custody regressions.
//!
//! These are database-level crash-boundary tests. Hub's own suite proves fetch/ACK
//! tombstones; these prove Hestia does not duplicate or lose local acceptance when
//! the crash happens on its side of the seam.

use hestia::storage::{SqliteChainStore, SqliteInboxStore};
use uuid::Uuid;

fn notice_id(byte: char) -> String {
    std::iter::repeat(byte).take(64).collect()
}

#[test]
fn receipt_retry_reuses_witness_and_member_enqueue() {
    let dir = tempfile::tempdir().unwrap();
    let key = [9u8; 32];
    let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), key).unwrap();
    let chain = SqliteChainStore::open(dir.path().join("witness.db"), key).unwrap();

    let connection = Uuid::new_v4();
    let hub = Uuid::new_v4();
    let hub_member = Uuid::new_v4();
    let id = notice_id('a');
    let notice = r#"{"pair_id":"00000000-0000-0000-0000-000000000001","from":"00000000-0000-0000-0000-000000000002","sealed":"opaque","kind":"coordination","pointer_uri":"thread:x","queued_at":"2026-10-04T00:00:00Z"}"#;

    inbox.stage_hub_receipt(
        connection, hub, hub_member, "lct:web4:mb32:child", "being",
        &id, notice, "coordination", Some("thread:x"),
    ).unwrap();

    // First process lands the witness, then "crashes" before inbox acceptance.
    let (first, inserted) = chain.append_once(
        &format!("hub-receive:{hub}:{hub_member}:{id}"),
        "hub.notice.received",
        serde_json::json!({"notice_id": id, "destination_lct": "lct:web4:mb32:child"}),
        "lct:web4:mb32:router",
    ).unwrap();
    assert!(inserted);

    // Retry returns the exact same witness row, not a second chain event.
    let (retry, inserted) = chain.append_once(
        &format!("hub-receive:{hub}:{hub_member}:{id}"),
        "hub.notice.received",
        serde_json::json!({"this body is ignored on idempotent replay": true}),
        "lct:web4:mb32:router",
    ).unwrap();
    assert!(!inserted);
    assert_eq!(retry.hash, first.hash);
    assert_eq!(retry.chain_position, first.chain_position);

    let local = inbox.accept_hub_receipt(connection, &id, &first.hash).unwrap();

    // Second crash edge: local acceptance landed, Hub ACK response was lost.
    // Retrying acceptance returns the same local notice id.
    assert_eq!(
        inbox.accept_hub_receipt(connection, &id, &first.hash).unwrap(),
        local
    );
    assert_eq!(inbox.pending_hub_receipt_acks(connection).unwrap(), vec![id.clone()]);

    let state = inbox.hub_receipt_custody(connection, &id).unwrap().unwrap();
    assert_eq!(state.member_notice_id, Some(local));
    assert_eq!(state.witness_hash.as_deref(), Some(first.hash.as_str()));
    assert!(state.hub_acked_at.is_none());

    inbox.mark_hub_receipt_acked(connection, &id).unwrap();
    assert!(inbox.pending_hub_receipt_acks(connection).unwrap().is_empty());
    assert!(inbox.hub_receipt_custody(connection, &id).unwrap().unwrap().hub_acked_at.is_some());
}

#[test]
fn same_hub_notice_id_cannot_change_under_custody() {
    let dir = tempfile::tempdir().unwrap();
    let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [3u8; 32]).unwrap();
    let connection = Uuid::new_v4();
    let hub = Uuid::new_v4();
    let member = Uuid::new_v4();
    let id = notice_id('b');

    inbox.stage_hub_receipt(
        connection, hub, member, "lct:web4:mb32:child", "being",
        &id, r#"{"kind":"coordination","pointer_uri":"a"}"#,
        "coordination", Some("a"),
    ).unwrap();

    let err = inbox.stage_hub_receipt(
        connection, hub, member, "lct:web4:mb32:child", "being",
        &id, r#"{"kind":"coordination","pointer_uri":"DIFFERENT"}"#,
        "coordination", Some("DIFFERENT"),
    ).unwrap_err();
    assert!(format!("{err:#}").contains("different immutable content"));
}

#[test]
fn ack_watermark_requires_local_acceptance() {
    let dir = tempfile::tempdir().unwrap();
    let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [5u8; 32]).unwrap();
    let connection = Uuid::new_v4();
    let id = notice_id('c');
    inbox.stage_hub_receipt(
        connection, Uuid::new_v4(), Uuid::new_v4(),
        "lct:web4:mb32:child", "being", &id,
        r#"{"kind":"coordination"}"#, "coordination", None,
    ).unwrap();

    let err = inbox.mark_hub_receipt_acked(connection, &id).unwrap_err();
    assert!(format!("{err:#}").contains("before local acceptance"));
}
