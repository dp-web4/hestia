//! `hestia member` — the operator client for the member registry's one
//! administrative REMOVE (#990): `retire` a residue name out of the
//! governance-invitation pool, `reinstate` it again.
//!
//! WHY THIS COMMAND EXISTS. The invitation pool is built from the member registry,
//! whose entry side is free and unauthenticated (#63: `plugin_id` is caller-supplied
//! at connect, and a first-ever connect mints a durable member). Measured on the
//! claude-code seat 2026-08-31 → 2026-09-07: 1,074 of 1,291 `review_request`s
//! (83.2%) went to names with no mailbox reader — probe residue, impostor probes,
//! typo'd connects, one-touch gates. The registry had no remove operation at all:
//! the only way to drop a name was hand-editing an encrypted vault doc. The daemon
//! half of this (tombstone + witnessed `member_retired` + the pool filter) is the
//! law; this client is the reachability, the same shape `gate_cli` is for
//! escalations.
//!
//! WHAT THIS IS NOT. This adds no authority. The daemon's `operator_gate` decides:
//! the act rides a challenge-signed operator session (`HighReversible` — one
//! operator, because a tombstone is undoable by design), and the witnessed row
//! takes its author from the session's provenance, never from this process. This
//! client can only reach verdicts the daemon would already permit from any other
//! signed operator surface.
//!
//! THE KEY. The operator credential is a JSON file `{lct_id, secret_key_hex}`
//! whose public half is law-listed in `operator_access` — the same shape
//! `tools/seed_seat_config.py`'s `Operator` reads. It is READ, never printed, and
//! supplied (`--key` / `HESTIA_OPERATOR_KEY`), never guessed: this fleet has been
//! burned by a tool that derived a locator a table already stated.

use anyhow::{anyhow, bail, Context, Result};
use serde_json::json;
use std::path::Path;
use std::time::Duration;

/// One challenge-signed operator session against the local daemon. Mirrors
/// `tools/seed_seat_config.py`'s `Operator.call` — bearer token, JSON in/out,
/// daemon error text surfaced verbatim (it is the diagnosis).
struct OperatorSession {
    client: reqwest::blocking::Client,
    base: String,
    token: String,
    /// The operator principal the daemon resolved (for display — the record's
    /// author comes from the daemon's side of the same session).
    operator: String,
}

impl OperatorSession {
    /// Challenge → sign → session. The key is read here and never leaves the
    /// process. Errors refuse loudly: a session that cannot open is the whole
    /// answer, and continuing without one would mint nothing anyway.
    fn open(endpoint: &str, key_path: &Path) -> Result<Self> {
        let cred_text = std::fs::read_to_string(key_path)
            .with_context(|| format!("reading operator credential {}", key_path.display()))?;
        let cred: serde_json::Value = serde_json::from_str(&cred_text)
            .with_context(|| format!("parsing {} — expected {{lct_id, secret_key_hex}}", key_path.display()))?;
        let lct_id = cred["lct_id"]
            .as_str()
            .ok_or_else(|| anyhow!("{}: missing 'lct_id'", key_path.display()))?
            .to_string();
        let secret_hex = cred["secret_key_hex"]
            .as_str()
            .ok_or_else(|| anyhow!("{}: missing 'secret_key_hex'", key_path.display()))?;
        let secret = hex::decode(secret_hex.trim())
            .with_context(|| format!("{}: 'secret_key_hex' is not hex", key_path.display()))?;
        let seed: [u8; 32] = secret
            .get(..32)
            .and_then(|b| b.try_into().ok())
            .ok_or_else(|| anyhow!("{}: need at least 32 secret bytes", key_path.display()))?;
        let keypair = web4_core::crypto::KeyPair::from_secret_bytes(&seed);

        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(15))
            .build()?;
        let base = endpoint.trim_end_matches('/').to_string();

        let challenge: serde_json::Value = client
            .post(format!("{base}/api/operator/challenge"))
            .json(&json!({}))
            .send()
            .context("POST /api/operator/challenge")?
            .error_for_status()
            .map_err(|e| anyhow!("operator challenge refused: {e}"))?
            .json()
            .context("decoding the operator challenge")?;
        let nonce = challenge["challenge"]
            .as_str()
            .ok_or_else(|| anyhow!("the challenge answer carried no 'challenge'"))?
            .to_string();

        // The daemon verifies against `challenge.as_bytes()` — the nonce STRING's
        // bytes, exactly as `authenticate_operator` checks them.
        let signature = keypair.sign(nonce.as_bytes()).to_hex();
        let session: serde_json::Value = client
            .post(format!("{base}/api/operator/session"))
            .json(&json!({
                "lct_id": lct_id,
                "challenge": nonce,
                "signature": signature,
            }))
            .send()
            .context("POST /api/operator/session")?
            .error_for_status()
            .map_err(|e| {
                anyhow!(
                    "operator session refused: {e} — is this key's public half in operator_access?"
                )
            })?
            .json()
            .context("decoding the operator session")?;
        let token = session["token"]
            .as_str()
            .ok_or_else(|| anyhow!("the session answer carried no 'token'"))?
            .to_string();
        let operator = session["operator"]
            .as_str()
            .unwrap_or(lct_id.as_str())
            .to_string();
        Ok(OperatorSession {
            client,
            base,
            token,
            operator,
        })
    }

    fn post(&self, path: &str, body: serde_json::Value) -> Result<serde_json::Value> {
        let resp = self
            .client
            .post(format!("{}{path}", self.base))
            .bearer_auth(&self.token)
            .json(&body)
            .send()
            .with_context(|| format!("POST {path}"))?;
        let status = resp.status();
        let answer: serde_json::Value = resp.json().unwrap_or(json!(null));
        if !status.is_success() {
            let why = answer["error"].as_str().unwrap_or("(no error text)");
            bail!("the daemon refused ({status}): {why}");
        }
        Ok(answer)
    }
}

/// `hestia member retire <plugin_id> --reason '...'`: tombstone the name, and let
/// the daemon's pool filter do the rest. The reason is REQUIRED (the daemon
/// refuses an unstated one) because a prune without a basis cannot be challenged.
pub fn retire(endpoint: &str, key_path: &Path, plugin_id: &str, reason: &str) -> Result<()> {
    let session = OperatorSession::open(endpoint, key_path)?;
    let answer = session.post(
        "/api/operator/member/retire",
        json!({"plugin_id": plugin_id, "reason": reason}),
    )?;
    println!(
        "retired '{}' (operator session as {}; witness {})",
        answer["retired"].as_str().unwrap_or(plugin_id),
        session.operator,
        answer["witnessEntryHash"].as_str().unwrap_or("?"),
    );
    if let Some(note) = answer["note"].as_str() {
        println!("note: {note}");
    }
    Ok(())
}

/// `hestia member reinstate <plugin_id>`: clear the tombstone, return the name to
/// the pool.
pub fn reinstate(endpoint: &str, key_path: &Path, plugin_id: &str) -> Result<()> {
    let session = OperatorSession::open(endpoint, key_path)?;
    let answer = session.post(
        "/api/operator/member/reinstate",
        json!({"plugin_id": plugin_id}),
    )?;
    println!(
        "reinstated '{}' (operator session as {}; witness {})",
        answer["reinstated"].as_str().unwrap_or(plugin_id),
        session.operator,
        answer["witnessEntryHash"].as_str().unwrap_or("?"),
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    /// The one byte-format this module shares with the daemon: the operator signs
    /// the challenge STRING's bytes, and `authenticate_operator` verifies exactly
    /// those. Pinned here because the signer and the verifier live in different
    /// crates and nothing else joins them.
    #[test]
    fn the_signed_preimage_is_the_challenge_strings_bytes() {
        let nonce = "ab12cd34";
        let sig = web4_core::crypto::KeyPair::from_secret_bytes(&[7u8; 32])
            .sign(nonce.as_bytes())
            .to_hex();
        assert_eq!(sig.len(), 128, "an Ed25519 signature hex");
        // and the same key verifies it through the daemon's own check shape
        let kp = web4_core::crypto::KeyPair::from_secret_bytes(&[7u8; 32]);
        let raw = hex::decode(&sig).unwrap();
        let sig_bytes: [u8; 64] = raw.try_into().unwrap();
        assert!(kp
            .verifying_key()
            .verify(
                nonce.as_bytes(),
                &web4_core::crypto::SignatureBytes::from_bytes(sig_bytes)
            )
            .is_ok());
    }
}
