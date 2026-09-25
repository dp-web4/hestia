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

use serde_json::Value;

use crate::AppState;

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
async fn request_status(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<(reqwest::StatusCode, Value), String> {
    let Some(token) = state.operator_token() else {
        return Err(needs_signin());
    };
    let url = format!("{}{}", state.daemon_url(), path);

    let first = one_shot(&url, method.clone(), &token, body.clone()).await?;
    if first.0 != reqwest::StatusCode::UNAUTHORIZED {
        return Ok(first);
    }

    // Session expired (or was revoked). Re-authenticate once from the unlocked
    // vault already held by the Rust shell, then retry exactly one time.
    let Some(vault) = state.operator_vault() else {
        state.clear_operator();
        return Err(needs_signin());
    };
    match crate::operator::authenticate(&state.daemon_url(), vault).await {
        Ok(session) => {
            let token = session.token.clone();
            state.set_operator(session);
            one_shot(&url, method, &token, body).await
        }
        Err(e) => {
            state.clear_operator();
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
