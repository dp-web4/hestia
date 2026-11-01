use hestia::storage::SqliteChainStore;

#[test]
fn route_shadow_window_keeps_sample_limit_and_pulls_matching_forward_receipts() {
    let dir = tempfile::tempdir().unwrap();
    let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x31; 32]).unwrap();
    let signer = "lct:web4:mb32:router";

    // Older successful sample, then its later transport disposition.
    let old = chain.append(
        "member_notice_route_shadow",
        serde_json::json!({
            "legacy_egress_row_id": 7,
            "legacy_address": "thor/claude-code",
            "f3_shadow": {"result":{"status":"resolved","decision":{"decision":"forward"}}}
        }),
        signer,
    ).unwrap();
    chain.append(
        "egress_forwarded",
        serde_json::json!({
            "row_id": 7,
            "carrier_lct": "carrier",
            "hub_receipt": {
                "ledger":"42",
                "recipient_lct":"11111111-1111-4111-8111-111111111111"
            }
        }),
        signer,
    ).unwrap();

    // Unrelated forwarding noise must not consume the parity sample LIMIT.
    for id in 100..105 {
        chain.append(
            "egress_forwarded",
            serde_json::json!({"row_id":id,"hub_receipt":{"ledger":id.to_string()}}),
            signer,
        ).unwrap();
    }

    // Newest sample is a refusal and has no egress row.
    let newest = chain.append(
        "member_notice_refused",
        serde_json::json!({
            "reason":"transport_binding_unmet",
            "f3_shadow":{"result":{"status":"resolved","decision":{"decision":"forward"}}}
        }),
        signer,
    ).unwrap();

    // LIMIT=1 means one parity sample, not one arbitrary chain event.
    let one = chain.read_recent_route_shadow(1).unwrap();
    assert_eq!(one.len(), 1);
    assert_eq!(one[0].hash, newest.hash);

    // LIMIT=2 returns both parity samples PLUS the matching disposition for row 7.
    let two = chain.read_recent_route_shadow(2).unwrap();
    let shadow_hashes: Vec<_> = two
        .iter()
        .filter(|e| e.event_type != "egress_forwarded")
        .map(|e| e.hash.as_str())
        .collect();
    assert_eq!(shadow_hashes.len(), 2);
    assert!(shadow_hashes.contains(&newest.hash.as_str()));
    assert!(shadow_hashes.contains(&old.hash.as_str()));

    let forwarded: Vec<_> = two
        .iter()
        .filter(|e| e.event_type == "egress_forwarded")
        .collect();
    assert_eq!(forwarded.len(), 1, "only the disposition joined to a selected sample belongs");
    assert_eq!(forwarded[0].event_data["row_id"], 7);
    assert_eq!(
        forwarded[0].event_data["hub_receipt"]["recipient_lct"],
        "11111111-1111-4111-8111-111111111111"
    );
}

#[test]
fn route_shadow_window_ignores_refusals_without_f3_shadow() {
    let dir = tempfile::tempdir().unwrap();
    let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x32; 32]).unwrap();
    let signer = "lct:web4:mb32:router";

    chain.append(
        "member_notice_refused",
        serde_json::json!({"reason":"old-pre-d2-refusal"}),
        signer,
    ).unwrap();
    let shadowed = chain.append(
        "member_notice_refused",
        serde_json::json!({
            "reason":"transport_binding_unmet",
            "f3_shadow":{"status":"unavailable","error":"test"}
        }),
        signer,
    ).unwrap();

    let rows = chain.read_recent_route_shadow(10).unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].hash, shadowed.hash);
}
