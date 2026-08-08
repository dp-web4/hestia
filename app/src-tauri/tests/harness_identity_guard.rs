//! Sprint A guard — the app must not impersonate its principal.
//!
//! **This test is committed RED, before the implementation exists** (SPRINTS_APP.md,
//! single-builder compensation #1). kimi is out of usage and codex/GPT are one entity, so
//! there is no independent reviewer for this code. A test written *after* the
//! implementation can be shaped to fit it; one committed failing cannot.
//!
//! ## What it guards, and why it is the first thing built
//!
//! Decision 0014 §2.1, from GPT's review of #297: the draft asserted both that the app is a
//! member with its own LCT *and* that its first act is "I hold the sovereign's key and sign
//! as them". Those cannot both be the provenance model. If the app signs consequential acts
//! with the human's private key, **the harness actor disappears from the record** — which is
//! the deputy problem, reintroduced by the surface built to make humans legible.
//!
//! Measured at `a745180`, `app/src-tauri/src/operator.rs` does exactly that:
//!
//! ```text
//! let signature = hex_encode(&sk.sign(challenge.as_bytes()).to_bytes());   // principal's key
//! ... json!({ "lct_id": key.lct_id, ... })                                 // principal's LCT
//! ```
//!
//! One identity, doing duty for two. The required composition is:
//!
//! ```text
//! principal:  human-root-LCT        actor:   app-instance-LCT
//! via_device: device-LCT            office:  sovereign-role-LCT
//! authority:  occupancy / delegation / session-id
//! ```
//!
//! ## Scope, stated honestly
//!
//! These tests bind the **app side** of the composition: that a harness identity exists,
//! that it is distinct and durable, and that the session request carries actor and principal
//! as separate fields. They do **not** prove the daemon records both — that is A3/A4 and
//! needs a daemon-side counterpart. A green here is necessary, not sufficient.

use hestia_app_lib::identity;

/// The harness must exist at all. Today there is no app-instance identity anywhere in the
/// crate — the app borrows the principal's and presents it as its own.
#[test]
fn the_app_has_a_harness_identity() {
    let dir = tempfile::tempdir().expect("tempdir");
    let h = identity::harness_identity(dir.path()).expect("harness identity must be creatable");
    assert!(
        h.lct_id.starts_with("lct:"),
        "harness LCT must be an LCT id, got {:?}",
        h.lct_id
    );
}

/// **The impersonation guard.** The actor and the principal must be different identities.
/// If these ever collapse to one value, the record cannot say who acted on whose behalf, and
/// every downstream provenance claim is a restatement of the same LCT.
#[test]
fn the_harness_is_not_the_principal() {
    let dir = tempfile::tempdir().expect("tempdir");
    let harness = identity::harness_identity(dir.path()).expect("harness identity");
    let principal = "lct:web4:test:the-human-principal";

    assert_ne!(
        harness.lct_id, principal,
        "the app must act as itself, never as its principal"
    );
}

/// Continuity across stop/start (0014 §4: "anything that only exists while the app is open
/// is a bug, not a session"). A harness identity regenerated per launch would make every
/// restart a different actor, and the chain would record a stranger each time.
#[test]
fn the_harness_identity_survives_restart() {
    let dir = tempfile::tempdir().expect("tempdir");
    let first = identity::harness_identity(dir.path()).expect("first run");
    let second = identity::harness_identity(dir.path()).expect("second run — same app, restarted");

    assert_eq!(
        first.lct_id, second.lct_id,
        "the harness identity must be durable, not per-process"
    );
}

/// The session request must carry **both** identities as distinct fields. This is the wire
/// shape the daemon needs in order to record actor and principal separately; today the body
/// carries `lct_id` alone, which is the principal wearing the actor's slot.
#[test]
fn the_session_request_names_actor_and_principal_separately() {
    let dir = tempfile::tempdir().expect("tempdir");
    let harness = identity::harness_identity(dir.path()).expect("harness identity");
    let principal = "lct:web4:test:the-human-principal";

    let body = identity::session_request_body(&harness, principal, "test-challenge", "deadbeef");

    let actor = body.get("actor").and_then(|v| v.as_str());
    let princ = body.get("principal").and_then(|v| v.as_str());

    assert_eq!(actor, Some(harness.lct_id.as_str()), "actor must be the harness");
    assert_eq!(princ, Some(principal), "principal must be the human");
    assert_ne!(actor, princ, "actor and principal must not be the same identity");
}
