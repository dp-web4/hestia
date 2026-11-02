use hestia::storage::SqliteInboxStore;
use uuid::Uuid;

fn store() -> (tempfile::TempDir, SqliteInboxStore) {
    let dir = tempfile::tempdir().unwrap();
    let s = SqliteInboxStore::open(dir.path().join("inbox.db"), [0x5au8; 32]).unwrap();
    (dir, s)
}

fn notice_id(ch: char) -> String {
    std::iter::repeat(ch).take(64).collect()
}

fn packet_json(packet: Uuid, destination: &str) -> String {
    serde_json::json!({
        "protocol": "web4-route-v1",
        "packet_id": packet,
        "destination_lct": destination,
        "origin_lct": "lct:web4:mb32:origin",
        "original_kind": "coordination",
        "pointer_uri": "shared-context/forum/router-test.md",
        "content_hash": format!("sha256-pointer:{}", "a".repeat(64)),
        "hops_remaining": 8,
        "visited_routers": [],
    })
    .to_string()
}

#[test]
fn origin_operation_returns_first_packet_even_if_retry_candidate_changes() {
    let (_dir, inbox) = store();
    let first_id = Uuid::new_v4();
    let retry_candidate = Uuid::new_v4();
    let first_packet = packet_json(first_id, "lct:web4:mb32:destination");
    let retry_packet = serde_json::json!({
        "protocol": "web4-route-v1",
        "packet_id": retry_candidate,
        "destination_lct": "lct:web4:mb32:destination",
        "origin_lct": "lct:web4:mb32:origin",
        "original_kind": "coordination",
        "pointer_uri": "shared-context/forum/router-test.md",
        "content_hash": format!("sha256-pointer:{}", "a".repeat(64)),
        "hops_remaining": 3,
        "visited_routers": [],
    }).to_string();
    let binding = r#"{"protocol":"hestia-route-origin-v1","destination":"same-intent"}"#;

    let (first, inserted) = inbox.stage_router_origin(
        "lct:web4:mb32:origin",
        "op-1",
        binding,
        first_id,
        &first_packet,
        "sha256-content:first",
    ).unwrap();
    assert!(inserted);
    assert_eq!(first.packet_id, first_id);

    // Same application act, but a retry generated a different random candidate
    // and today's route config would have produced a different hop limit.
    // The first admitted packet must win byte-for-byte.
    let (again, inserted) = inbox.stage_router_origin(
        "lct:web4:mb32:origin",
        "op-1",
        binding,
        retry_candidate,
        &retry_packet,
        "sha256-content:retry",
    ).unwrap();
    assert!(!inserted);
    assert_eq!(again.packet_id, first_id);
    assert_eq!(again.packet_json, first_packet);

    let err = inbox.stage_router_origin(
        "lct:web4:mb32:origin",
        "op-1",
        r#"{"protocol":"hestia-route-origin-v1","destination":"DIFFERENT"}"#,
        Uuid::new_v4(),
        &retry_packet,
        "sha256-content:retry",
    ).unwrap_err();
    assert!(format!("{err:#}").contains("different send intent"), "{err:#}");
}

#[test]
fn same_operation_id_is_scoped_by_canonical_origin() {
    let (_dir, inbox) = store();
    let a_id = Uuid::new_v4();
    let b_id = Uuid::new_v4();
    let a_packet = packet_json(a_id, "lct:web4:mb32:destination");
    let b_packet = packet_json(b_id, "lct:web4:mb32:destination");
    let binding = r#"{"protocol":"hestia-route-origin-v1","destination":"same-intent"}"#;

    let (a, a_inserted) = inbox.stage_router_origin(
        "lct:web4:mb32:origin-a", "same-op", binding,
        a_id, &a_packet, "sha256-content:a",
    ).unwrap();
    let (b, b_inserted) = inbox.stage_router_origin(
        "lct:web4:mb32:origin-b", "same-op", binding,
        b_id, &b_packet, "sha256-content:b",
    ).unwrap();

    assert!(a_inserted && b_inserted);
    assert_ne!(a.packet_id, b.packet_id);
}

#[test]
fn packet_id_is_immutable_across_ingress_retries() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let id = notice_id('a');
    let first = packet_json(packet, "lct:web4:mb32:a");

    inbox.stage_router_packet(
        ingress,
        &id,
        packet,
        r#"{"kind":"route.forward","sealed":"opaque-a"}"#,
        &first,
        "sha256-content:first",
    ).unwrap();

    let err = inbox.stage_router_packet(
        ingress,
        &id,
        packet,
        r#"{"kind":"route.forward","sealed":"opaque-a"}"#,
        &packet_json(packet, "lct:web4:mb32:b"),
        "sha256-content:changed",
    ).unwrap_err();

    assert!(
        format!("{err:#}").contains("different bytes"),
        "{err:#}"
    );
}

#[test]
fn one_hub_receipt_cannot_change_immutable_envelope() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let id = notice_id('b');
    let p = packet_json(packet, "lct:web4:mb32:a");

    inbox.stage_router_packet(
        ingress,
        &id,
        packet,
        r#"{"kind":"route.forward","sealed":"opaque-a"}"#,
        &p,
        "sha256-content:first",
    ).unwrap();

    let err = inbox.stage_router_packet(
        ingress,
        &id,
        packet,
        r#"{"kind":"route.forward","sealed":"opaque-B"}"#,
        &p,
        "sha256-content:first",
    ).unwrap_err();

    assert!(
        format!("{err:#}").contains("different immutable content"),
        "{err:#}"
    );
}

#[test]
fn forward_decision_and_exact_outbound_bytes_are_immutable() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let id = notice_id('c');
    let p = packet_json(packet, "lct:web4:mb32:dest");

    inbox.stage_router_packet(
        ingress, &id, packet, "notice", &p, "sha256-content:p",
    ).unwrap();

    let link = Uuid::new_v4();
    let decision = r#"{"action":"forward","next_hop_lct":"r2"}"#;
    let outbound = r#"{"protocol":"web4-route-v1","packet_id":"fixed","hops_remaining":7}"#;

    inbox.record_router_forward_decision(
        packet,
        decision,
        outbound,
        "lct:web4:mb32:r2",
        link,
        "route:packet",
    ).unwrap();

    // Exact replay is accepted.
    inbox.record_router_forward_decision(
        packet,
        decision,
        outbound,
        "lct:web4:mb32:r2",
        link,
        "route:packet",
    ).unwrap();

    let state = inbox.router_packet_state(packet).unwrap().unwrap();
    assert_eq!(state.decision_json.as_deref(), Some(decision));
    assert_eq!(state.outbound_packet_json.as_deref(), Some(outbound));
    assert_eq!(state.next_hop_lct.as_deref(), Some("lct:web4:mb32:r2"));
    assert_eq!(state.forward_link_id, Some(link));
    assert_eq!(state.forward_operation_id.as_deref(), Some("route:packet"));

    let err = inbox.record_router_forward_decision(
        packet,
        decision,
        r#"{"changed":true}"#,
        "lct:web4:mb32:r2",
        link,
        "route:packet",
    ).unwrap_err();
    assert!(
        format!("{err:#}").contains("different persisted decision"),
        "{err:#}"
    );
}

#[test]
fn upstream_ack_is_not_eligible_until_packet_completion_is_witnessed() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let id = notice_id('d');
    let p = packet_json(packet, "lct:web4:mb32:child");

    inbox.stage_router_packet(
        ingress, &id, packet, "notice", &p, "sha256-content:p",
    ).unwrap();
    inbox.record_router_stage_witness(
        ingress, &id, packet, "stage-witness",
    ).unwrap();

    let local_id = inbox.accept_router_packet_local(
        packet,
        "child",
        "lct:web4:mb32:origin",
        "coordination",
        "shared-context/forum/router-test.md",
        "stage-witness",
    ).unwrap();

    // Local queue acceptance alone is not enough to ACK upstream.
    assert!(inbox.pending_router_ingress_acks(ingress).unwrap().is_empty());
    assert!(inbox.mark_router_ingress_acked(ingress, &id).is_err());

    // Retrying local acceptance is idempotent.
    assert_eq!(
        inbox.accept_router_packet_local(
            packet,
            "child",
            "lct:web4:mb32:origin",
            "coordination",
            "shared-context/forum/router-test.md",
            "stage-witness",
        ).unwrap(),
        local_id
    );

    inbox.complete_router_packet(
        packet, "delivered-local", "completion-witness",
    ).unwrap();

    assert_eq!(
        inbox.pending_router_ingress_acks(ingress).unwrap(),
        vec![id.clone()]
    );
    inbox.mark_router_ingress_acked(ingress, &id).unwrap();
    assert!(inbox.pending_router_ingress_acks(ingress).unwrap().is_empty());
}

#[test]
fn duplicate_ingress_receipts_share_one_packet_completion() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let id1 = notice_id('e');
    let id2 = notice_id('f');
    let p = packet_json(packet, "lct:web4:mb32:dest");

    for (id, stage) in [(&id1, "stage-1"), (&id2, "stage-2")] {
        inbox.stage_router_packet(
            ingress,
            id,
            packet,
            &format!(r#"{{"kind":"route.forward","receipt":"{id}"}}"#),
            &p,
            "sha256-content:p",
        ).unwrap();
        inbox.record_router_stage_witness(
            ingress, id, packet, stage,
        ).unwrap();
    }

    inbox.record_router_local_decision(
        packet,
        r#"{"action":"terminal","reason":"test"}"#,
        None,
    ).unwrap();
    inbox.complete_router_packet(
        packet, "unreachable-terminal", "done-witness",
    ).unwrap();

    let pending = inbox.pending_router_ingress_acks(ingress).unwrap();
    assert_eq!(pending, vec![id1.clone(), id2.clone()]);

    inbox.mark_router_ingress_acked(ingress, &id1).unwrap();
    assert_eq!(
        inbox.pending_router_ingress_acks(ingress).unwrap(),
        vec![id2]
    );
}


#[test]
fn refused_ingress_cannot_poison_packet_id_namespace() {
    let (_dir, inbox) = store();
    let ingress = Uuid::new_v4();
    let packet = Uuid::new_v4();
    let bad_id = notice_id('1');
    let good_id = notice_id('2');

    // An unconfigured sender claims a legitimate-looking packet id with bytes
    // that differ from what the real neighbor will later send.
    inbox.record_router_ingress_rejection(
        ingress,
        &bad_id,
        "bad-neighbor-notice",
        Some(packet),
        "refusal-witness",
    ).unwrap();

    assert_eq!(
        inbox.pending_router_rejection_acks(ingress).unwrap(),
        vec![bad_id.clone()]
    );
    assert!(
        inbox.router_packet_state(packet).unwrap().is_none(),
        "refused ingress must never claim packet_id globally"
    );
    inbox.mark_router_rejection_acked(ingress, &bad_id).unwrap();
    assert!(inbox.pending_router_rejection_acks(ingress).unwrap().is_empty());

    // The configured neighbor may now present the SAME packet id with its real
    // bytes; this must stage normally instead of colliding with the rejection.
    let good = packet_json(packet, "lct:web4:mb32:legitimate-destination");
    inbox.stage_router_packet(
        ingress,
        &good_id,
        packet,
        "configured-neighbor-notice",
        &good,
        "sha256-content:real",
    ).unwrap();
    inbox.record_router_stage_witness(
        ingress, &good_id, packet, "good-stage",
    ).unwrap();
    assert!(inbox.pending_router_ingress_acks(ingress).unwrap().is_empty());

    inbox.record_router_local_decision(
        packet,
        r#"{"action":"terminal","reason":"test"}"#,
        None,
    ).unwrap();
    inbox.complete_router_packet(
        packet, "unreachable-terminal", "completion",
    ).unwrap();

    assert_eq!(
        inbox.pending_router_ingress_acks(ingress).unwrap(),
        vec![good_id]
    );
}

