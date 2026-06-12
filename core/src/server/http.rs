//! HTTP transport for the Hestia MCP server.
//!
//! Mounts two surfaces on the same listener:
//!   /mcp/*           — the MCP StreamableHttp surface (plugin path)
//!   /                — embedded HTML dashboard (operator path)
//!   /api/dashboard   — JSON snapshot consumed by the dashboard + TUI

use anyhow::{Context, Result};
use axum::{
    extract::{Path, Query, State},
    http::{header, HeaderMap, StatusCode},
    response::{Html, IntoResponse, Json},
    routing::{delete, get, post, put},
};
use base64::Engine as _;
use web4_core::oid4vc::{verify_holder_proof, CredentialIssuerMetadata, CredentialRequest};
use web4_core::sd_jwt_vc::SdJwtVc;
use rmcp::transport::streamable_http_server::{
    session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use super::handler::HestiaServer;
use super::state::SharedState;
use crate::callback::{CallbackState, callback_router};

pub const DEFAULT_BIND: &str = "127.0.0.1:7711";

const DASHBOARD_HTML: &str = include_str!("dashboard/index.html");

pub async fn serve(state: SharedState, bind: &str) -> Result<()> {
    serve_with_callback(state, bind, None).await
}

pub async fn serve_with_callback(
    state: SharedState,
    bind: &str,
    callback_keypair: Option<web4_core::crypto::KeyPair>,
) -> Result<()> {
    let addr: SocketAddr = bind
        .parse()
        .with_context(|| format!("parsing bind address '{}'", bind))?;

    let server_clone = HestiaServer::new(state.clone());

    let mut config = StreamableHttpServerConfig::default();
    config.sse_keep_alive = Some(Duration::from_secs(15));
    config.stateful_mode = true;
    config.json_response = true;

    let service = StreamableHttpService::new(
        move || Ok(server_clone.clone()),
        Arc::new(LocalSessionManager::default()),
        config,
    );

    let mut app = axum::Router::new()
        .route("/", get(dashboard_html))
        .route("/api/dashboard", get(dashboard_json))
        .route("/api/failures", get(failures_json))
        .route("/api/vault", get(vault_list).post(vault_add))
        .route("/api/vault/{name}", delete(vault_delete))
        .route("/api/policy", get(policy_get))
        .route("/api/policy/preset", put(policy_set_preset))
        .route("/api/chain", get(chain_query))
        // OID4VCI issuance (EUDI Phase 2) — hestia as person-scale issuer
        .route("/.well-known/openid-credential-issuer", get(vci_metadata))
        .route("/vci/nonce", post(vci_nonce))
        .route("/vci/credential", post(vci_credential))
        .with_state(state)
        .nest_service("/mcp", service);

    if let Some(kp) = callback_keypair {
        let cb_state = Arc::new(tokio::sync::Mutex::new(CallbackState::new(kp)));
        app = app.nest("/callback", callback_router(cb_state));
        tracing::info!("Sovereign callback active at /callback");
    }

    let listener = TcpListener::bind(&addr)
        .await
        .with_context(|| format!("binding {}", addr))?;

    tracing::info!("Hestia MCP server listening on http://{}", addr);
    tracing::info!("Dashboard at http://{}/", addr);

    // Run until ctrl-c
    let shutdown_token = CancellationToken::new();
    let shutdown_clone = shutdown_token.clone();
    tokio::spawn(async move {
        let _ = tokio::signal::ctrl_c().await;
        tracing::info!("shutdown signal received");
        shutdown_clone.cancel();
    });

    axum::serve(listener, app)
        .with_graceful_shutdown(async move { shutdown_token.cancelled().await })
        .await
        .context("axum::serve failed")?;

    Ok(())
}

async fn dashboard_html() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        Html(DASHBOARD_HTML),
    )
}

async fn dashboard_json(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let snapshot = s.dashboard_snapshot(50);
    drop(s);
    Json(snapshot)
}

async fn failures_json(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let snapshot = s.failures_snapshot(500);
    drop(s);
    Json(snapshot)
}

// --- Vault endpoints ---

async fn vault_list(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let names = s.vault.list();
    let entries: Vec<serde_json::Value> = names.iter().filter_map(|name| {
        s.vault.get(name).map(|e| serde_json::json!({
            "id": name,
            "name": name,
            "scope": e.scope,
            "tags": e.tags,
            "allowed_consumers": e.allowed_consumers,
            "created_at": e.created_at,
            "last_rotated": e.last_rotated,
        }))
    }).collect();
    Json(serde_json::json!({ "entries": entries }))
}

async fn vault_add(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let name = body.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let value = body.get("value").and_then(|v| v.as_str()).unwrap_or("");
    if name.is_empty() || value.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": "name and value required"})));
    }
    let scope: Vec<String> = body.get("scope").and_then(|v| serde_json::from_value(v.clone()).ok()).unwrap_or_default();
    let tags: Vec<String> = body.get("tags").and_then(|v| serde_json::from_value(v.clone()).ok()).unwrap_or_default();
    let consumers: Vec<String> = body.get("allowed_consumers").and_then(|v| serde_json::from_value(v.clone()).ok()).unwrap_or_default();

    let entry = crate::vault::VaultEntry::new(name, value)
        .with_scope(scope)
        .with_tags(tags)
        .with_consumers(consumers);

    let mut s = state.lock().await;
    match s.vault.add(entry) {
        Ok(()) => (StatusCode::OK, Json(serde_json::json!({"ok": true}))),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

async fn vault_delete(
    State(state): State<SharedState>,
    Path(name): Path<String>,
) -> impl IntoResponse {
    let mut s = state.lock().await;
    match s.vault.remove(&name) {
        Ok(_) => Json(serde_json::json!({"ok": true})),
        Err(e) => Json(serde_json::json!({"error": e.to_string()})),
    }
}

// --- OID4VCI issuance endpoints (EUDI Phase 2) ---

/// Issuer base URL from the request Host header (the credential `iss`/audience).
fn issuer_base(headers: &HeaderMap) -> String {
    let host = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("127.0.0.1:7711");
    format!("http://{host}")
}

async fn vci_metadata(headers: HeaderMap) -> impl IntoResponse {
    let base = issuer_base(&headers);
    Json(CredentialIssuerMetadata::for_vct(&base, "Web4Presence"))
}

async fn vci_nonce(State(state): State<SharedState>) -> impl IntoResponse {
    // 128-bit random, hex. Single-use; consumed at the credential endpoint.
    let nonce = web4_core::sha256_hex(uuid::Uuid::new_v4().as_bytes());
    let mut s = state.lock().await;
    s.vci_nonces.insert(nonce.clone());
    Json(serde_json::json!({ "c_nonce": nonce }))
}

async fn vci_credential(
    State(state): State<SharedState>,
    headers: HeaderMap,
    Json(req): Json<CredentialRequest>,
) -> impl IntoResponse {
    let base = issuer_base(&headers);
    let now = chrono::Utc::now().timestamp();

    // Extract the c_nonce the wallet's proof was bound to (from the proof JWT
    // payload) so we can check it's one we issued.
    let proof_nonce = match proof_nonce(&req.proof_jwt) {
        Some(n) => n,
        None => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error":"proof missing nonce"}))),
    };

    let mut s = state.lock().await;

    // Single-use: must be a nonce we issued; consume it.
    if !s.vci_nonces.remove(&proof_nonce) {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error":"unknown or used c_nonce"})));
    }

    // Verify the holder key-possession proof (aud = us, fresh).
    let holder_pk = match verify_holder_proof(&req.proof_jwt, &base, &proof_nonce, 300, now) {
        Ok(pk) => pk,
        Err(e) => return (StatusCode::UNAUTHORIZED, Json(serde_json::json!({"error": e}))),
    };

    // Load the daemon's issuer identity from the vault (init --ai).
    let (issuer_lct, issuer_key) = match s.vault.get("ai_identity_secret").map(|e| e.secret.clone()) {
        Some(hex) => {
            let lct = s.vault.get("ai_identity_lct_id").map(|e| e.secret.clone()).unwrap_or_default();
            match hex32(&hex) {
                Some(b) => (lct, web4_core::crypto::KeyPair::from_secret_bytes(&b)),
                None => return (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error":"identity key malformed"}))),
            }
        }
        None => return (StatusCode::CONFLICT, Json(serde_json::json!({"error":"no issuer identity — run `hestia init --ai`"}))),
    };

    // Assurance level from the local constellation (ties the credential to the
    // device-constellation work); default single_device if none.
    let assurance = crate::constellation::ConstellationStore::load(&s.home)
        .ok()
        .and_then(|st| serde_json::to_value(st.proof().assurance_level).ok())
        .and_then(|v| v.as_str().map(String::from))
        .unwrap_or_else(|| "single_device".into());

    let host = headers.get(header::HOST).and_then(|h| h.to_str().ok()).unwrap_or("127.0.0.1:7711");
    let issuer_did = if issuer_lct.is_empty() {
        format!("did:web:{host}")
    } else {
        format!("did:web4:{host}:{issuer_lct}")
    };

    let credential = SdJwtVc::new("Web4Presence", &issuer_did)
        .iat(now)
        .holder_binding(&holder_pk)
        .sd_claim("assurance_level", serde_json::json!(assurance))
        .sd_claim("issued_by", serde_json::json!("hestia"))
        .issue(&issuer_key, &format!("{issuer_did}#key-0"));

    (StatusCode::OK, Json(serde_json::json!({ "credential": credential, "format": "vc+sd-jwt" })))
}

/// Pull the `nonce` claim out of an OID4VCI proof JWT (no verification — just to
/// look up which issued nonce it claims, before verifying).
fn proof_nonce(proof_jwt: &str) -> Option<String> {
    let payload_b64 = proof_jwt.split('.').nth(1)?;
    let raw = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(payload_b64).ok()?;
    let v: serde_json::Value = serde_json::from_slice(&raw).ok()?;
    v.get("nonce").and_then(|n| n.as_str()).map(String::from)
}

fn hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 { return None; }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).ok()?;
    }
    Some(out)
}

// --- Policy endpoints ---

async fn policy_get(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let policy_state = s.vault.policy();
    let resolved = policy_state.resolve().unwrap_or_else(|| {
        crate::policy::get_preset("safety").unwrap().config
    });
    Json(serde_json::json!({
        "active_preset": policy_state.active_preset,
        "enforce": resolved.enforce,
        "default_policy": format!("{:?}", resolved.default_policy),
        "rules": resolved.rules.iter().map(|r| serde_json::json!({
            "id": r.id,
            "name": r.name,
            "priority": r.priority,
            "decision": r.decision.as_str(),
        })).collect::<Vec<_>>(),
    }))
}

async fn policy_set_preset(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let preset = body.get("preset").and_then(|v| v.as_str()).unwrap_or("");
    if !crate::policy::is_preset_name(preset) {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": format!("unknown preset: {preset}")})));
    }
    let mut s = state.lock().await;
    match s.vault.set_active_preset(preset) {
        Ok(()) => (StatusCode::OK, Json(serde_json::json!({"ok": true, "preset": preset}))),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

// --- Chain endpoints ---

#[derive(serde::Deserialize, Default)]
struct ChainQuery {
    limit: Option<u64>,
    event_type: Option<String>,
    tool: Option<String>,
}

async fn chain_query(
    State(state): State<SharedState>,
    Query(q): Query<ChainQuery>,
) -> impl IntoResponse {
    let s = state.lock().await;
    let limit = q.limit.unwrap_or(50);
    let entries: Vec<super::dashboard::RecentEntry> = s.chain_store
        .read_recent(limit)
        .unwrap_or_default()
        .into_iter()
        .map(super::dashboard::flatten_entry)
        .filter(|e| {
            if let Some(ref et) = q.event_type {
                if e.event_type != *et { return false; }
            }
            if let Some(ref tf) = q.tool {
                if let Some(ref tn) = e.tool_name {
                    if !tn.contains(tf.as_str()) { return false; }
                } else {
                    return false;
                }
            }
            true
        })
        .collect();
    Json(serde_json::json!({ "entries": entries }))
}
