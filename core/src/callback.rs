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
    pub signing_bytes_hex: String,
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

    fn re_derive_signing_bytes(&self, intent: &SignIntent) -> Vec<u8> {
        let canonical = serde_json::to_vec(&intent.event)
            .unwrap_or_default();
        web4_core::crypto::sha256(&canonical).to_vec()
    }
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

    // Defense-in-depth: re-derive signing bytes from intent rather than
    // blindly signing whatever the hub supplies.
    let derived = state.re_derive_signing_bytes(&req.intent);
    let sig = state.keypair.sign(&derived);

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
}
