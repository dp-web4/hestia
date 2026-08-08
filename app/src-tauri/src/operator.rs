//! Operator identity for the Hestia app.
//!
//! The whole point of this module living in the Rust shell rather than the
//! webview: the operator's Ed25519 secret key and the session bearer token
//! NEVER cross the IPC boundary. The webview may submit an unlock passphrase
//! and ask "am I signed in?", but it can never read the key or the token —
//! unlike the web dashboard, which necessarily holds its credential in
//! `localStorage` where any script in the page can read it.
//!
//! Flow (matches `core/src/server/http.rs` operator_challenge/operator_session):
//!   1. POST /api/operator/challenge      -> {challenge}
//!   2. construct the five-field composition in the Rust shell
//!   3. principal, harness, and device sign one canonical transcript
//!   4. POST the composed request and receive an opaque session token
//!   5. every /api/* request carries `Authorization: Bearer <token>`
//!
//! The challenge is single-use (the daemon burns the nonce even on a failed
//! attempt), so a re-auth always fetches a fresh one.

use std::path::PathBuf;
use std::sync::Arc;

use serde::Serialize;

use crate::{identity, identity_vault::IdentityVault};

/// What the UI is allowed to know about the operator session: whether it
/// exists and which LCT it belongs to. Never the token.
#[derive(Debug, Clone, Serialize, Default)]
pub struct OperatorStatus {
    pub signed_in: bool,
    pub lct_id: Option<String>,
    /// Encrypted identity-vault path. Path only — never contents.
    pub vault_path: Option<String>,
    /// Whether the named vault currently exists.
    pub vault_exists: bool,
    /// Whether a legacy plaintext credential can be imported into the vault.
    pub migration_available: bool,
}

/// The live session. Held in `AppState` behind a mutex; token is private to
/// this crate and only ever attached to outbound daemon requests.
#[derive(Clone)]
pub struct OperatorSession {
    pub lct_id: String,
    pub token: String,
    pub vault: Arc<IdentityVault>,
}

impl std::fmt::Debug for OperatorSession {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OperatorSession")
            .field("lct_id", &self.lct_id)
            .field("token", &"<redacted>")
            .field("vault_path", &self.vault.path())
            .finish()
    }
}

/// Default credential location — the same path the daemon writes and the
/// dashboard's one-click login reads. Checked so the UI can offer a plain
/// "Sign in" button instead of a file picker (dp 2026-07-24: "I'd rather
/// just click login").
pub fn default_legacy_key_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from)?;
    let p = home.join(".hestia").join("operator.key");
    p.exists().then_some(p)
}

/// Run the full challenge -> sign -> session handshake against `daemon_url`.
/// Returns the session on success. All identity/authority fields are covered by
/// the same principal, harness, and device signatures.
pub async fn authenticate(
    daemon_url: &str,
    vault: Arc<IdentityVault>,
) -> Result<OperatorSession, String> {
    let client = reqwest::Client::new();
    let challenge: serde_json::Value = client
        .post(format!("{daemon_url}/api/operator/challenge"))
        .send()
        .await
        .map_err(|e| format!("challenge request failed: {e}"))?
        .json()
        .await
        .map_err(|e| format!("challenge response not JSON: {e}"))?;
    let challenge = challenge
        .get("challenge")
        .and_then(|v| v.as_str())
        .ok_or("daemon returned no challenge")?
        .to_string();

    let request = identity::session_request_body(&vault, &challenge)?;

    let resp = client
        .post(format!("{daemon_url}/api/operator/session"))
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("session request failed: {e}"))?;

    let status = resp.status();
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("session response not JSON: {e}"))?;
    if !status.is_success() {
        let why = body
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("operator authentication failed");
        return Err(why.to_string());
    }
    let token = body
        .get("token")
        .and_then(|v| v.as_str())
        .ok_or("session response carried no token")?
        .to_string();

    Ok(OperatorSession {
        lct_id: vault.principal_lct().to_string(),
        token,
        vault,
    })
}
