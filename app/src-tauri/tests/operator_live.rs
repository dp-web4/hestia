//! Live end-to-end test of the operator handshake against a running daemon.
//!
//! Ignored by default (needs a daemon + an operator key on this machine):
//!     cargo test --test operator_live -- --ignored --nocapture
//!
//! Which daemon and which key (CI: the `app-daemon contract` job in ci.yml runs these
//! against an isolated daemon built from the same commit):
//!     HESTIA_APP_LIVE_DAEMON        daemon base URL — REQUIRED, never on port 7711
//!     HESTIA_APP_LIVE_OPERATOR_KEY  the genesis operator credential file that daemon minted —
//!                                   REQUIRED for the sign-in test, never under ~/.hestia
//!
//! NEVER THE LIVE DAEMON. These tests open operator sessions and write to the daemon they reach.
//! There is no default endpoint and no default key: an unset endpoint, any endpoint on :7711
//! (the host's live daemon), or a key under ~/.hestia (the live operator credential) is a
//! REFUSAL that fails the test with a one-line reason. It is not a skip. `live_target` decides
//! this; the non-ignored `refusal_*` tests below pin it.
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

/// The port the live host daemon listens on. Nothing here may reach it.
const LIVE_PORT: u16 = 7711;

/// The explicit port of a base URL, or the scheme's default. None when it cannot be read, which
/// the caller refuses (an endpoint it cannot check is not one it may use).
fn endpoint_port(url: &str) -> Option<u16> {
    let (scheme, rest) = url.split_once("://")?;
    let authority = rest.split(['/', '?', '#']).next()?;
    let hostport = authority.rsplit_once('@').map(|(_, h)| h).unwrap_or(authority);
    let port = if let Some(v6) = hostport.strip_prefix('[') {
        v6.split_once(']')?.1.strip_prefix(':')
    } else {
        hostport.rsplit_once(':').map(|(_, p)| p)
    };
    match port {
        Some(p) => p.parse().ok(),
        None => match scheme.to_ascii_lowercase().as_str() {
            "http" => Some(80),
            "https" => Some(443),
            _ => None,
        },
    }
}

/// Decide which daemon, and (when `need_key`) which key, a live test may use. Pure: the
/// environment is passed in so the refusals are testable without touching it.
fn live_target(
    daemon_env: Option<String>,
    key_env: Option<std::ffi::OsString>,
    home: Option<std::path::PathBuf>,
    need_key: bool,
) -> Result<(String, Option<std::path::PathBuf>), String> {
    let daemon = daemon_env
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .filter(|s| !s.is_empty())
        .ok_or("refused: HESTIA_APP_LIVE_DAEMON is not set; operator_live never defaults to the live daemon (point it at an isolated one)")?;
    match endpoint_port(&daemon) {
        None => return Err(format!("refused: cannot read a port from HESTIA_APP_LIVE_DAEMON={daemon:?}")),
        Some(LIVE_PORT) => {
            return Err(format!(
                "refused: HESTIA_APP_LIVE_DAEMON={daemon} is on port {LIVE_PORT}, the live daemon's; use an isolated daemon on another port"
            ))
        }
        Some(_) => {}
    }
    if !need_key {
        return Ok((daemon, None));
    }
    let key = key_env
        .filter(|p| !p.is_empty())
        .map(std::path::PathBuf::from)
        .ok_or("refused: HESTIA_APP_LIVE_OPERATOR_KEY is not set; operator_live never defaults to the live operator key")?;
    if let Some(home) = home {
        let live = home.join(".hestia");
        // Lexically AND resolved: a relative path, a `..` or a symlink must not reach it either.
        let resolved = |p: &std::path::Path| std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
        let lexical = std::path::absolute(&key).unwrap_or_else(|_| key.clone());
        if lexical.starts_with(&live) || resolved(&key).starts_with(resolved(&live)) {
            return Err(format!(
                "refused: HESTIA_APP_LIVE_OPERATOR_KEY={} is under {}, the live operator credential; use the key the isolated daemon minted",
                key.display(),
                live.display()
            ));
        }
    }
    Ok((daemon, Some(key)))
}

fn home_dir() -> Option<std::path::PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .filter(|h| !h.is_empty())
        .map(std::path::PathBuf::from)
}

/// The configured target, or a loud failure with the one-line reason.
fn target(need_key: bool) -> (String, Option<std::path::PathBuf>) {
    live_target(
        std::env::var("HESTIA_APP_LIVE_DAEMON").ok(),
        std::env::var_os("HESTIA_APP_LIVE_OPERATOR_KEY"),
        home_dir(),
        need_key,
    )
    .unwrap_or_else(|why| panic!("{why}"))
}

fn daemon() -> String {
    target(false).0
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
    // Invoked explicitly (--ignored): an unconfigured or live target is a refusal that FAILS.
    let (daemon, path) = target(true);
    let path = path.expect("target(true) returns a key");
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

// ---- the refusals (NOT ignored: they run in every `cargo test`) ---------------------------------

fn s(v: &str) -> Option<String> {
    Some(v.to_string())
}

#[test]
fn refusal_no_endpoint_is_a_loud_refusal_not_a_default() {
    let why = live_target(None, None, None, false).unwrap_err();
    assert!(why.starts_with("refused:") && why.contains("HESTIA_APP_LIVE_DAEMON") && !why.contains('\n'), "{why}");
    assert!(live_target(s("   "), None, None, false).is_err(), "blank is unset");
}

#[test]
fn refusal_port_7711_is_refused_however_it_is_spelled() {
    for url in [
        "http://127.0.0.1:7711",
        "http://127.0.0.1:7711/",
        "http://localhost:7711/mcp",
        "http://[::1]:7711",
        "http://user@10.0.0.5:7711",
        "HTTP://host:7711?x=1",
    ] {
        let why = live_target(s(url), None, None, false).unwrap_err();
        assert!(why.contains("7711"), "{url}: {why}");
    }
    assert!(live_target(s("not a url"), None, None, false).is_err(), "an unreadable endpoint is refused");
    let (d, k) = live_target(s("http://127.0.0.1:7797/"), None, None, false).unwrap();
    assert_eq!((d.as_str(), k), ("http://127.0.0.1:7797", None));
    assert_eq!(endpoint_port("http://127.0.0.1"), Some(80));
    assert_eq!(endpoint_port("https://h"), Some(443));
}

#[test]
fn refusal_the_key_must_be_explicit_and_not_the_live_one() {
    let home = tempfile::tempdir().unwrap();
    let live = home.path().join(".hestia");
    std::fs::create_dir_all(&live).unwrap();
    std::fs::write(live.join("operator.key"), "{}").unwrap();
    let ok = s("http://127.0.0.1:7797");
    let h = Some(home.path().to_path_buf());

    let why = live_target(ok.clone(), None, h.clone(), true).unwrap_err();
    assert!(why.contains("HESTIA_APP_LIVE_OPERATOR_KEY is not set"), "{why}");

    let why = live_target(ok.clone(), Some(live.join("operator.key").into()), h.clone(), true).unwrap_err();
    assert!(why.contains("under") && why.contains(".hestia"), "{why}");

    // A `..` detour and a symlink into ~/.hestia are the same key.
    let other = home.path().join("other");
    std::fs::create_dir_all(&other).unwrap();
    let detour = other.join("..").join(".hestia").join("operator.key");
    assert!(live_target(ok.clone(), Some(detour.into()), h.clone(), true).is_err(), "`..` detour");
    #[cfg(unix)]
    {
        let link = other.join("k");
        std::os::unix::fs::symlink(live.join("operator.key"), &link).unwrap();
        assert!(live_target(ok.clone(), Some(link.into()), h.clone(), true).is_err(), "symlink");
    }

    let isolated = other.join("operator.key");
    std::fs::write(&isolated, "{}").unwrap();
    let (_, k) = live_target(ok, Some(isolated.clone().into()), h, true).unwrap();
    assert_eq!(k.as_deref(), Some(isolated.as_path()));
}
