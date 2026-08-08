//! The app's own identity — the **harness**, distinct from the human it acts for.
//!
//! ## Why this module exists
//!
//! Decision 0014 §2.1 (from GPT's review of #297): the app is a *member with its own LCT*
//! that fills a role — it is **not** the human, and it must never sign as the human. Before
//! this module, `operator.rs` did exactly that: it signed the daemon's challenge with the
//! principal's key and presented the principal's `lct_id`, so one identity did duty for two
//! and **the harness actor vanished from the record**. That is the deputy problem,
//! reintroduced by the surface built to make humans legible.
//!
//! The composition this restores:
//!
//! ```text
//! principal:  human-root-LCT     — who this is for; the beneficiary
//! via_device: device-LCT         — the anchor the person is present through
//! actor:      app-instance-LCT   — THIS module; the harness that sent the request
//! office:     role-LCT           — what is being exercised (often Sovereign)
//! authority:  occupancy / delegation / session-id
//! ```
//!
//! ## Why `web4-core` and not `hestia`
//!
//! The id format is **not invented here**. `Lct::lct_id()` is the canonical, key-derived
//! `lct:web4:mb32:…` used everywhere else in the fleet, and re-deriving it locally is exactly
//! the fork this project keeps paying for.
//!
//! The dependency also mirrors decision 0014's split: the app takes the **identity** domain
//! (`web4-core`) and deliberately does *not* take the **governance** domain (`hestia` core).
//! An app that linked the daemon would be a node pretending to be a client.
//!
//! ## Custody
//!
//! The harness secret is **device-local and non-replicated** (0014 §1.1). It is this app
//! instance on this device — copying it to another device would mint a second actor wearing
//! the same name, which is the inverse of what the constellation is for. Losing it is
//! recoverable: a new harness identity is minted and the *principal* is unchanged.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use web4_core::crypto::KeyPair;
use web4_core::lct::{EntityType, Lct};

/// Filename of the harness credential inside the app's identity directory.
const HARNESS_FILE: &str = "harness-identity.json";

/// The app instance's own identity. `lct_id` is safe to show and to send; the secret never
/// leaves this module's file and never crosses the IPC boundary to the webview.
#[derive(Clone)]
pub struct HarnessIdentity {
    /// Canonical key-derived id, `lct:web4:mb32:…`.
    pub lct_id: String,
    keypair: KeyPair,
}

/// Hand-written so the secret can never reach a log line. `KeyPair` has no `Debug`, and
/// deriving one here would have been the wrong fix — the field must stay unprintable.
impl std::fmt::Debug for HarnessIdentity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("HarnessIdentity")
            .field("lct_id", &self.lct_id)
            .field("keypair", &"<redacted>")
            .finish()
    }
}

impl HarnessIdentity {
    /// Sign as the harness. Note the absence of any path that signs as the principal —
    /// that is the point of the module, not an oversight.
    pub fn sign(&self, message: &[u8]) -> Vec<u8> {
        self.keypair.sign(message).bytes.to_vec()
    }
}

/// On-disk form. Secret is hex like the rest of the fleet's credential files.
#[derive(Serialize, Deserialize)]
struct StoredHarness {
    lct_id: String,
    secret_key_hex: String,
}

fn harness_path(dir: &Path) -> PathBuf {
    dir.join(HARNESS_FILE)
}

/// Load this app instance's harness identity, creating it on first run.
///
/// **Durable by construction** (0014 §4): a harness regenerated per launch would make every
/// restart a different actor, and the chain would record a stranger each time. So the second
/// call returns the first call's identity.
pub fn harness_identity(dir: &Path) -> Result<HarnessIdentity, String> {
    let path = harness_path(dir);

    if let Ok(raw) = std::fs::read_to_string(&path) {
        let stored: StoredHarness = serde_json::from_str(&raw)
            .map_err(|e| format!("harness credential at {} is unreadable: {e}", path.display()))?;
        let bytes: [u8; 32] = hex_decode32(&stored.secret_key_hex)
            .ok_or_else(|| format!("harness secret at {} is not 32 hex bytes", path.display()))?;
        let keypair = KeyPair::from_secret_bytes(&bytes);
        return Ok(HarnessIdentity { lct_id: stored.lct_id, keypair });
    }

    // First run for this app instance.
    // `AiSoftware` = software-bound actor. The app is a harness rather than a model, and
    // web4 has no `Application`/`Software` variant — the closest honest type is the
    // software-actor one. FLAGGED FOR REVIEW: if the ontology gains a harness/application
    // type, this should move to it rather than stay by inertia.
    let (lct, keypair) = Lct::new(EntityType::AiSoftware, None);
    let lct_id = lct.lct_id();

    std::fs::create_dir_all(dir)
        .map_err(|e| format!("cannot create identity dir {}: {e}", dir.display()))?;
    let stored = StoredHarness {
        lct_id: lct_id.clone(),
        secret_key_hex: hex_encode(&keypair.secret_key_bytes()),
    };
    let json = serde_json::to_string_pretty(&stored).map_err(|e| e.to_string())?;

    // Written via a temp + rename so a crash mid-write cannot leave a half credential that
    // parses as a *different* identity.
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, json).map_err(|e| format!("cannot write harness credential: {e}"))?;
    restrict(&tmp);
    std::fs::rename(&tmp, &path).map_err(|e| format!("cannot install harness credential: {e}"))?;

    Ok(HarnessIdentity { lct_id, keypair })
}

/// The operator-session request body, carrying **actor and principal as separate fields**.
///
/// The daemon side of this is A3 and does not exist yet: today `/api/operator/session`
/// accepts `{lct_id, challenge, signature}` only. `lct_id` is therefore still sent, set to
/// the **principal**, so this remains wire-compatible with the current daemon while the
/// composed fields ride alongside. When A3 lands, `lct_id` is what gets removed.
pub fn session_request_body(
    harness: &HarnessIdentity,
    principal_lct: &str,
    challenge: &str,
    signature_hex: &str,
) -> serde_json::Value {
    serde_json::json!({
        // Composition (0014 §2.1). `actor` is who sent it; `principal` is who it is for.
        "actor": harness.lct_id,
        "principal": principal_lct,
        // Back-compat with the current daemon contract; removed in A3.
        "lct_id": principal_lct,
        "challenge": challenge,
        "signature": signature_hex,
    })
}

#[cfg(unix)]
fn restrict(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn restrict(_path: &Path) {}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn hex_decode32(s: &str) -> Option<[u8; 32]> {
    let s = s.trim();
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for (i, chunk) in s.as_bytes().chunks(2).enumerate() {
        out[i] = u8::from_str_radix(std::str::from_utf8(chunk).ok()?, 16).ok()?;
    }
    Some(out)
}
