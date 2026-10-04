//! D2 migration ratchet: live legacy member_notify is observational only.
//!
//! This is deliberately a source-boundary test. The cutover point is a single
//! consequential seam in handler.rs; until a later PR explicitly changes this
//! ratchet, shadow mode may record F3 decisions but may not originate/forward
//! an F3 packet from the legacy tool.

#[test]
fn legacy_member_notify_shadow_does_not_dual_send() {
    let src = include_str!("../src/server/handler.rs");
    let start = src
        .find("async fn tool_member_notify")
        .expect("tool_member_notify exists");
    let end = src[start..]
        .find("async fn tool_egress_pending")
        .map(|n| start + n)
        .expect("tool_egress_pending follows member_notify");
    let body = &src[start..end];

    assert!(
        body.contains("member_notice_route_shadow"),
        "D2 live path must leave a paired shadow record"
    );
    assert!(
        body.contains("\"f3_shadow\""),
        "the authoritative member_notice/refusal evidence must carry the F3 shadow decision"
    );
    assert!(
        !body.contains("originate_once("),
        "D2 shadow mode must not originate an F3 packet from legacy member_notify"
    );
    assert!(
        !body.contains("\"route_forward\""),
        "D2 shadow mode must not invoke router forwarding from legacy member_notify"
    );
}
