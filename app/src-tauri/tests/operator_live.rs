//! Live end-to-end test of the operator handshake against a running daemon.
//!
//! Ignored by default (needs a daemon + an operator key on this machine):
//!     cargo test --test operator_live -- --ignored --nocapture
//!
//! This exercises the SHIPPING code path (`operator::authenticate`), not a
//! reimplementation of it — the distinction that makes it worth having.
//!
//! These tests are `#[ignore]`d, so they run only when someone asked for them
//! by name. A missing prerequisite therefore means *the check that was asked
//! for could not run*, and it FAILS — it does not print `skip:` and return
//! green. The requirement this file guards (PRD §6) exists because "nothing
//! noticed, because nothing was checking"; a check that reports success while
//! checking nothing is that same failure one layer up.

use hestia_app_lib::operator;

const DAEMON: &str = "http://127.0.0.1:7711";

fn key_path() -> Option<String> {
    operator::default_key_path().map(|p| p.to_string_lossy().to_string())
}

#[tokio::test]
#[ignore]
async fn authenticate_opens_a_session_and_the_token_reads_the_gated_api() {
    let path = key_path().expect(
        "no ~/.hestia/operator.key on this machine — this test was invoked explicitly \
         (--ignored), so an absent key is a failure to run the check, not a reason to \
         pass. Mint an operator key, or don't invoke it.",
    );

    let session = operator::authenticate(DAEMON, &path)
        .await
        .expect("operator handshake should succeed against the live daemon");
    assert!(!session.token.is_empty(), "session carried no token");
    assert!(session.lct_id.starts_with("lct:"), "unexpected operator lct");

    // The token must actually open the gate: an unauthed GET is 401.
    let client = reqwest::Client::new();
    let unauthed = client
        .get(format!("{DAEMON}/api/dashboard"))
        .send()
        .await
        .expect("daemon unreachable");
    assert_eq!(
        unauthed.status(),
        reqwest::StatusCode::UNAUTHORIZED,
        "the operator gate should reject an unauthenticated read"
    );

    // /credential fail-closed stopgap (PRD §5.6): OID4VCI issuance mints a presentation signed with the
    // OWNER's identity key, so it is now behind the operator gate. An unauthenticated POST must be 401 —
    // and 401 (not 400/422) also proves the gate preflights BEFORE body parsing (RWOA O). An empty body
    // is deliberate: if it were 422, the gate would not be dominating the side effect.
    let cred_unauthed = client
        .post(format!("{DAEMON}/credential"))
        .json(&serde_json::json!({}))
        .send()
        .await
        .expect("daemon unreachable");
    assert_eq!(
        cred_unauthed.status(),
        reqwest::StatusCode::UNAUTHORIZED,
        "ungated /credential minted an owner-signed claim; it must be operator-gated now"
    );
    // ...but /nonce grants nothing and must stay open, or the stopgap over-gated (fail-fragile, §4.1).
    let nonce_open = client
        .post(format!("{DAEMON}/nonce"))
        .send()
        .await
        .expect("daemon unreachable");
    assert_ne!(
        nonce_open.status(),
        reqwest::StatusCode::UNAUTHORIZED,
        "/nonce grants nothing and must stay open — the stopgap must not over-gate"
    );

    let authed = client
        .get(format!("{DAEMON}/api/dashboard"))
        .bearer_auth(&session.token)
        .send()
        .await
        .expect("daemon unreachable");
    assert!(authed.status().is_success(), "bearer token was rejected");

    let snapshot: serde_json::Value = authed.json().await.expect("dashboard not JSON");
    assert!(
        snapshot["society"]["chain_length"].as_u64().unwrap_or(0) > 0,
        "dashboard carried no chain"
    );

    // The derived-trust fields this app release renders must be present — this
    // is the contract that broke silently before (the app froze at v0.1.2 while
    // the daemon grew the whole T3-from-V3 surface underneath it).
    let trust = snapshot["trust"]
        .as_array()
        .and_then(|a| a.first())
        .expect("no trust grains");
    for field in [
        "legacy_level",
        "derived_temperament",
        "adjudicated_counts",
        "derivation",
    ] {
        assert!(
            trust.get(field).is_some(),
            "daemon TrustView is missing `{field}` — app/daemon contract drift"
        );
    }
}

#[tokio::test]
#[ignore]
async fn a_bad_key_is_refused() {
    let bogus = std::env::temp_dir().join("hestia-bogus-operator.key");
    std::fs::write(
        &bogus,
        serde_json::json!({
            "lct_id": "lct:web4:operator:not-authorized",
            "secret_key_hex": "11".repeat(32),
        })
        .to_string(),
    )
    .unwrap();

    let result = operator::authenticate(DAEMON, &bogus.to_string_lossy()).await;
    let _ = std::fs::remove_file(&bogus);
    let why = result.expect_err("an unauthorized key must NOT open an operator session");

    // `is_err()` alone is green when the daemon is simply down — the refusal we
    // want evidenced is the daemon's, not the network's. `authenticate` marks
    // its transport failures; anything else means the daemon answered and said no.
    assert!(
        !why.contains("request failed"),
        "daemon unreachable, so nothing was actually refused: {why}"
    );
}
