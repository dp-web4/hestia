//! Operator identity for the Hestia app.
//!
//! The whole point of this module living in the Rust shell rather than the
//! webview: the operator's Ed25519 secret key and the session bearer token
//! NEVER cross the IPC boundary. The webview can ask "am I signed in?" and
//! "sign me in from this key file", but it can never read the key or the
//! token — unlike the web dashboard, which necessarily holds its credential
//! in `localStorage` where any script in the page can read it.
//!
//! Flow (matches `core/src/server/http.rs` operator_challenge/operator_session):
//!   1. POST /api/operator/challenge      -> {challenge}
//!   2. sign challenge bytes with the operator Ed25519 seed
//!   3. POST /api/operator/session {lct_id, challenge, signature} -> {token}
//!   4. every /api/* request carries `Authorization: Bearer <token>`
//!
//! The challenge is single-use (the daemon burns the nonce even on a failed
//! attempt), so a re-auth always fetches a fresh one.

use std::path::PathBuf;

use ed25519_dalek::{Signer, SigningKey};
use serde::{Deserialize, Serialize};

/// The on-disk operator credential: `{lct_id, secret_key_hex}` where
/// `secret_key_hex` is a 32-byte Ed25519 seed (hex). Same file the daemon
/// mints at genesis (`core/src/server/state.rs`).
#[derive(Debug, Clone, Deserialize)]
pub struct OperatorKeyFile {
    pub lct_id: String,
    pub secret_key_hex: String,
}

/// What the UI is allowed to know about the operator session: whether it
/// exists and which LCT it belongs to. Never the token.
#[derive(Debug, Clone, Serialize, Default)]
pub struct OperatorStatus {
    pub signed_in: bool,
    pub lct_id: Option<String>,
    /// Where the key was loaded from, so the UI can offer "sign in again"
    /// without a file picker. Path only — never contents.
    pub key_path: Option<String>,
}

/// The live session. Held in `AppState` behind a mutex; token is private to
/// this crate and only ever attached to outbound daemon requests.
#[derive(Debug, Clone)]
pub struct OperatorSession {
    pub lct_id: String,
    pub token: String,
    pub key_path: Option<String>,
}

/// Default credential location — the same path the daemon writes and the
/// dashboard's one-click login reads. Checked so the UI can offer a plain
/// "Sign in" button instead of a file picker (dp 2026-07-24: "I'd rather
/// just click login").
pub fn default_key_path() -> Option<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from)?;
    let p = home.join(".hestia").join("operator.key");
    p.exists().then_some(p)
}

pub fn read_key_file(path: &str) -> Result<OperatorKeyFile, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
    serde_json::from_str::<OperatorKeyFile>(&raw)
        .map_err(|e| format!("{path} is not a {{lct_id, secret_key_hex}} credential: {e}"))
}

fn signing_key(key: &OperatorKeyFile) -> Result<SigningKey, String> {
    let raw = hex_decode(&key.secret_key_hex)?;
    let seed: [u8; 32] = raw
        .try_into()
        .map_err(|_| "secret_key_hex must be a 32-byte Ed25519 seed".to_string())?;
    Ok(SigningKey::from_bytes(&seed))
}

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    let s = s.trim();
    if s.len() % 2 != 0 {
        return Err("odd-length hex".into());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Run the full challenge -> sign -> session handshake against `daemon_url`.
/// Returns the session on success. The signature is over the raw challenge
/// bytes, matching `authenticate_operator` in the daemon.
pub async fn authenticate(
    daemon_url: &str,
    key_path: &str,
) -> Result<OperatorSession, String> {
    let key = read_key_file(key_path)?;
    let sk = signing_key(&key)?;

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

    let signature = hex_encode(&sk.sign(challenge.as_bytes()).to_bytes());

    let resp = client
        .post(format!("{daemon_url}/api/operator/session"))
        .json(&serde_json::json!({
            "lct_id": key.lct_id,
            "challenge": challenge,
            "signature": signature,
        }))
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
        lct_id: key.lct_id,
        token,
        key_path: Some(key_path.to_string()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_roundtrip() {
        let bytes = [0u8, 1, 15, 16, 255];
        assert_eq!(hex_decode(&hex_encode(&bytes)).unwrap(), bytes);
    }

    #[test]
    fn seed_must_be_32_bytes() {
        let short = OperatorKeyFile {
            lct_id: "lct:test".into(),
            secret_key_hex: "abcd".into(),
        };
        assert!(signing_key(&short).is_err());
    }

    #[test]
    fn signature_verifies_against_the_public_key() {
        use ed25519_dalek::{Verifier, VerifyingKey};
        let key = OperatorKeyFile {
            lct_id: "lct:test".into(),
            secret_key_hex: hex_encode(&[7u8; 32]),
        };
        let sk = signing_key(&key).unwrap();
        let challenge = "test-challenge-nonce";
        let sig = sk.sign(challenge.as_bytes());
        let vk: VerifyingKey = sk.verifying_key();
        assert!(vk.verify(challenge.as_bytes(), &sig).is_ok());
        // and hex-encodes to the 64-byte form the daemon decodes
        assert_eq!(hex_encode(&sig.to_bytes()).len(), 128);
    }
}
