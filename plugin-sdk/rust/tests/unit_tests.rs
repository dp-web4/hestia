//! Unit tests for the Rust SDK surface that doesn't require a live server.
//!
//! Full end-to-end against an MCP server is exercised in the TypeScript and
//! Python SDK test suites (both use the rmcp / mcp libraries the Rust SDK is
//! built on, so wire-level behavior is validated cross-language). These
//! tests cover the SDK-internal logic: type round-trips, error mapping from
//! the `_hestia_error` envelope, endpoint discovery, builder ergonomics.

use hestia_plugin_sdk::{
    discover_hestia_endpoint, HestiaClient, HestiaClientConfig, HestiaError, Outcome,
    PolicyDecision, PolicyResult, ToolCallSpec, DEFAULT_HESTIA_ENDPOINT,
    HESTIA_PROTOCOL_VERSION,
};
use serde_json::{json, Value};

#[test]
fn protocol_version_is_zero() {
    assert_eq!(HESTIA_PROTOCOL_VERSION, 0);
}

#[test]
fn config_builder_has_sensible_defaults() {
    let cfg = HestiaClientConfig::new("test-plugin", "test-host");
    assert_eq!(cfg.plugin_id, "test-plugin");
    assert_eq!(cfg.host_agent, "test-host");
    assert_eq!(cfg.requested_role, "citizen"); // default
    assert!(cfg.hestia_endpoint.is_none());
}

#[test]
fn config_builder_methods_chain() {
    let cfg = HestiaClientConfig::new("plug", "host")
        .with_role("administrator")
        .with_endpoint("http://example.com");
    assert_eq!(cfg.requested_role, "administrator");
    assert_eq!(cfg.hestia_endpoint.as_deref(), Some("http://example.com"));
}

#[test]
fn outcome_helpers_construct_correctly() {
    let s = Outcome::success(0.5);
    assert!(s.success);
    assert_eq!(s.magnitude, 0.5);
    assert!(s.error.is_none());

    let f = Outcome::failure(0.3, "kaboom");
    assert!(!f.success);
    assert_eq!(f.error.as_deref(), Some("kaboom"));
}

#[test]
fn tool_call_spec_builder() {
    let spec = ToolCallSpec::new("file_write").with_target("/tmp/x");
    assert_eq!(spec.tool_name, "file_write");
    assert_eq!(spec.target.as_deref(), Some("/tmp/x"));
    assert!(spec.parameters.is_empty());
    assert!(spec.atp_stake.is_none());
}

#[test]
fn endpoint_discovery_prefers_override() {
    let r = discover_hestia_endpoint(Some("http://override.test"));
    assert_eq!(r, "http://override.test");
}

#[test]
fn endpoint_discovery_falls_back_to_default() {
    // We can't reliably remove env vars in tests without affecting other
    // tests in parallel, so this only asserts the default constant is sane.
    assert!(DEFAULT_HESTIA_ENDPOINT.starts_with("http://127.0.0.1"));
}

// -------- envelope error mapping --------

fn map(code: &str, msg: &str, data: Value) -> HestiaError {
    HestiaError::from_envelope(code, msg, Some(&data))
}

#[test]
fn envelope_maps_vault_not_found() {
    let err = map("hestia.vault_not_found", "missing", json!({"name": "anthropic_key"}));
    match err {
        HestiaError::VaultNotFound { name } => assert_eq!(name, "anthropic_key"),
        other => panic!("wrong variant: {other:?}"),
    }
}

#[test]
fn envelope_maps_policy_denied() {
    let err = map(
        "hestia.policy_denied",
        "no shell access",
        json!({"policy_id": "p-42"}),
    );
    match err {
        HestiaError::PolicyDenied { reason, policy_id } => {
            assert_eq!(reason, "no shell access");
            assert_eq!(policy_id.as_deref(), Some("p-42"));
        }
        other => panic!("wrong variant: {other:?}"),
    }
}

#[test]
fn envelope_maps_action_not_found() {
    let err = map(
        "hestia.action_not_found",
        "no such action",
        json!({"action_id": "abc-123"}),
    );
    match err {
        HestiaError::ActionNotFound { action_id } => assert_eq!(action_id, "abc-123"),
        other => panic!("wrong variant: {other:?}"),
    }
}

#[test]
fn envelope_maps_vault_scope_mismatch() {
    let err = map(
        "hestia.vault_scope_mismatch",
        "wrong scope",
        json!({"name": "k", "requested_scope": ["publish", "infer"]}),
    );
    match err {
        HestiaError::VaultScopeMismatch { name, scope } => {
            assert_eq!(name, "k");
            assert_eq!(scope, vec!["publish".to_string(), "infer".to_string()]);
        }
        other => panic!("wrong variant: {other:?}"),
    }
}

#[test]
fn envelope_maps_session_expired() {
    let err = HestiaError::from_envelope("hestia.session_expired", "", None);
    assert!(matches!(err, HestiaError::SessionExpired));
}

#[test]
fn envelope_maps_unknown_to_fallback() {
    let err = map(
        "hestia.gomjabbar",
        "untyped failure",
        json!({"extra": "context"}),
    );
    match err {
        HestiaError::Unknown { code, message, data } => {
            assert_eq!(code, "hestia.gomjabbar");
            assert_eq!(message, "untyped failure");
            assert!(data.is_some());
        }
        other => panic!("wrong variant: {other:?}"),
    }
}

// -------- type serialization (wire-format compatibility with TS/Py) --------

#[test]
fn policy_result_deserializes_camelcase() {
    // The wire format uses camelCase; verify the Rust SDK deserializes it.
    let wire = json!({
        "decision": "deny",
        "reason": "shell disabled",
        "policyId": "p-42",
        "enforced": true
    });
    let parsed: PolicyResult = serde_json::from_value(wire).unwrap();
    assert_eq!(parsed.decision, PolicyDecision::Deny);
    assert_eq!(parsed.reason, "shell disabled");
    assert_eq!(parsed.policy_id.as_deref(), Some("p-42"));
    assert!(parsed.enforced);
}

#[test]
fn policy_result_defaults_enforced_when_missing() {
    let wire = json!({"decision": "allow", "reason": "ok"});
    let parsed: PolicyResult = serde_json::from_value(wire).unwrap();
    assert!(parsed.enforced);
}

#[test]
fn policy_decision_round_trip() {
    for d in [PolicyDecision::Allow, PolicyDecision::Deny, PolicyDecision::Warn] {
        let s = serde_json::to_string(&d).unwrap();
        let back: PolicyDecision = serde_json::from_str(&s).unwrap();
        assert_eq!(d, back);
    }
}

// -------- not-connected path --------

#[tokio::test]
async fn methods_reject_when_not_connected() {
    let client = HestiaClient::new(HestiaClientConfig::new("p", "h"));
    let action_result = client
        .begin_action(ToolCallSpec::new("Read"))
        .await;
    assert!(matches!(action_result, Err(HestiaError::NotConnected)));
}
