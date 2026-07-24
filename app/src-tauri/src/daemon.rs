//! The authed daemon transport.
//!
//! Every `/api/*` route on the daemon sits behind `operator_gate` — an
//! unauthenticated GET returns 401 (verified against the live CBP daemon
//! 2026-07-24; this is why app v0.1.2 showed nothing but errors). All daemon
//! access therefore goes through here, which attaches the operator bearer
//! held in `AppState`.
//!
//! Auto-reauth: an operator session can expire while the app is open. On a
//! 401 with a known key path we re-run the handshake once and retry. The
//! webview never sees the token either way — it just sees data or an error
//! saying "sign in".

use serde_json::Value;

use crate::AppState;

fn needs_signin() -> String {
    "not signed in — open Settings and sign in with your operator key".to_string()
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

async fn request(
    state: &AppState,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    let Some(token) = state.operator_token() else {
        return Err(needs_signin());
    };
    let url = format!("{}{}", state.daemon_url(), path);

    let first = one_shot(&url, method.clone(), &token, body.clone()).await?;
    if first.0 != reqwest::StatusCode::UNAUTHORIZED {
        return finish(first);
    }

    // Session expired (or was revoked). Re-authenticate once from the key
    // path we already used, then retry exactly one time.
    let Some(key_path) = state.operator_key_path() else {
        state.clear_operator();
        return Err(needs_signin());
    };
    match crate::operator::authenticate(&state.daemon_url(), &key_path).await {
        Ok(session) => {
            let token = session.token.clone();
            state.set_operator(session);
            finish(one_shot(&url, method, &token, body).await?)
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
