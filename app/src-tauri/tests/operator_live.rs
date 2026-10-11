//! Live end-to-end test of the operator handshake against a running daemon.
//!
//! Ignored by default (needs a daemon + an operator key on this machine):
//!     cargo test --test operator_live -- --ignored --nocapture
//!
//! Which daemon and which key (CI: the `app-daemon contract` job in ci.yml runs these
//! against an isolated daemon built from the same commit, never the host's :7711):
//!     HESTIA_APP_LIVE_DAEMON        daemon base URL (default http://127.0.0.1:7711)
//!     HESTIA_APP_LIVE_OPERATOR_KEY  the genesis operator credential file the daemon minted
//!                                   (default: the legacy per-user location, if it exists)
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

use std::sync::Arc;

use hestia_app_lib::{handshake, identity_vault, operator};

fn daemon() -> String {
    std::env::var("HESTIA_APP_LIVE_DAEMON")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .unwrap_or_else(|| "http://127.0.0.1:7711".to_string())
}

fn operator_key_path() -> Option<std::path::PathBuf> {
    match std::env::var_os("HESTIA_APP_LIVE_OPERATOR_KEY") {
        Some(p) if !p.is_empty() => Some(std::path::PathBuf::from(p)),
        _ => operator::default_legacy_key_path(),
    }
}

fn test_vault_from_legacy(
    source: &std::path::Path,
) -> (tempfile::TempDir, Arc<identity_vault::IdentityVault>) {
    let dir = tempfile::tempdir().expect("temporary live-test vault directory");
    let copied_source = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    std::fs::copy(source, &copied_source).expect("copy legacy key into isolated test directory");
    let vault = identity_vault::migrate_plaintext_operator_key(
        &copied_source,
        &encrypted,
        "operator-live-test-only",
    )
    .expect("migrate isolated copy into a test identity vault");
    (dir, Arc::new(vault))
}

#[tokio::test]
#[ignore]
async fn authenticate_opens_a_session_and_the_token_reads_the_gated_api() {
    let path = operator_key_path().expect(
        "no operator key (HESTIA_APP_LIVE_OPERATOR_KEY unset and no ~/.hestia/operator.key) — \
         this test was invoked explicitly (--ignored), so an absent key is a failure to run \
         the check, not a reason to pass. Mint an operator key, or don't invoke it.",
    );
    let daemon = daemon();
    let daemon = daemon.as_str();

    let (_dir, vault) = test_vault_from_legacy(&path);
    let session = operator::authenticate(daemon, vault)
        .await
        .expect("operator handshake should succeed against the live daemon");
    assert!(!session.token.is_empty(), "session carried no token");
    assert!(
        session.lct_id.starts_with("lct:"),
        "unexpected operator lct"
    );

    // The token must actually open the gate: an unauthed GET is 401.
    let client = reqwest::Client::new();
    let unauthed = client
        .get(format!("{daemon}/api/dashboard"))
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
        .post(format!("{daemon}/credential"))
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
        .post(format!("{daemon}/nonce"))
        .send()
        .await
        .expect("daemon unreachable");
    assert_ne!(
        nonce_open.status(),
        reqwest::StatusCode::UNAUTHORIZED,
        "/nonce grants nothing and must stay open — the stopgap must not over-gate"
    );

    // `/api/dashboard` is a read model: each GET returns the LAST projection and queues a
    // refresh (stale-while-revalidate), and answers 503 while the first projection warms. So a
    // single GET right after activity reads the snapshot from before it. Poll, bounded, until
    // the projection carries trust; never until it carries anything at all.
    let mut snapshot = serde_json::Value::Null;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
    loop {
        let authed = client
            .get(format!("{daemon}/api/dashboard"))
            .bearer_auth(&session.token)
            .send()
            .await
            .expect("daemon unreachable");
        let status = authed.status();
        assert!(
            status.is_success() || status == reqwest::StatusCode::SERVICE_UNAVAILABLE,
            "bearer token was rejected: {status}"
        );
        if status.is_success() {
            snapshot = authed.json().await.expect("dashboard not JSON");
            if snapshot["trust"].as_array().is_some_and(|a| !a.is_empty()) {
                break;
            }
        }
        if std::time::Instant::now() > deadline {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
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
        .expect("no trust grains after 20 s of polling (CI seeds one witnessed member action \
                 with tools/app_contract_seed.py; a hand run needs a daemon with member activity)");
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
    let dir = tempfile::tempdir().unwrap();
    let bogus = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    std::fs::write(
        &bogus,
        serde_json::json!({
            "lct_id": "lct:web4:operator:not-authorized",
            "secret_key_hex": "11".repeat(32),
        })
        .to_string(),
    )
    .unwrap();

    let vault = identity_vault::migrate_plaintext_operator_key(
        &bogus,
        &encrypted,
        "operator-live-test-only",
    )
    .unwrap();
    let result = operator::authenticate(&daemon(), Arc::new(vault)).await;
    let why = result.expect_err("an unauthorized key must NOT open an operator session");

    // `is_err()` alone is green when the daemon is simply down — the refusal we
    // want evidenced is the daemon's, not the network's. `authenticate` marks
    // its transport failures; anything else means the daemon answered and said no.
    assert!(
        !why.contains("request failed"),
        "daemon unreachable, so nothing was actually refused: {why}"
    );
}

/// The handshake (web4#904) against a daemon built from the same commit: it must answer
/// `GET /api/version` without a session, and the app's own classification must read it as
/// the SAME release — same lockstep version, same operator-API generation. In CI this is the
/// contract that a daemon and an app built from one commit agree about what they are.
#[tokio::test]
#[ignore]
async fn the_daemon_handshake_matches_this_app() {
    let daemon = daemon();
    let raw = reqwest::get(format!("{daemon}/api/version"))
        .await
        .expect("daemon unreachable");
    assert_eq!(
        raw.status(),
        reqwest::StatusCode::OK,
        "/api/version must answer without a session"
    );
    let body: serde_json::Value = raw.json().await.expect("/api/version not JSON");
    for field in ["version", "build_id", "api_compat"] {
        assert!(body.get(field).is_some(), "/api/version is missing `{field}`: {body}");
    }

    let h = handshake::handshake(&daemon).await;
    assert_eq!(
        h.state,
        handshake::CompatState::Compatible,
        "a daemon from this commit must be compatible with this app: {}",
        h.message
    );
    assert_eq!(h.daemon_version.as_deref(), Some(handshake::APP_VERSION));
    assert_eq!(h.daemon_api_compat, Some(handshake::APP_API_COMPAT));
    let build = h.daemon_build_id.unwrap_or_default();
    assert!(
        !build.is_empty() && !build.starts_with("app-v"),
        "build id must be a daemon describe string, never an app-v* tag: {build:?}"
    );
}
