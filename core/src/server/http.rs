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

// ---- Operator-surface authentication (RWOA clauses W + O) -------------------
// The operator proves presence by SIGNING a server-issued challenge with their
// LCT (strong evidence); the `operator_gate` middleware is the preflight (O) over
// the operator routes. See `server::operator_auth`.

/// `POST /api/operator/challenge` → a fresh single-use nonce for the operator to
/// sign. Unauthenticated by design (this is how auth STARTS); the nonce is
/// unpredictable, single-use, and TTL-bounded, so issuing it grants nothing.
async fn operator_challenge(State(state): State<SharedState>) -> impl IntoResponse {
    let now = super::state::unix_now();
    let mut s = state.lock().await;
    let challenge = s.operator_challenges.issue(now);
    s.operator_challenges.gc(now, super::operator_auth::CHALLENGE_TTL_SECS);
    (StatusCode::OK, Json(serde_json::json!({ "challenge": challenge })))
}

/// `POST /api/operator/session` {lct_id, challenge, signature} → open an operator
/// session on a verified LCT signature. Returns an opaque bearer token for
/// reversible acts; the irreversible tail re-collects fresh signatures per act.
async fn operator_session(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let (lct_id, challenge, signature) = (
        body.get("lct_id").and_then(|v| v.as_str()).unwrap_or(""),
        body.get("challenge").and_then(|v| v.as_str()).unwrap_or(""),
        body.get("signature").and_then(|v| v.as_str()).unwrap_or(""),
    );
    let now = super::state::unix_now();
    let mut s = state.lock().await;
    let law = s.vault.policy().clone();
    let authed = super::operator_auth::authenticate_operator(
        &law,
        &mut s.operator_challenges,
        lct_id,
        challenge,
        signature,
        now,
        super::operator_auth::CHALLENGE_TTL_SECS,
    );
    match authed {
        Some(op) => {
            let token = s.operator_sessions.open(&op, now);
            let _ = s.append_chain(
                "operator_session_opened",
                serde_json::json!({ "operator": op, "evidence": "operator-lct-signature" }),
            );
            (StatusCode::OK, Json(serde_json::json!({ "token": token, "operator": op })))
        }
        None => (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({ "error": "operator authentication failed" })),
        ),
    }
}

/// The operator-surface preflight (RWOA O): resolve the request's operator from
/// its session, classify the act's stakes (S), and gate on the gradient (W/V).
/// Reversible acts pass on the session; the irreversible tail escalates (202)
/// pending a law-defined quorum; no session ⇒ 401. Every consequential decision
/// is self-witnessed (A). Reachability alone never admits.
async fn operator_gate(
    State(state): State<SharedState>,
    req: axum::extract::Request,
    next: axum::middleware::Next,
) -> axum::response::Response {
    use super::operator_auth::{gate_session_request, AuthzOutcome, Stakes};

    let method = req.method().as_str().to_string();
    let path = req.uri().path().to_string();
    let stakes = Stakes::classify(&method, &path);

    // Dev-only named override — the explicit unsafe escape hatch, refused in the
    // production profile, and loud + witnessed when used. Never the front door.
    let dev_override = std::env::var("HESTIA_OPERATOR_DEV_TOKEN").ok().filter(|t| !t.is_empty());
    let production = std::env::var("HESTIA_PROFILE").map(|p| p == "production").unwrap_or(false);
    let bearer = req
        .headers()
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(str::to_string);

    if let Some(dev) = &dev_override {
        if !production && bearer.as_deref() == Some(dev.as_str()) {
            let now = super::state::unix_now();
            let mut s = state.lock().await;
            eprintln!("[hestia] WARNING: operator dev-override used on {method} {path} (dev-only, unsafe)");
            let _ = s.append_chain(
                "operator_gate",
                serde_json::json!({ "act": format!("{method} {path}"), "verdict": "dev-override",
                    "stakes": stakes.as_str(), "unsafe": true, "at": now }),
            );
            drop(s);
            return next.run(req).await;
        }
    }

    let now = super::state::unix_now();
    let outcome = {
        let s = state.lock().await;
        let law = s.vault.policy();
        let operator = bearer
            .as_deref()
            .and_then(|t| s.operator_sessions.operator(t, now, super::operator_auth::SESSION_TTL_SECS))
            .map(str::to_string);
        gate_session_request(law, operator.as_deref(), stakes)
    };

    // Self-witness the authorization decision (A) for consequential acts (skip the
    // low-stakes read flood).
    if !matches!(stakes, Stakes::LowReversible) {
        let mut s = state.lock().await;
        let _ = s.append_chain("operator_gate", outcome.evidence_record(&format!("{method} {path}")));
    }

    match outcome {
        AuthzOutcome::Authorized { .. } => next.run(req).await,
        AuthzOutcome::RequiresQuorum { have, need, .. } => (
            StatusCode::ACCEPTED,
            Json(serde_json::json!({
                "escalate": "irreversible act requires a quorum of operator signatures",
                "have": have, "need": need, "act": format!("{method} {path}")
            })),
        )
            .into_response(),
        AuthzOutcome::Denied { reason, .. } => {
            (StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": reason }))).into_response()
        }
    }
}

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

    // Bounded operator bootstrap (RWOA genesis window): on a fresh vault this
    // mints the first operator so the gated surface isn't a permanent lockout;
    // it no-ops (window shut) once an operator exists.
    if let Err(e) = state.lock().await.bootstrap_operator_if_genesis() {
        tracing::warn!("operator bootstrap failed: {e}");
    }

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

    // The OPERATOR DATA surface (/api/*): every route behind the operator_gate
    // preflight (RWOA O). route_layer applies only to these routes, not fallbacks.
    // NB: the dashboard HTML shell `GET /` is served UNAUTHENTICATED below — it
    // carries no data (only the app skeleton + the sign-in JS), and it must load
    // for the operator to sign in at all. All *data* lives behind the gate.
    let operator_surface = axum::Router::new()
        .route("/api/dashboard", get(dashboard_json))
        .route("/api/failures", get(failures_json))
        .route("/api/vault", get(vault_list).post(vault_add))
        .route("/api/vault/:name", delete(vault_delete))
        .route("/api/policy", get(policy_get))
        .route("/api/policy/preset", put(policy_set_preset))
        .route("/api/policy/override", put(policy_set_override))
        .route("/api/policy/override/:rule_id", delete(policy_clear_override))
        .route("/api/policy/rule", put(policy_upsert_rule))
        .route("/api/policy/rule/:rule_id", delete(policy_delete_rule))
        .route("/api/orchestrators/:id/connect", post(orchestrator_connect))
        .route("/api/chain", get(chain_query))
        .route_layer(axum::middleware::from_fn_with_state(state.clone(), operator_gate));

    let mut app = axum::Router::new()
        .merge(operator_surface)
        // The dashboard HTML shell — unauthenticated (app skeleton + sign-in JS,
        // no data). The operator signs in from here; all /api/* data is gated.
        .route("/", get(dashboard_html))
        // Operator auth bootstrap surface — UNauthenticated by design (this is how
        // an operator establishes a session; issuing a challenge grants nothing).
        .route("/api/operator/challenge", post(operator_challenge))
        .route("/api/operator/session", post(operator_session))
        // OID4VCI issuance (EUDI Phase 2) — hestia as person-scale issuer.
        // The credential route matches the `<issuer>/credential` that
        // `CredentialIssuerMetadata::for_vct` advertises (issuer = http://host).
        .route("/.well-known/openid-credential-issuer", get(vci_metadata))
        .route("/nonce", post(vci_nonce))
        .route("/credential", post(vci_credential))
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
        Html(load_dashboard_html()),
    )
}

/// The dashboard HTML to serve. Normally the compiled-in copy. When
/// `HESTIA_DASHBOARD_DEV=1` (or `HESTIA_DASHBOARD_PATH=<file>` for an explicit
/// path) it is read **fresh from disk on every request**, so dashboard edits
/// hot-reload on a browser refresh — no rebuild/restart needed. Falls back to
/// the built-in copy if the file can't be read.
fn load_dashboard_html() -> String {
    let path = std::env::var("HESTIA_DASHBOARD_PATH").ok().or_else(|| {
        match std::env::var("HESTIA_DASHBOARD_DEV") {
            Ok(v) if !v.is_empty() && v != "0" => Some(
                concat!(env!("CARGO_MANIFEST_DIR"), "/src/server/dashboard/index.html").to_string(),
            ),
            _ => None,
        }
    });
    match path {
        Some(p) => std::fs::read_to_string(&p).unwrap_or_else(|e| {
            tracing::warn!("dashboard hot-reload: cannot read {p}: {e}; serving built-in copy");
            DASHBOARD_HTML.to_string()
        }),
        None => DASHBOARD_HTML.to_string(),
    }
}

#[derive(serde::Deserialize, Default)]
struct DashboardQuery {
    /// Calendar window for the feed + windowed stat: hour | day | week | all.
    /// Calendar-filtered, not count-filtered — a count window silently evicts
    /// a quiet plugin's entries when busier plugins churn (dp 2026-07-23).
    range: Option<String>,
}

async fn dashboard_json(
    State(state): State<SharedState>,
    Query(q): Query<DashboardQuery>,
) -> impl IntoResponse {
    let now = chrono::Utc::now();
    // Caps are transport safety only; the range does the filtering.
    let (cutoff, cap, label) = match q.range.as_deref() {
        Some("day") => (Some(now - chrono::Duration::days(1)), 5_000, "day"),
        Some("week") => (Some(now - chrono::Duration::weeks(1)), 10_000, "week"),
        Some("all") => (None, 10_000, "all"),
        _ => (Some(now - chrono::Duration::hours(1)), 2_000, "hour"),
    };
    let s = state.lock().await;
    let snapshot = s.dashboard_snapshot_window(cap, cutoff, label);
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
    let proof_nonce = match web4_core::oid4vc::proof_nonce(&req.proof_jwt) {
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
    let assurance = crate::constellation::ConstellationStore::load(&s.vault)
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

fn hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 { return None; }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).ok()?;
    }
    Some(out)
}

// --- Policy endpoints ---

/// Tool categories the policy can match on (mirrors `policy::classify`).
const POLICY_CATEGORIES: &[&str] =
    &["command", "file_read", "file_write", "network", "credential_access", "task_management"];

fn parse_decision(s: &str) -> Option<crate::policy::PolicyDecision> {
    use crate::policy::PolicyDecision::*;
    match s {
        "allow" => Some(Allow),
        "deny" => Some(Deny),
        "warn" => Some(Warn),
        _ => None,
    }
}

/// A short human label for what a rule matches, for the editor list.
fn match_summary(m: &crate::policy::PolicyMatch) -> String {
    let mut parts = Vec::new();
    let join = |v: &Vec<String>| v.join(", ");
    if let Some(t) = m.tools.as_ref().filter(|v| !v.is_empty()) { parts.push(format!("tools: {}", join(t))); }
    if let Some(c) = m.categories.as_ref().filter(|v| !v.is_empty()) { parts.push(format!("categories: {}", join(c))); }
    if let Some(p) = m.target_patterns.as_ref().filter(|v| !v.is_empty()) { parts.push(format!("target ~ {}", join(p))); }
    if let Some(p) = m.command_patterns.as_ref().filter(|v| !v.is_empty()) { parts.push(format!("command ~ {}", join(p))); }
    if parts.is_empty() { "any".into() } else { parts.join(" · ") }
}

/// `GET /api/policy` — the full editable policy state for the dashboard editor:
/// active preset, the preset's rules with their current override state, the
/// custom rules, and the available presets / categories / decisions.
async fn policy_get(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let ps = s.vault.policy();
    let resolved = ps.resolve().unwrap_or_else(|| crate::policy::get_preset("safety").unwrap().config);

    let preset_rules: Vec<_> = crate::policy::get_preset(&ps.active_preset)
        .map(|p| p.config.rules)
        .unwrap_or_default()
        .iter()
        .map(|r| {
            let ov = ps.overrides.get(&r.id);
            let decision = ov.and_then(|o| o.decision).unwrap_or(r.decision);
            let enabled = ov.and_then(|o| o.enabled).unwrap_or(true);
            serde_json::json!({
                "id": r.id,
                "name": r.name,
                "priority": r.priority,
                "default_decision": r.decision.as_str(),
                "decision": decision.as_str(),
                "enabled": enabled,
                "overridden": ov.is_some(),
                "match": match_summary(&r.r#match),
                "reason": r.reason,
            })
        })
        .collect();

    let presets: Vec<_> = crate::policy::list_presets()
        .iter()
        .map(|p| serde_json::json!({"name": p.name, "description": p.description}))
        .collect();

    Json(serde_json::json!({
        "active_preset": ps.active_preset,
        "enforce": resolved.enforce,
        "default_policy": resolved.default_policy.as_str(),
        "presets": presets,
        "categories": POLICY_CATEGORIES,
        "decisions": ["allow", "warn", "deny"],
        "preset_rules": preset_rules,
        "custom_rules": ps.custom_rules,
    }))
}

async fn policy_set_preset(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let preset = body.get("preset").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if !crate::policy::is_preset_name(&preset) {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": format!("unknown preset: {preset}")})));
    }
    let mut s = state.lock().await;
    match s.vault.set_active_preset(&preset) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain("policy_edit", serde_json::json!({"change": "preset", "preset": preset}));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "preset": preset})))
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

#[derive(serde::Deserialize)]
struct OverrideBody {
    rule_id: String,
    /// `"allow" | "warn" | "deny"`, or omit to leave the decision unchanged.
    decision: Option<String>,
    /// `false` disables the rule; omit to leave enabled-state unchanged.
    enabled: Option<bool>,
}

/// `PUT /api/policy/override` — override a *preset* rule's decision / enabled
/// state (the "edit specifically" path for built-in rules).
async fn policy_set_override(
    State(state): State<SharedState>,
    Json(body): Json<OverrideBody>,
) -> impl IntoResponse {
    let decision = match body.decision.as_deref() {
        None => None,
        Some(d) => match parse_decision(d) {
            Some(pd) => Some(pd),
            None => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": format!("unknown decision: {d}")}))),
        },
    };
    let ov = crate::vault::PolicyOverride { decision, enabled: body.enabled };
    let mut s = state.lock().await;
    match s.vault.set_policy_override(&body.rule_id, ov) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain("policy_edit", serde_json::json!({
                "change": "override", "rule_id": body.rule_id,
                "decision": body.decision, "enabled": body.enabled,
            }));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "rule_id": body.rule_id})))
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

/// `DELETE /api/policy/override/{rule_id}` — revert a preset rule to its default.
async fn policy_clear_override(
    State(state): State<SharedState>,
    Path(rule_id): Path<String>,
) -> impl IntoResponse {
    let mut s = state.lock().await;
    match s.vault.clear_policy_override(&rule_id) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain("policy_edit", serde_json::json!({"change": "clear_override", "rule_id": rule_id}));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "rule_id": rule_id})))
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

/// `PUT /api/policy/rule` — add or replace (by `id`) a custom rule. The body is
/// a full `PolicyRule`; its `match` may be by category or by tool/pattern (the
/// "edit by category or specifically" path).
async fn policy_upsert_rule(
    State(state): State<SharedState>,
    Json(rule): Json<crate::policy::PolicyRule>,
) -> impl IntoResponse {
    if rule.id.trim().is_empty() || rule.name.trim().is_empty() {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": "rule id and name are required"})));
    }
    let rule_id = rule.id.clone();
    let mut s = state.lock().await;
    match s.vault.upsert_custom_rule(rule) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain("policy_edit", serde_json::json!({"change": "upsert_rule", "rule_id": rule_id}));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "rule_id": rule_id})))
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

/// `DELETE /api/policy/rule/{rule_id}` — remove a custom rule.
async fn policy_delete_rule(
    State(state): State<SharedState>,
    Path(rule_id): Path<String>,
) -> impl IntoResponse {
    let mut s = state.lock().await;
    match s.vault.remove_custom_rule(&rule_id) {
        Ok(removed) => {
            s.reload_policy();
            let _ = s.append_chain("policy_edit", serde_json::json!({"change": "delete_rule", "rule_id": rule_id, "removed": removed}));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "removed": removed})))
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

/// `POST /api/orchestrators/{id}/connect` — connect a running-but-not-engaged
/// orchestrator by installing its hestia plugin.
async fn orchestrator_connect(
    State(state): State<SharedState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match crate::orchestrators::install(&id) {
        Ok(msg) => {
            let s = state.lock().await;
            let _ = s.append_chain("orchestrator_connect", serde_json::json!({"id": id, "status": msg}));
            (StatusCode::OK, Json(serde_json::json!({"ok": true, "message": msg})))
        }
        Err(e) => (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": e.to_string()}))),
    }
}

// --- Chain endpoints ---

#[derive(serde::Deserialize, Default)]
struct ChainQuery {
    limit: Option<u64>,
    event_type: Option<String>,
    tool: Option<String>,
    /// Calendar window: hour | day | week | all. When set, entries are
    /// selected by calendar time (capped) BEFORE the event/tool filters run —
    /// a count-first window makes filtered views shrink as other signers
    /// churn (the filtered-window illusion).
    range: Option<String>,
}

async fn chain_query(
    State(state): State<SharedState>,
    Query(q): Query<ChainQuery>,
) -> impl IntoResponse {
    let s = state.lock().await;
    let now = chrono::Utc::now();
    let (cutoff, default_cap) = match q.range.as_deref() {
        Some("hour") => (Some(now - chrono::Duration::hours(1)), 2_000),
        Some("day") => (Some(now - chrono::Duration::days(1)), 5_000),
        Some("week") => (Some(now - chrono::Duration::weeks(1)), 10_000),
        Some("all") => (None, 10_000),
        _ => (None, 50), // legacy: no range → old count-window behavior
    };
    let limit = q.limit.unwrap_or(default_cap);
    let cutoff_str = cutoff.map(|c: chrono::DateTime<chrono::Utc>| c.to_rfc3339());
    let entries: Vec<super::dashboard::RecentEntry> = s.chain_store
        .read_recent_window(cutoff_str.as_deref(), limit)
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
