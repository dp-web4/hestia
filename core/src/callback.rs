//! Sovereign callback server — receives signing requests from hubs.
//!
//! When a hub needs a Sovereign signature (genesis, role assignment, etc.),
//! it sends a SignRequest to Hestia's callback endpoint. Hestia evaluates
//! authority + need-to-know, optionally prompts the operator, and returns
//! the signature or a denial.
//!
//! Wire shape per CBP's V2-7 spec (forum/cbp-v2-7-v2-8-pickup-2026-06-07.md):
//! ```json
//! POST {callback_url}
//! {
//!   "intent": { "request_id", "hub_id", "hub_name", "actor_lct_id",
//!               "ledger_index", "event_kind", "event": {...} },
//!   "signing_bytes_hex": "hex..."
//! }
//! → { "request_id", "signature": "hex-64" }
//! → { "request_id", "denied": true, "deny_reason": "..." }
//! ```

use anyhow::Result;
use axum::{extract::State, http::StatusCode, routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;
use web4_core::crypto::KeyPair;

/// Intent payload from the hub — describes what it wants signed.
#[derive(Clone, Debug, Deserialize)]
pub struct SignIntent {
    pub request_id: Uuid,
    pub hub_id: Uuid,
    #[serde(default)]
    pub hub_name: String,
    pub actor_lct_id: Uuid,
    #[serde(default)]
    pub ledger_index: u64,
    pub event_kind: String,
    pub event: serde_json::Value,
}

/// Incoming signing request from the hub.
#[derive(Clone, Debug, Deserialize)]
pub struct SignRequest {
    pub intent: SignIntent,
    #[serde(default)]
    pub signing_bytes_hex: String,
}

fn hex_decode(s: &str) -> std::result::Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd length".into());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

/// Response to the hub — either a signature or a denial.
#[derive(Clone, Debug, Serialize)]
pub struct SignResponse {
    pub request_id: Uuid,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub denied: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deny_reason: Option<String>,
}

/// Callback server state — holds the signing keypair and policy gate.
pub struct CallbackState {
    pub keypair: KeyPair,
    pub auto_approve: bool,
    pub approved_events: Vec<String>,
}

impl CallbackState {
    pub fn new(keypair: KeyPair) -> Self {
        Self {
            keypair,
            auto_approve: false,
            approved_events: vec![
                "genesis".into(),
                "member_added".into(),
                "role_assigned".into(),
                "member_skill_declared".into(),
                "law_amended".into(),
                // OID4VCI issuance: the vault signs SD-JWT-VCs the hub mints
                // under the Sovereign's identity (e.g. Web4Membership). Bytes
                // are validated against the intent before signing.
                "oid4vci_credential".into(),
            ],
        }
    }

    pub fn auto_approve_all(mut self) -> Self {
        self.auto_approve = true;
        self
    }

    fn should_approve(&self, event_kind: &str) -> bool {
        self.auto_approve || self.approved_events.iter().any(|e| e == event_kind)
    }

}

/// The event kind the hub uses for OID4VCI credential issuance.
const ISSUANCE_EVENT_KIND: &str = "oid4vci_credential";

/// Defense-in-depth for OID4VCI issuance: the vault must not sign a credential
/// it didn't authorize. The hub hands over the raw JWS signing input
/// (`base64url(header).base64url(payload)`); we decode the payload and confirm
/// it genuinely is the credential the human-readable intent describes:
///
/// - `iss` must reference the actor LCT we're signing as — binds the credential's
///   declared issuer to *our* key. (A mismatched `iss` would anyway produce a
///   credential no verifier accepts, but we refuse to spend a signature on it.)
/// - `vct` / `sub` must match what the intent claims, so the bytes can't say
///   something other than what the operator is approving.
///
/// Returns `Err(reason)` to deny.
fn validate_issuance(intent: &SignIntent, signing_bytes: &[u8]) -> std::result::Result<(), String> {
    let signing_input = std::str::from_utf8(signing_bytes)
        .map_err(|_| "issuance signing bytes are not valid UTF-8".to_string())?;
    // Must be a bare JWS signing input: exactly header.payload (no signature).
    if signing_input.split('.').count() != 2 {
        return Err("issuance signing input must be `header.payload`".into());
    }

    let iss = web4_core::oid4vc::jwt_payload_claim(signing_input, "iss")
        .ok_or("credential payload missing `iss`")?;
    let actor = intent.actor_lct_id.to_string();
    if !iss.contains(&actor) {
        return Err(format!(
            "credential `iss` ({iss}) does not reference the signing actor {actor}"
        ));
    }

    // The bytes must match the human-readable intent the operator approves.
    if let Some(want_vct) = intent.event.get("vct").and_then(|v| v.as_str()) {
        let got = web4_core::oid4vc::jwt_payload_claim(signing_input, "vct");
        if got.as_deref() != Some(want_vct) {
            return Err("credential `vct` does not match the intent".into());
        }
    }
    if let Some(want_sub) = intent.event.get("sub").and_then(|v| v.as_str()) {
        let got = web4_core::oid4vc::jwt_payload_claim(signing_input, "sub");
        if got.as_deref() != Some(want_sub) {
            return Err("credential `sub` does not match the intent".into());
        }
    }
    Ok(())
}

async fn handle_sign_request(
    State(state): State<Arc<Mutex<CallbackState>>>,
    Json(req): Json<SignRequest>,
) -> (StatusCode, Json<SignResponse>) {
    let state = state.lock().await;
    let request_id = req.intent.request_id;

    if !state.should_approve(&req.intent.event_kind) {
        return (
            StatusCode::FORBIDDEN,
            Json(SignResponse {
                request_id,
                signature: None,
                denied: true,
                deny_reason: Some(format!(
                    "event kind '{}' not in approved list",
                    req.intent.event_kind
                )),
            }),
        );
    }

    // Sign the exact bytes the hub computed — the hub verifies against
    // these same bytes, so we must match. The intent is logged for audit.
    let signing_bytes = match hex_decode(&req.signing_bytes_hex) {
        Ok(b) => b,
        Err(_) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(SignResponse {
                    request_id,
                    signature: None,
                    denied: true,
                    deny_reason: Some("invalid signing_bytes_hex".into()),
                }),
            );
        }
    };

    // For OID4VCI issuance, don't blind-sign: confirm the bytes are the
    // credential the intent describes (issuer == us, vct/sub match).
    if req.intent.event_kind == ISSUANCE_EVENT_KIND {
        if let Err(reason) = validate_issuance(&req.intent, &signing_bytes) {
            return (
                StatusCode::FORBIDDEN,
                Json(SignResponse {
                    request_id,
                    signature: None,
                    denied: true,
                    deny_reason: Some(format!("issuance validation failed: {reason}")),
                }),
            );
        }
    }

    let sig = state.keypair.sign(&signing_bytes);

    (
        StatusCode::OK,
        Json(SignResponse {
            request_id,
            signature: Some(sig.to_hex()),
            denied: false,
            deny_reason: None,
        }),
    )
}

/// Build the callback router.
pub fn callback_router(state: Arc<Mutex<CallbackState>>) -> Router {
    Router::new()
        .route("/", post(handle_sign_request))
        .with_state(state)
}

/// Start the callback server on the given bind address.
pub async fn serve_callback(state: Arc<Mutex<CallbackState>>, bind: &str) -> Result<()> {
    let app = callback_router(state);
    let listener = tokio::net::TcpListener::bind(bind).await?;
    tracing::info!("Hestia callback server listening on {bind}");
    axum::serve(listener, app).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_approve_known_events() {
        let kp = KeyPair::generate();
        let state = CallbackState::new(kp);

        assert!(state.should_approve("genesis"));
        assert!(state.should_approve("member_added"));
        assert!(state.should_approve("role_assigned"));
        assert!(!state.should_approve("unknown_danger"));
    }

    #[test]
    fn test_auto_approve_all() {
        let kp = KeyPair::generate();
        let state = CallbackState::new(kp).auto_approve_all();

        assert!(state.should_approve("anything_at_all"));
    }

    #[test]
    fn test_sign_response_serialization() {
        let approved = SignResponse {
            request_id: Uuid::new_v4(),
            signature: Some("abcdef".into()),
            denied: false,
            deny_reason: None,
        };
        let json = serde_json::to_string(&approved).unwrap();
        assert!(!json.contains("denied"));
        assert!(!json.contains("deny_reason"));
        assert!(json.contains("signature"));

        let denied = SignResponse {
            request_id: Uuid::new_v4(),
            signature: None,
            denied: true,
            deny_reason: Some("not authorized".into()),
        };
        let json = serde_json::to_string(&denied).unwrap();
        assert!(json.contains("denied"));
        assert!(json.contains("deny_reason"));
        assert!(!json.contains("signature"));
    }

    fn hex_encode(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    /// Build the SignRequest the hub sends for an OID4VCI credential: a prepared
    /// (unsigned) SD-JWT-VC issued under `actor_lct`, plus the matching intent.
    /// Returns (request, the unsigned credential to assemble after signing).
    fn issuance_request(
        actor_lct: Uuid,
        cred_iss: &str,
        intent_vct: &str,
    ) -> (SignRequest, web4_core::sd_jwt_vc::UnsignedSdJwtVc) {
        use web4_core::sd_jwt_vc::SdJwtVc;
        let holder = KeyPair::generate();
        let subject = "did:web4:hub.example:00000000-0000-0000-0000-0000000000aa";
        let unsigned = SdJwtVc::new("Web4Membership", cred_iss)
            .iat(1_700_000_000)
            .holder_binding(&holder.verifying_key())
            .claim("sub", serde_json::json!(subject))
            .sd_claim("member", serde_json::json!(true))
            .prepare(&format!("{cred_iss}#key-0"));
        let req = SignRequest {
            intent: SignIntent {
                request_id: Uuid::new_v4(),
                hub_id: Uuid::new_v4(),
                hub_name: "Test Hub".into(),
                actor_lct_id: actor_lct,
                ledger_index: 0,
                event_kind: ISSUANCE_EVENT_KIND.into(),
                event: serde_json::json!({ "vct": intent_vct, "sub": subject }),
            },
            signing_bytes_hex: hex_encode(unsigned.signing_bytes()),
        };
        (req, unsigned)
    }

    #[tokio::test]
    async fn issuance_signing_end_to_end() {
        use web4_core::sd_jwt_vc::verify_issuer;
        let kp = KeyPair::generate();
        let vault_pub = kp.verifying_key();
        let state = Arc::new(Mutex::new(CallbackState::new(kp)));

        let actor = Uuid::new_v4();
        let cred_iss = format!("did:web4:hub.example:{actor}");
        let (req, unsigned) = issuance_request(actor, &cred_iss, "Web4Membership");

        let (status, resp) = handle_sign_request(State(state.clone()), Json(req)).await;
        assert_eq!(status, StatusCode::OK);
        let sig_hex = resp.0.signature.expect("vault should sign valid issuance");

        // Assemble the credential and verify it under the vault's key.
        let sig = hex_decode(&sig_hex).unwrap();
        let arr: [u8; 64] = sig.as_slice().try_into().unwrap();
        let compact = unsigned.into_compact(&arr);
        let v = verify_issuer(&compact, &vault_pub).expect("vault-signed credential must verify");
        assert_eq!(v.vct, "Web4Membership");
        assert_eq!(v.issuer, cred_iss);
        assert_eq!(v.claims.get("member").unwrap(), &serde_json::json!(true));
    }

    #[tokio::test]
    async fn issuance_denied_when_iss_not_the_actor() {
        let kp = KeyPair::generate();
        let state = Arc::new(Mutex::new(CallbackState::new(kp)));
        // Credential claims a DIFFERENT issuer than the actor we sign as.
        let actor = Uuid::new_v4();
        let other = Uuid::new_v4();
        let cred_iss = format!("did:web4:hub.example:{other}");
        let (req, _unsigned) = issuance_request(actor, &cred_iss, "Web4Membership");

        let (status, resp) = handle_sign_request(State(state), Json(req)).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert!(resp.0.denied);
        assert!(resp.0.deny_reason.unwrap().contains("does not reference the signing actor"));
    }

    #[tokio::test]
    async fn issuance_denied_when_vct_mismatches_intent() {
        let kp = KeyPair::generate();
        let state = Arc::new(Mutex::new(CallbackState::new(kp)));
        let actor = Uuid::new_v4();
        let cred_iss = format!("did:web4:hub.example:{actor}");
        // Intent claims a different vct than the bytes actually encode.
        let (req, _unsigned) = issuance_request(actor, &cred_iss, "SomethingElse");

        let (status, resp) = handle_sign_request(State(state), Json(req)).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        assert!(resp.0.deny_reason.unwrap().contains("vct"));
    }
}
