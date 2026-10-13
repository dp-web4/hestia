//! `hestia member` — the operator client for retiring a member id on this seat
//! (#990's remedy, on #1100's store): `retire` takes a residue name out of every
//! governance-selection pool AND revokes its grants, `reinstate` brings it back.
//!
//! WHY THIS COMMAND EXISTS. The invitation pool is built from the member registry,
//! whose entry side is free and unauthenticated (#63: `plugin_id` is caller-supplied
//! at connect, and a first-ever connect mints a durable member). Measured on the
//! claude-code seat 2026-08-31 → 2026-09-07: 1,074 of 1,291 `review_request`s
//! (83.2%) went to names with no mailbox reader — probe residue, impostor probes,
//! typo'd connects, one-touch gates. The daemon's half (the `members/retired`
//! store, `POST /api/agents/:id/retire`, the pool filters reading it) is the law;
//! this client is the reachability — the same verb the dashboard's agents view
//! drives, from a shell — the same shape `gate_cli` is for escalations.
//!
//! ONE VERB, ONE STORE. An earlier cut of this surface carried a SECOND retire
//! route (`/api/operator/member/retire`) writing a registry tombstone the pools
//! read — two stores that could disagree, neither naming the other (claude-code's
//! re-review, 2026-10-13). The tombstone was dropped; the pool filters read the
//! store this route writes, so an id retired here — or from the dashboard — is
//! out of every selection path in the same act.
//!
//! WHAT THIS IS NOT. This adds no authority. The daemon's `operator_gate` decides:
//! the act rides a challenge-signed operator session (`HighReversible` — one
//! operator, because retirement is undoable by design), and the witnessed rows
//! take their author from the session the middleware authenticated, never from
//! this process. This client can only reach verdicts the daemon would already
//! permit from any other signed operator surface.
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

/// `hestia member retire <plugin_id> --reason '...' --ref '...'`: the one retire
/// verb, from a shell — the id is out of every governance-selection pool and its
/// grants are revoked in the same act (the daemon's `retire_guard` refuses a
/// recently-active id unless `--confirm-active` says the word). Reason AND ref
/// are required (the daemon refuses an unexplained one): a retirement that
/// revokes authority must not be an unexplained row itself.
///
/// The id rides the URL path, so this client refuses ids that are not a single
/// safe path segment rather than let one misroute — member ids are slug-shaped
/// (`claude-code`, `ollama:qwen3:2b@sha256:…`); anything else is a typo to fix,
/// not a name to encode around.
pub fn retire(
    endpoint: &str,
    key_path: &Path,
    plugin_id: &str,
    reason: &str,
    evidence_ref: &str,
    confirm_active: bool,
) -> Result<()> {
    let id = plugin_id.trim();
    if id.is_empty()
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':' | '@' | '+'))
    {
        bail!("'{plugin_id}' is not a single safe URL path segment — refusing to misroute");
    }
    let session = OperatorSession::open(endpoint, key_path)?;
    let answer = session.post(
        &format!("/api/agents/{id}/retire"),
        json!({"reason": reason, "ref": evidence_ref, "confirm_active": confirm_active}),
    )?;
    println!(
        "retired '{}' (operator session as {}; intent {}, witness {})",
        answer["plugin_id"].as_str().unwrap_or(id),
        session.operator,
        answer["intentEntryHash"].as_str().unwrap_or("?"),
        answer["witnessEntryHash"].as_str().unwrap_or("?"),
    );
    let revoked = answer["revoked_standing_paths"].as_array().map(|v| v.len()).unwrap_or(0);
    if revoked > 0 {
        println!("revoked {revoked} standing grant(s) in the same act — they are NOT restored by reinstate");
    }
    if let Some(note) = answer["note"].as_str() {
        println!("note: {note}");
    }
    Ok(())
}

/// `hestia member reinstate <plugin_id> --reason '...'`: lift the retirement,
/// return the name to the pools. The grants revoked at retirement stay revoked
/// — re-grant any that are still wanted, deliberately.
pub fn reinstate(endpoint: &str, key_path: &Path, plugin_id: &str, reason: &str) -> Result<()> {
    let id = plugin_id.trim();
    if id.is_empty()
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':' | '@' | '+'))
    {
        bail!("'{plugin_id}' is not a single safe URL path segment — refusing to misroute");
    }
    let session = OperatorSession::open(endpoint, key_path)?;
    let answer = session.post(
        &format!("/api/agents/{id}/reinstate"),
        json!({"reason": reason}),
    )?;
    println!(
        "reinstated '{}' (operator session as {}; intent {}, witness {})",
        answer["plugin_id"].as_str().unwrap_or(id),
        session.operator,
        answer["intentEntryHash"].as_str().unwrap_or("?"),
        answer["witnessEntryHash"].as_str().unwrap_or("?"),
    );
    if let Some(note) = answer["note"].as_str() {
        println!("note: {note}");
    }
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
