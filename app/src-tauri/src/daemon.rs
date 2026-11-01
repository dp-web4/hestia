//! The authed daemon transport.
//!
//! Every `/api/*` route on the daemon sits behind `operator_gate` — an
//! unauthenticated GET returns 401 (verified against the live CBP daemon
//! 2026-07-24; this is why app v0.1.2 showed nothing but errors). All daemon
//! access therefore goes through here, which attaches the operator bearer
//! held in `AppState`.
//!
//! Auto-reauth: an operator session can expire while the app is open. On a
//! 401, the still-unlocked identity vault re-runs the handshake once and
//! retries. The webview never sees the token or credential either way — it
//! just sees data or an error saying "sign in".
//!
//! ONE ENGINE, SEVERAL VIEWS. The daemon on this machine also serves its own
//! web dashboard, and the CLI drives the same state; the app is not a second
//! engine but a second view onto the first. Every act therefore races the other
//! views, and the daemon — not any view — is the arbiter. `send` flattens a
//! refusal to a sentence, which is right for a caller that can only report it;
//! `send_checked` keeps the status, because "someone else already did this"
//! (409) is an outcome of the world and must not be rendered as a failure of
//! the operator's action.
//!
//! ONE ENDPOINT PER OPERATION. Every operation captures the selected [`Endpoint`] once, and
//! the version probe, the bearer, any re-auth and the request itself all use that capture. If
//! Settings selects another daemon while the operation is awaiting, it stops before it sends
//! anything else: the probe that cleared daemon A never authorizes a request to daemon B, and
//! a session minted by A is never published as B's (Codex, hestia#1280).

use serde_json::Value;

use crate::handshake::{self, Handshake};
use crate::{AppState, Endpoint};

/// The handshake for `ep`, from cache or a fresh `GET /api/version`.
pub async fn current_handshake(state: &AppState, ep: &Endpoint) -> Handshake {
    if let Some(h) = state.cached_handshake(&ep.url) {
        return h;
    }
    let h = handshake::handshake(&ep.url).await;
    state.store_handshake(&ep.url, &h);
    h
}

/// Refuse before the first operator route if the daemon does not speak this app's API.
///
/// Every route goes through here, so an incompatible pairing reads as ONE clear sentence
/// ("incompatible daemon: ...") on every page, instead of each page's first route failing
/// in its own way (a 404 on a renamed route, "bad response" on a reshaped body).
///
/// The answer is about `ep` only, and only while `ep` is still selected: a probe that returns
/// after Settings moved on is refused rather than lent to the new endpoint.
pub async fn ensure_compatible(state: &AppState, ep: &Endpoint) -> Result<Handshake, String> {
    let h = current_handshake(state, ep).await;
    still_selected(state, ep)?;
    if h.state.usable() {
        Ok(h)
    } else {
        Err(h.message)
    }
}

/// Refuse to go on if Settings selected another daemon since `ep` was captured.
pub fn still_selected(state: &AppState, ep: &Endpoint) -> Result<(), String> {
    if state.is_current(ep) {
        Ok(())
    } else {
        Err(endpoint_changed(ep))
    }
}

fn endpoint_changed(ep: &Endpoint) -> String {
    format!(
        "daemon changed in Settings while this was in flight; nothing more was sent to {} — retry against the new daemon",
        ep.url
    )
}

fn needs_signin() -> String {
    "not signed in — open Settings and unlock your identity vault".to_string()
}

/// GET a daemon path, authed. `path` starts with `/`.
pub async fn get(state: &AppState, path: &str) -> Result<Value, String> {
    request(state, reqwest::Method::GET, path, None).await
}

/// POST/PUT/DELETE a daemon path with an optional JSON body, authed.
pub async fn send(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    request(state, method, path, body).await
}

/// A refusal the caller needs to tell apart from other refusals.
#[derive(Debug)]
pub enum Refused {
    /// The daemon says this act is already done — another view won the race.
    /// Single-shot acts answer 409 (`DecideError::AlreadyDecided`), and a view
    /// that renders this as an error teaches the operator that their click
    /// failed when in fact the intent was already settled.
    Conflict(String),
    Other(String),
}

impl std::fmt::Display for Refused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Refused::Conflict(m) | Refused::Other(m) => f.write_str(m),
        }
    }
}

/// `send`, but a 409 comes back as [`Refused::Conflict`] rather than a bare
/// string. For acts that race the daemon's other views.
pub async fn send_checked(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, Refused> {
    match request_status(state, method, path, body).await {
        Ok((status, value)) if status.is_success() => Ok(value),
        Ok((status, value)) => {
            let why = value
                .get("error")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .unwrap_or_else(|| format!("daemon returned {status}"));
            if status == reqwest::StatusCode::CONFLICT {
                Err(Refused::Conflict(why))
            } else {
                Err(Refused::Other(why))
            }
        }
        Err(e) => Err(Refused::Other(e)),
    }
}

async fn request(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    finish(request_status(state, method, path, body).await?)
}

/// The shared transport: auth, one re-auth on 401, and the raw status handed
/// back. `request` flattens it; `send_checked` reads it.
pub(crate) async fn request_status(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<(reqwest::StatusCode, Value), String> {
    let ep = state.endpoint();
    ensure_compatible(state, &ep).await?;
    let url = format!("{}{}", ep.url, path);

    if let Some(token) = state.operator_token_for(&ep) {
        let first = one_shot(&url, method.clone(), &token, body.clone()).await?;
        if first.0 != reqwest::StatusCode::UNAUTHORIZED {
            return Ok(first);
        }
        // Sessions live in daemon memory: a 401 on a session that worked is often a daemon
        // that was restarted or replaced. Re-probe it rather than trust the cached answer.
        state.forget_handshake();
        ensure_compatible(state, &ep).await?;
    }

    // No session for this endpoint: it expired, was revoked, or was minted by the daemon
    // selected before this one. Re-authenticate once from the unlocked vault already held by
    // the Rust shell, against the captured endpoint, then send exactly once more.
    let Some(vault) = state.operator_vault() else {
        return Err(needs_signin());
    };
    match crate::operator::authenticate(&ep.url, vault).await {
        Ok(session) => {
            let token = session.token.clone();
            if !state.set_operator_for(&ep, session) {
                return Err(endpoint_changed(&ep));
            }
            one_shot(&url, method, &token, body).await
        }
        Err(e) => {
            // A failure against a daemon that is no longer selected says nothing about the
            // session for the one that is.
            if state.is_current(&ep) {
                state.clear_operator();
            }
            Err(format!("operator session expired and re-auth failed: {e}"))
        }
    }
}

async fn one_shot(
    url: &str,
    method: reqwest::Method,
    token: &str,
    body: Option<Value>,
) -> Result<(reqwest::StatusCode, Value), String> {
    let client = reqwest::Client::new();
    let mut req = client.request(method, url).bearer_auth(token);
    if let Some(b) = body {
        req = req.json(&b);
    }
    let resp = req
        .send()
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?;
    let status = resp.status();
    // Some daemon routes answer 200 with an empty body; treat that as null
    // rather than a parse error.
    let text = resp
        .text()
        .await
        .map_err(|e| format!("bad response: {e}"))?;
    let value = if text.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str(&text).map_err(|e| format!("bad response: {e}"))?
    };
    Ok((status, value))
}

fn finish((status, value): (reqwest::StatusCode, Value)) -> Result<Value, String> {
    if status.is_success() {
        return Ok(value);
    }
    let why = value
        .get("error")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .unwrap_or_else(|| format!("daemon returned {status}"));
    Err(why)
}

/// The endpoint-binding races, against real sockets. Each daemon is a bare TCP listener the
/// test answers by hand, so a test can hold a response, change Settings, then release it.
/// Every token and key here is synthetic; the responders verify nothing.
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::time::Duration;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::{TcpListener, TcpStream};

    async fn daemon() -> (TcpListener, String) {
        let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", l.local_addr().unwrap());
        (l, url)
    }

    /// The next request on `l`: accept, then read the head and any `content-length` body.
    async fn next(l: &TcpListener) -> (TcpStream, String) {
        let (mut s, _) = tokio::time::timeout(Duration::from_secs(5), l.accept())
            .await
            .expect("no request arrived")
            .unwrap();
        let mut buf = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let n = s.read(&mut chunk).await.unwrap();
            buf.extend_from_slice(&chunk[..n]);
            let text = String::from_utf8_lossy(&buf).to_string();
            if let Some(end) = text.find("\r\n\r\n") {
                let len = text[..end]
                    .lines()
                    .find_map(|l| {
                        l.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|v| v.trim().parse::<usize>().unwrap())
                    })
                    .unwrap_or(0);
                if buf.len() >= end + 4 + len || n == 0 {
                    return (s, text);
                }
            } else if n == 0 {
                return (s, text);
            }
        }
    }

    async fn answer(mut s: TcpStream, status: &str, body: &str) {
        let resp = format!(
            "HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
            body.len()
        );
        s.write_all(resp.as_bytes()).await.unwrap();
    }

    fn version(compat: u32) -> String {
        serde_json::json!({"version": handshake::APP_VERSION, "build_id": "test", "api_compat": compat})
            .to_string()
    }

    /// Nothing reaches `l` within a beat.
    async fn silent(l: &TcpListener) -> bool {
        tokio::time::timeout(Duration::from_millis(300), l.accept())
            .await
            .is_err()
    }

    fn vault() -> (tempfile::TempDir, Arc<crate::identity_vault::IdentityVault>) {
        let dir = tempfile::tempdir().unwrap();
        let legacy = dir.path().join("operator.key");
        let seed: String = [0x5au8; 32].iter().map(|b| format!("{b:02x}")).collect();
        std::fs::write(
            &legacy,
            serde_json::json!({"lct_id": "lct:web4:human:test-principal", "secret_key_hex": seed})
                .to_string(),
        )
        .unwrap();
        let v = crate::identity_vault::migrate_plaintext_operator_key(
            &legacy,
            dir.path().join("identity.vault"),
            "correct horse battery staple",
        )
        .unwrap();
        (dir, Arc::new(v))
    }

    /// Signed in to `url` with `token`, as a completed sign-in would leave it.
    fn signed_in(url: &str, token: &str) -> (tempfile::TempDir, Arc<AppState>) {
        let state = Arc::new(AppState::new());
        state.set_daemon_url(url);
        let (dir, vault) = vault();
        let session = crate::operator::OperatorSession {
            lct_id: vault.principal_lct().to_string(),
            token: token.to_string(),
            vault,
        };
        assert!(state.set_operator_for(&state.endpoint(), session));
        (dir, state)
    }

    fn compatible_cached(state: &AppState, url: &str) {
        let h = handshake::classify(
            &handshake::Probe::Answered {
                status: 200,
                body: version(handshake::APP_API_COMPAT),
            },
            handshake::APP_VERSION,
            handshake::APP_API_COMPAT,
        );
        state.store_handshake(url, &h);
    }

    /// The operation's outcome; a regression that sends the route somewhere unanswered fails
    /// here instead of hanging the suite.
    async fn outcome(call: tokio::task::JoinHandle<Result<Value, String>>) -> Result<Value, String> {
        tokio::time::timeout(Duration::from_secs(5), call)
            .await
            .expect("the operation did not finish: a request went to a daemon nobody answers")
            .unwrap()
    }

    fn grant(state: &Arc<AppState>) -> tokio::task::JoinHandle<Result<Value, String>> {
        let s = Arc::clone(state);
        tokio::spawn(async move {
            send(&s, reqwest::Method::POST, "/api/scope/grant", Some(serde_json::json!({}))).await
        })
    }

    /// Codex's repro (hestia#1280 P1): A's compatible answer arrives after Settings chose B.
    /// Before: B's first request was the POST, with A's bearer. Now neither daemon gets it.
    #[tokio::test]
    async fn a_probe_answered_after_a_switch_sends_the_route_nowhere() {
        let (a, a_url) = daemon().await;
        let (b, b_url) = daemon().await;
        let (_dir, state) = signed_in(&a_url, "token-a");
        let call = grant(&state);

        let (probe, req) = next(&a).await;
        assert!(req.starts_with("GET /api/version "), "{req}");
        state.set_daemon_url(&b_url);
        answer(probe, "200 OK", &version(handshake::APP_API_COMPAT)).await;

        let err = outcome(call).await.unwrap_err();
        assert!(err.contains("daemon changed in Settings"), "{err}");
        assert!(silent(&b).await, "unprobed B was sent a request");
        assert!(silent(&a).await, "A was sent the route after it was deselected");
    }

    /// A token minted by A is never sent to B: B is probed, then signed in to, then routed.
    #[tokio::test]
    async fn a_session_from_the_old_daemon_is_not_sent_to_the_new_one() {
        let (_a, a_url) = daemon().await;
        let (b, b_url) = daemon().await;
        let (_dir, state) = signed_in(&a_url, "token-a");
        state.set_daemon_url(&b_url);
        let call = grant(&state);

        let (s, req) = next(&b).await;
        assert!(req.starts_with("GET /api/version "), "{req}");
        answer(s, "200 OK", &version(handshake::APP_API_COMPAT)).await;
        let (s, req) = next(&b).await;
        assert!(
            req.starts_with("POST /api/operator/challenge "),
            "B got the route before a session: {req}"
        );
        answer(s, "200 OK", r#"{"challenge":"c-b"}"#).await;
        let (s, req) = next(&b).await;
        assert!(req.starts_with("POST /api/operator/session "), "{req}");
        answer(s, "200 OK", r#"{"token":"token-b"}"#).await;
        let (s, req) = next(&b).await;
        assert!(req.starts_with("POST /api/scope/grant "), "{req}");
        assert!(req.to_ascii_lowercase().contains("authorization: bearer token-b"), "{req}");
        assert!(!req.contains("token-a"), "A's bearer reached B: {req}");
        answer(s, "200 OK", "{}").await;

        outcome(call).await.unwrap();
        assert_eq!(state.operator_token_for(&state.endpoint()).as_deref(), Some("token-b"));
    }

    /// A 401, then a switch while re-auth is in flight: the session A mints is discarded,
    /// not published as B's, and the route is not retried anywhere.
    #[tokio::test]
    async fn a_reauth_finished_after_a_switch_is_discarded() {
        let (a, a_url) = daemon().await;
        let (b, b_url) = daemon().await;
        let (_dir, state) = signed_in(&a_url, "token-a");
        compatible_cached(&state, &a_url);
        let call = grant(&state);

        let (s, req) = next(&a).await;
        assert!(req.starts_with("POST /api/scope/grant "), "{req}");
        answer(s, "401 Unauthorized", r#"{"error":"session expired"}"#).await;
        let (s, req) = next(&a).await;
        assert!(req.starts_with("GET /api/version "), "a 401 must re-probe: {req}");
        answer(s, "200 OK", &version(handshake::APP_API_COMPAT)).await;
        let (s, req) = next(&a).await;
        assert!(req.starts_with("POST /api/operator/challenge "), "{req}");
        answer(s, "200 OK", r#"{"challenge":"c-a"}"#).await;
        let (s, req) = next(&a).await;
        assert!(req.starts_with("POST /api/operator/session "), "{req}");
        state.set_daemon_url(&b_url);
        answer(s, "200 OK", r#"{"token":"late-token-a"}"#).await;

        let err = outcome(call).await.unwrap_err();
        assert!(err.contains("daemon changed in Settings"), "{err}");
        assert_eq!(
            state.operator_token_for(&state.endpoint()),
            None,
            "A's session was published as B's"
        );
        assert!(silent(&a).await, "the route was retried on deselected A");
        assert!(silent(&b).await, "B was sent a request");
    }

    /// A 401 is read as "maybe a different daemon now": the cached answer is dropped and a
    /// replacement that speaks another API generation is refused before any re-auth.
    #[tokio::test]
    async fn a_401_re_probes_and_an_incompatible_replacement_is_not_signed_in_to() {
        let (a, a_url) = daemon().await;
        let (_dir, state) = signed_in(&a_url, "token-a");
        compatible_cached(&state, &a_url);
        let call = grant(&state);

        let (s, _) = next(&a).await;
        answer(s, "401 Unauthorized", "{}").await;
        let (s, req) = next(&a).await;
        assert!(req.starts_with("GET /api/version "), "{req}");
        answer(s, "200 OK", &version(handshake::APP_API_COMPAT + 1)).await;

        let err = outcome(call).await.unwrap_err();
        assert!(err.contains("incompatible"), "{err}");
        assert!(silent(&a).await, "a sign-in reached an incompatible daemon");
    }

    /// Control: an incompatible daemon is refused before the first operator route.
    #[tokio::test]
    async fn an_incompatible_daemon_is_refused_before_the_route() {
        let (a, a_url) = daemon().await;
        let (_dir, state) = signed_in(&a_url, "token-a");
        let call = grant(&state);
        let (s, req) = next(&a).await;
        assert!(req.starts_with("GET /api/version "), "{req}");
        answer(s, "200 OK", &version(handshake::APP_API_COMPAT + 1)).await;
        assert!(outcome(call).await.unwrap_err().contains("incompatible"));
        assert!(silent(&a).await);
    }

    #[test]
    fn re_saving_the_same_url_keeps_the_session_and_a_new_url_unbinds_it() {
        let (_dir, state) = signed_in("http://127.0.0.1:1", "t");
        let ep = state.endpoint();
        state.set_daemon_url("http://127.0.0.1:1");
        assert!(state.is_current(&ep));
        assert_eq!(state.operator_token_for(&ep).as_deref(), Some("t"));
        state.set_daemon_url("http://127.0.0.1:2");
        assert!(!state.is_current(&ep));
        assert_eq!(state.operator_token_for(&state.endpoint()), None);
    }
}
