//! HTTP transport for the Hestia MCP server.
//!
//! Mounts two surfaces on the same listener:
//!   /mcp/*           — the MCP StreamableHttp surface (plugin path)
//!   /                — embedded HTML dashboard (operator path)
//!   /api/dashboard   — JSON snapshot consumed by the dashboard + TUI

use anyhow::{Context, Result};
use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode, header},
    response::{Html, IntoResponse, Json},
    routing::{delete, get, post, put},
};
use rmcp::transport::streamable_http_server::{
    StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use web4_core::oid4vc::{CredentialIssuerMetadata, CredentialRequest, verify_holder_proof};
use web4_core::sd_jwt_vc::SdJwtVc;

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
    s.operator_challenges
        .gc(now, super::operator_auth::CHALLENGE_TTL_SECS);
    (
        StatusCode::OK,
        Json(serde_json::json!({ "challenge": challenge })),
    )
}

/// `POST /api/operator/session` {lct_id, challenge, signature} → open an operator
/// session on a verified LCT signature. Returns an opaque bearer token for
/// reversible acts; the irreversible tail re-collects fresh signatures per act.
async fn operator_session(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    use super::operator_auth::{
        OperatorProvenance, OperatorSessionProof, SESSION_TRANSCRIPT_DOMAIN,
        operator_session_opened_record,
    };

    let composed = [
        "actor",
        "principal",
        "via_device",
        "office",
        "authority",
        "actor_public_key",
        "device_public_key",
        "actor_signature",
        "device_signature",
    ]
    .iter()
    .any(|field| body.get(field).is_some());
    let proof = if composed {
        let required = |field: &str| {
            body.get(field)
                .and_then(|v| v.as_str())
                .filter(|v| !v.is_empty())
                .map(str::to_string)
        };
        let Some(actor) = required("actor") else {
            return bad_operator_session("composed session is missing actor");
        };
        let Some(principal) = required("principal") else {
            return bad_operator_session("composed session is missing principal");
        };
        let Some(via_device) = required("via_device") else {
            return bad_operator_session("composed session is missing via_device");
        };
        let Some(office) = required("office") else {
            return bad_operator_session("composed session is missing office");
        };
        let Some(authority) = required("authority") else {
            return bad_operator_session("composed session is missing authority");
        };
        let candidate = OperatorProvenance {
            actor,
            principal,
            via_device,
            office,
            authority,
        };
        if let Err(reason) = candidate.validate() {
            return bad_operator_session(reason);
        }
        if body.get("lct_id").and_then(|v| v.as_str()) != Some(candidate.principal.as_str()) {
            return bad_operator_session("lct_id must exactly equal principal");
        }
        if body.get("transcript").and_then(|v| v.as_str()) != Some(SESSION_TRANSCRIPT_DOMAIN) {
            return bad_operator_session("unsupported or missing operator-session transcript");
        }
        let Some(actor_public_key) = required("actor_public_key") else {
            return bad_operator_session("composed session is missing actor_public_key");
        };
        let Some(device_public_key) = required("device_public_key") else {
            return bad_operator_session("composed session is missing device_public_key");
        };
        let Some(actor_signature) = required("actor_signature") else {
            return bad_operator_session("composed session is missing actor_signature");
        };
        let Some(device_signature) = required("device_signature") else {
            return bad_operator_session("composed session is missing device_signature");
        };
        Some((
            candidate,
            actor_public_key,
            device_public_key,
            actor_signature,
            device_signature,
        ))
    } else {
        None
    };
    let (principal, challenge, signature) = (
        proof
            .as_ref()
            .map(|p| p.0.principal.as_str())
            .unwrap_or_else(|| body.get("lct_id").and_then(|v| v.as_str()).unwrap_or("")),
        body.get("challenge").and_then(|v| v.as_str()).unwrap_or(""),
        body.get("signature").and_then(|v| v.as_str()).unwrap_or(""),
    );
    let now = super::state::unix_now();
    let mut s = state.lock().await;
    let law = s.vault.policy().clone();
    let authed = match proof.as_ref() {
        Some((provenance, actor_key, device_key, actor_sig, device_sig)) => {
            super::operator_auth::authenticate_composed_operator(
                &law,
                &mut s.operator_challenges,
                provenance,
                challenge,
                actor_key,
                device_key,
                signature,
                actor_sig,
                device_sig,
                now,
                super::operator_auth::CHALLENGE_TTL_SECS,
            )
            .map(|(lct_id, principal_public_key)| (lct_id, Some(principal_public_key)))
        }
        None => super::operator_auth::authenticate_operator(
            &law,
            &mut s.operator_challenges,
            principal,
            challenge,
            signature,
            now,
            super::operator_auth::CHALLENGE_TTL_SECS,
        )
        .map(|lct_id| (lct_id, None)),
    };
    match authed {
        Some((op, principal_public_key)) => {
            let (token, record, session_ref) = match proof {
                Some((provenance, actor_key, device_key, actor_sig, device_sig)) => {
                    // Authentication above proved every identity named in the tuple.
                    debug_assert_eq!(provenance.principal, op);
                    let session_proof = OperatorSessionProof::new(
                        challenge,
                        &provenance,
                        principal_public_key
                            .as_deref()
                            .expect("composed authentication returns its authorized key"),
                        &actor_key,
                        &device_key,
                        signature,
                        &actor_sig,
                        &device_sig,
                    );
                    let record = operator_session_opened_record(&provenance, &session_proof);
                    let session_ref = Some(provenance.authority.clone());
                    (
                        s.operator_sessions.open(provenance, now),
                        record,
                        session_ref,
                    )
                }
                None => (
                    s.operator_sessions.open(op.clone(), now),
                    serde_json::json!({
                        "operator": op,
                        "evidence": "operator-lct-signature",
                    }),
                    None,
                ),
            };
            let _ = s.append_chain("operator_session_opened", record);
            (
                StatusCode::OK,
                Json(serde_json::json!({
                    "token": token,
                    "operator": op,
                    "session_ref": session_ref,
                })),
            )
        }
        None => (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({ "error": "operator authentication failed" })),
        ),
    }
}

fn bad_operator_session(reason: &str) -> (StatusCode, Json<serde_json::Value>) {
    (
        StatusCode::BAD_REQUEST,
        Json(serde_json::json!({ "error": reason })),
    )
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
    use super::operator_auth::{AuthzOutcome, Stakes, gate_session_request};

    let method = req.method().as_str().to_string();
    let path = req.uri().path().to_string();
    let stakes = Stakes::classify(&method, &path);

    // Dev-only named override — the explicit unsafe escape hatch, refused in the
    // production profile, and loud + witnessed when used. Never the front door.
    let dev_override = std::env::var("HESTIA_OPERATOR_DEV_TOKEN")
        .ok()
        .filter(|t| !t.is_empty());
    let production = std::env::var("HESTIA_PROFILE")
        .map(|p| p == "production")
        .unwrap_or(false);
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
            eprintln!(
                "[hestia] WARNING: operator dev-override used on {method} {path} (dev-only, unsafe)"
            );
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
    let (outcome, provenance) = {
        let s = state.lock().await;
        let law = s.vault.policy();
        let operator = bearer
            .as_deref()
            .and_then(|t| {
                s.operator_sessions
                    .operator(t, now, super::operator_auth::SESSION_TTL_SECS)
            })
            .map(str::to_string);
        let provenance = bearer
            .as_deref()
            .and_then(|t| {
                s.operator_sessions
                    .provenance(t, now, super::operator_auth::SESSION_TTL_SECS)
            })
            .cloned();
        (
            gate_session_request(law, operator.as_deref(), stakes),
            provenance,
        )
    };

    // Self-witness the authorization decision (A) for consequential acts (skip the
    // low-stakes read flood).
    if !matches!(stakes, Stakes::LowReversible) {
        let mut s = state.lock().await;
        let _ = s.append_chain(
            "operator_gate",
            super::operator_auth::attach_operator_provenance(
                outcome.evidence_record(&format!("{method} {path}")),
                provenance.as_ref(),
            ),
        );
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
        AuthzOutcome::Denied { reason, .. } => (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({ "error": reason })),
        )
            .into_response(),
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
        .route("/api/hub/status", get(super::hub_tab::hub_status))
        .route(
            "/api/hub/urls",
            get(super::hub_tab::hub_urls_list)
                .post(super::hub_tab::hub_urls_add)
                .delete(super::hub_tab::hub_urls_remove),
        )
        .route(
            "/api/hub/urls/active",
            axum::routing::put(super::hub_tab::hub_urls_set_active),
        )
        .route("/api/hub/join", post(super::hub_tab::hub_join))
        .route("/api/hub/topics", get(super::hub_tab::hub_topics))
        .route("/api/hub/topic", post(super::hub_tab::hub_topic_create))
        .route("/api/hub/post", post(super::hub_tab::hub_post))
        .route("/api/trust/derivation", get(trust_derivation_json))
        .route("/api/trust/graph", get(trust_graph_turtle))
        .route("/api/operator/adjudicate", post(operator_adjudicate))
        .route(
            "/api/operator/gate-escalation",
            post(operator_gate_escalation),
        )
        .route("/api/operator/alias", post(operator_alias))
        .route("/api/operator/amnesty", post(operator_amnesty))
        .route("/api/failures", get(failures_json))
        .route("/api/vault", get(vault_list).post(vault_add))
        .route("/api/vault/:name", delete(vault_delete))
        .route("/api/policy", get(policy_get))
        // Per-member grants. Behind the operator gate like every other /api route, and
        // DELIBERATELY absent from the MCP tool list: an agent must not be able to change its
        // own policy or another agent's, so the only way in is a challenge-signed operator
        // session. `no_mcp_tool_can_set_an_operator_grant` asserts that rather than trusting
        // that nobody adds the tool later.
        .route("/api/policy/instance", post(policy_set_instance_grant))
        .route(
            "/api/policy/instance/:plugin_id/:role",
            delete(policy_revoke_instance_grant),
        )
        // Scope requests. The member half is MCP (`hestia_request_scope`); the deciding half is
        // here, behind the operator gate, for the same reason the grant above is: a member that
        // could answer its own ask would be holding both halves of the control.
        .route("/api/scope/requests", get(scope_list_requests))
        .route("/api/scope/decide", post(scope_decide))
        // The durable channel's revoke verb (Sprint F R1). Same wall, same reasoning: a
        // member that could revoke — or, worse, could NOT be revoked — would hold the
        // control.
        .route("/api/scope/standing/revoke", post(scope_standing_revoke))
        // THE GRANT HALF NOW HAS A ROUTE, REVERSING A DELIBERATE DECISION RECORDED HERE.
        //
        // What stood here said: "The GRANT half deliberately has no route of its own: a
        // standing grant is only ever a promotion of a member's witnessed ask, through
        // /api/scope/decide {standing:true}, so the ask and its durable answer stay paired."
        //
        // The pairing was worth wanting and the mechanism was the wrong way to get it. Making
        // the ONLY widening door an answer-to-an-ask made the operator's composing power
        // derivative of a member act — ratify, never originate — against this society's own
        // rule that only an operator-walled act may compose upward. The restart of
        // 2026-08-15 showed what that costs: every member's envelope empty, the remedy
        // (`hestia_request_scope`) denied by the very emptiness it exists to fill, and the
        // operator holding no verb that could reach in from outside the cycle. The single
        // grant that landed did so only because a member routed around its own gate to file
        // the ask. A door reachable only from inside a room nobody can enter is not a door.
        //
        // The pairing's EVIDENTIARY value is kept, which is what actually mattered: a
        // ratification carries a `request_id` and the ask it answered; an originated grant
        // carries `request_id: null` and `origin: "operator_initiated"`. A reader can always
        // tell them apart. What is gone is the DEPENDENCY, not the distinction.
        .route("/api/scope/grant", post(scope_grant))
        // THE SOCIETY FLOOR (dp, 2026-08-16). Same operator wall as every other widening, and
        // deliberately NOT reachable from MCP: a member that could edit the floor could widen
        // itself AND every peer in one act, which is the largest privilege escalation this
        // codebase could offer. The floor is the one list that must be editable from exactly
        // one direction.
        .route("/api/scope/floor", post(scope_floor_add))
        .route("/api/scope/floor/remove", post(scope_floor_remove))
        .route("/api/policy/preset", put(policy_set_preset))
        .route("/api/policy/override", put(policy_set_override))
        .route(
            "/api/policy/override/:rule_id",
            delete(policy_clear_override),
        )
        .route("/api/policy/rule", put(policy_upsert_rule))
        .route("/api/policy/rule/:rule_id", delete(policy_delete_rule))
        .route("/api/orchestrators/:id/connect", post(orchestrator_connect))
        .route("/api/agents", get(agents_inventory))
        .route("/api/gates/verify", get(gates_verify))
        .route("/api/gates/ratify", post(gates_ratify))
        .route("/api/agents/:id/ungovern", post(agent_ungovern))
        .route("/api/chain", get(chain_query))
        // The admin ledger — governance history with status facets. Operator-gated for the same
        // reason /api/chain is: it is the society's whole record of who ruled on what.
        .route("/api/governance/ledger", get(governance_ledger))
        // OID4VCI issuance MINTS a presentation SIGNED WITH THE OWNER'S IDENTITY KEY — a consequential
        // act that must be owner-authorized. Fail-closed stopgap (PRD §5.6/§7.1; Nomad's finding, dp's
        // §12 disposition): gate it behind the operator session like every other consequential surface,
        // closing the ungated "any local caller mints an owner-signed claim" hole. `/metadata` + `/nonce`
        // stay open below (discovery + a freshness nonce grant nothing). The full OID4VCI delegation authz
        // — what a wallet flow should require — is a separate design (§8 item b); this only refuses
        // unauthorized minting, it does not decide the wallet flow.
        .route("/credential", post(vci_credential))
        .route_layer(axum::middleware::from_fn_with_state(
            state.clone(),
            operator_gate,
        ));

    // The disposition worker (#459; reshaped to the revised #480 review): the
    // daemon's only periodic task. Two halves per tick:
    //
    // 1. LAPSE RECORDING takes the outer lock briefly — it reads the bounded live
    //    escalation store and appends a `gate_escalation_expired` only when a row
    //    crossed its deadline unruled. Steady state: a small scan, zero appends.
    // 2. PROJECTION never touches the outer lock at all. It pages the witness
    //    chain after a durable cursor (≤ DISPOSITION_PROJECTION_PAGE positions)
    //    on the chain store's OWN connection and writes obligations to inbox.db
    //    on ITS own connection — the r2 sweep materialised 20k entries under the
    //    global lock every pass, the gate-starving shape #488/#482 flagged; this
    //    is the work-queue shape the review asked for instead.
    //
    // Spawned before `app` below moves `state`.
    let (chain_handle, inbox_handle) = {
        let s = state.lock().await;
        (s.chain_store.clone(), s.inbox_store.clone())
    };
    let lapse_state = state.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(
            super::handler::DISPOSITION_RECONCILE_INTERVAL_SECS,
        ));
        loop {
            tick.tick().await;
            let now = super::gate_escalation::now_secs();
            let lapsed = {
                let mut s = lapse_state.lock().await;
                super::handler::record_newly_lapsed(&mut s, now)
            };
            match super::handler::project_dispositions(&chain_handle, &inbox_handle) {
                Ok(p) if p.projected > 0 || lapsed > 0 => {
                    tracing::info!(
                        projected = p.projected,
                        lapsed,
                        cursor = p.advanced_to,
                        "disposition worker closed open obligations"
                    );
                }
                Ok(_) => {}
                Err(e) => tracing::warn!("disposition projector: {e}"),
            }
        }
    });

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
        // /metadata + /nonce are legitimately unauthenticated (discovery + a freshness
        // nonce grant nothing). /credential — which mints an OWNER-SIGNED presentation —
        // was moved behind the operator gate above (fail-closed stopgap, PRD §5.6) and is
        // deliberately NOT mounted here anymore.
        .route("/.well-known/openid-credential-issuer", get(vci_metadata))
        .route("/nonce", post(vci_nonce))
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
        [
            (header::CONTENT_TYPE, "text/html; charset=utf-8"),
            // NO-STORE. The page shipped with no Cache-Control, no ETag and no Last-Modified, so
            // a browser is free to heuristically cache it — and this page is a single HTML file
            // containing all of its own JavaScript, redeployed constantly. The operator then
            // reads a stale UI against a current daemon and cannot tell that apart from a broken
            // feature.
            //
            // That is not hypothetical: it cost a long debugging detour on 2026-08-01. The grant
            // was live, the daemon was applying it (`layers: ["operator-grant"]`), and the
            // dashboard kept reporting the society baseline. Two fixes went into the UI before
            // the question "is the browser running the code I deployed?" got asked — and the
            // answer had been unfalsifiable the whole time, because nothing in the response said
            // how old the page was.
            //
            // A governance console must never be able to show a stale reading of state that the
            // operator is about to make decisions from.
            (header::CACHE_CONTROL, "no-store, must-revalidate"),
        ],
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
                concat!(
                    env!("CARGO_MANIFEST_DIR"),
                    "/src/server/dashboard/index.html"
                )
                .to_string(),
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

#[derive(serde::Deserialize)]
struct DerivationQuery {
    plugin_id: String,
    #[serde(default)]
    role: Option<String>,
}

/// The RECEIPTS endpoint (Stage 2): score -> versioned formula -> evidence
/// pointers -> witnessed acts, computed at read time over the chain window.
/// This is the auditable-trust contract made clickable.
#[derive(serde::Deserialize)]
struct OperatorIdentityAlias {
    /// The identity that should OWN the evidence (the surviving member).
    alias_of: String,
    /// The identity whose evidence folds into it (the mis-reported one).
    alias: String,
    #[serde(rename = "ref")]
    evidence_ref: String,
    #[serde(default)]
    reason: Option<String>,
}

#[derive(serde::Deserialize)]
struct OperatorAdjudication {
    subject_plugin_id: String,
    subject_role: String,
    axis: String, // validity | valuation (veracity stays daemon-computed via the plugin tool)
    verdict: String, // upheld | partial | refuted | deferred
    #[serde(rename = "ref")]
    evidence_ref: String,
    #[serde(default)]
    score: Option<f64>,
    #[serde(default)]
    reason: Option<String>,
    #[serde(default)]
    method: Option<String>, // defaults to "review"
}

/// The HUMAN's adjudication surface (dp 2026-07-24: "i would rate you 1.0
/// personally" — the most trusted witness in the system had no way to witness
/// that). Operator-session-gated (the /api operator_gate preflight has already
/// authenticated the sovereign's challenge-signed session before this runs);
/// the adjudication is recorded with the SOVEREIGN as adjudicator. Temperament
/// stays conduct-derived — a human rating enters as validity/valuation, never
/// as a hand-set temperament (that would be prescribed trust again).
/// `POST /api/operator/alias` — record that two plugin_ids are the SAME member, so
/// derivation folds their evidence together.
///
/// Consequential: it joins trust records, so it is operator-gated like adjudication and
/// carries an evidence pointer. It is an APPEND, never a rewrite — history stays where it
/// landed and `derivation::aliased_identities` follows the record at read time. Refuses a
/// self-alias, and refuses without a pointer: no evidence, no join.
///
/// surface: operator identity-alias   act: join two identities' trust evidence
/// S: high/reversible [construct: append-only; a later contradicting alias supersedes, nothing is edited]
/// R: n/a [construct: no reachability-based authority]
/// W: pass [construct: operator_gate — LCT-signed session, same bar as adjudicate]
/// O: pass [construct: all validation precedes append_chain, the only side effect]
/// A: pass [construct: single append_chain carrying alias, alias_of, ref and reason]
/// V: n/a [construct: reversible — supersede by appending, no data destroyed]
/// verdict: PASS
async fn operator_alias(
    State(state): State<SharedState>,
    Json(a): Json<OperatorIdentityAlias>,
) -> impl IntoResponse {
    if a.alias.trim().is_empty() || a.alias_of.trim().is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "alias and alias_of are both required"})),
        )
            .into_response();
    }
    if a.alias == a.alias_of {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "an identity cannot be an alias of itself"})),
        )
            .into_response();
    }
    if a.evidence_ref.is_empty()
        || a.evidence_ref.len() > 512
        || a.evidence_ref.chars().any(char::is_control)
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "'ref' must be a single-line evidence pointer (<=512 bytes) — \
                      joining two identities' evidence needs a stated basis"})),
        )
            .into_response();
    }
    let mut s = state.lock().await;
    let entry = match s.append_chain(
        crate::derivation::IDENTITY_ALIAS_EVENT,
        serde_json::json!({
            "alias": a.alias,
            "alias_of": a.alias_of,
            "ref": a.evidence_ref,
            "reason": a.reason,
            "recorded_by": "operator",
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({"error": format!("witnessing: {e}")})),
            )
                .into_response();
        }
    };
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "alias": a.alias,
            "alias_of": a.alias_of,
            "witnessEntryHash": entry.hash,
            "note": "evidence folds at READ time; nothing was rewritten"
        })),
    )
        .into_response()
}

async fn operator_adjudicate(
    State(state): State<SharedState>,
    Json(a): Json<OperatorAdjudication>,
) -> impl IntoResponse {
    if !matches!(a.axis.as_str(), "validity" | "valuation") {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "operator adjudications cover axis validity|valuation \
                      (veracity is daemon-computed calibration; temperament is conduct-derived)"})),
        )
            .into_response();
    }
    if !matches!(
        a.verdict.as_str(),
        "upheld" | "partial" | "refuted" | "deferred"
    ) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "verdict must be upheld|partial|refuted|deferred"})),
        )
            .into_response();
    }
    if a.evidence_ref.is_empty()
        || a.evidence_ref.len() > 512
        || a.evidence_ref.chars().any(char::is_control)
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "'ref' must be a single-line evidence pointer (<=512 bytes) — \
                      no pointer, no adjudication"})),
        )
            .into_response();
    }
    let role = crate::reputation::normalize_constellation_role(&a.subject_role);
    let score = match a.verdict.as_str() {
        "deferred" => None,
        "upheld" => Some(a.score.unwrap_or(1.0).clamp(0.0, 1.0)),
        "partial" => Some(a.score.unwrap_or(0.5).clamp(0.0, 1.0)),
        _ => Some(a.score.unwrap_or(0.0).clamp(0.0, 1.0)),
    };
    let dimension = if a.axis == "validity" {
        web4_core::v3::ValueDimension::Validity
    } else {
        web4_core::v3::ValueDimension::Valuation
    };
    let s = state.lock().await;
    let subject_instance_lct = s.member_lct(&a.subject_plugin_id);
    let entry = match s.append_chain(
        "adjudication",
        serde_json::json!({
            "subject_plugin_id": a.subject_plugin_id,
            "subject_instance_lct": subject_instance_lct,
            "subject_role": role,
            "axis": a.axis,
            "verdict": a.verdict,
            "score": score,
            "method": a.method.clone().unwrap_or_else(|| "review".to_string()),
            "ref": a.evidence_ref,
            "reason": a.reason,
            "adjudicated_by": {
                "operator": true,
                "sovereign_lct_id": s.sovereign.lct_id(),
                "role_lct": s.sovereign.sovereign_role_id(),
            },
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({"error": format!("witnessing: {e}")})),
            )
                .into_response();
        }
    };
    let mut updated = None;
    if let Some(score) = score {
        let adj_reason = format!("adjudication:{}:{}:operator", a.axis, a.verdict);
        let rep_ctx = crate::reputation::RepContext {
            // An OPERATOR adjudication: a human judgment about conduct, the
            // strongest causal provenance in this set.
            class: crate::reputation::DeltaClass::Conduct,
            role_lct: role,
            action_type: "adjudication",
            action_target: "operator",
            action_id: "",
            rule_triggered: "",
            reason: &adj_reason,
        };
        match s.apply_adjudication_ctx(&a.subject_plugin_id, dimension, score, &rep_ctx) {
            Ok(t) => updated = Some(t.entity_id),
            Err(e) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({"error": format!("applying: {e}"),
                        "witnessEntryHash": entry.hash})),
                )
                    .into_response();
            }
        }
    }
    Json(serde_json::json!({
        "witnessEntryHash": entry.hash,
        "axis": a.axis, "verdict": a.verdict, "score": score,
        "adjudicatedEntity": updated,
    }))
    .into_response()
}

#[derive(serde::Deserialize)]
struct AmnestyRequest {
    /// Currently only "deny" (conduct-class amnesty).
    class: String,
    /// Denies with chain_position strictly below this are excluded from conduct.
    before_position: u64,
    reason: String,
    /// Evidence pointer (e.g. the fix commit that ended the era being amnestied).
    #[serde(rename = "ref")]
    evidence_ref: String,
}

/// Sovereign amnesty (dp 2026-07-24: rehab/repair policy). A SOCIETY-level act:
/// excludes a class of historical conduct from derivation — history is never
/// deleted; the amnesty is itself a witnessed act and every excluded item shows
/// in receipts with the amnesty as its reason. Operator-session-gated (the
/// /api operator_gate preflight authenticated the sovereign before this runs).
async fn operator_amnesty(
    State(state): State<SharedState>,
    Json(a): Json<AmnestyRequest>,
) -> impl IntoResponse {
    if a.class != "deny" {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "only class 'deny' is amnestiable in v1"})),
        )
            .into_response();
    }
    if a.reason.trim().is_empty() || a.evidence_ref.is_empty() || a.evidence_ref.len() > 512 {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
            "error": "amnesty requires a reason and a single-line evidence ref"})),
        )
            .into_response();
    }
    let s = state.lock().await;
    match s.append_chain(
        "amnesty",
        serde_json::json!({
            "data": {
                "class": a.class,
                "before_position": a.before_position,
                "reason": a.reason,
                "ref": a.evidence_ref,
            },
            "declared_by": {
                "operator": true,
                "sovereign_lct_id": s.sovereign.lct_id(),
                "role_lct": s.sovereign.sovereign_role_id(),
            },
        }),
    ) {
        Ok(e) => Json(serde_json::json!({"witnessEntryHash": e.hash,
            "excludes": format!("denies before #{}", a.before_position)}))
        .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": format!("witnessing: {e}")})),
        )
            .into_response(),
    }
}

async fn trust_derivation_json(
    State(state): State<SharedState>,
    Query(q): Query<DerivationQuery>,
) -> impl IntoResponse {
    let s = state.lock().await;
    let role = q
        .role
        .unwrap_or_else(|| "role:constellation:interactive-dev".to_string());
    let window = s
        .chain_store
        // Fetch what the model DECLARES it reads, projected — not the whole window.
        // `DERIVATION_EVENT_TYPES` filters in SQL (indexed) and `project_row` retains
        // only `DERIVATION_KEYS`, so this stops materialising documents nobody folds.
        .scan_recent(
            None,
            Some(crate::derivation::DERIVATION_EVENT_TYPES),
            crate::derivation::DERIVATION_SCAN,
            crate::derivation::project_row,
        )
        .unwrap_or_default();
    let derived = crate::derivation::derive(&q.plugin_id, &role, &window);
    drop(s);
    Json(serde_json::to_value(derived).unwrap_or_default())
}

/// The same derived trust as `/api/trust/derivation`, projected into the Web4 T3/V3
/// ontology as Turtle — `role@agent` as two edges, one `DimensionScore` per MEASURED
/// dimension, each traversable back to the chain entries that produced it.
///
/// Served as `text/turtle` so a relying party can pipe it straight into a triple store and
/// ask sufficiency questions of it, rather than parsing our JSON and trusting our field
/// names. That independence is the point: the graph is the portable object, this daemon is
/// just what happened to emit it.
async fn trust_graph_turtle(
    State(state): State<SharedState>,
    Query(q): Query<DerivationQuery>,
) -> impl IntoResponse {
    let s = state.lock().await;
    let role = q
        .role
        .unwrap_or_else(|| "role:constellation:interactive-dev".to_string());
    let window = s
        .chain_store
        // Fetch what the model DECLARES it reads, projected — not the whole window.
        // `DERIVATION_EVENT_TYPES` filters in SQL (indexed) and `project_row` retains
        // only `DERIVATION_KEYS`, so this stops materialising documents nobody folds.
        .scan_recent(
            None,
            Some(crate::derivation::DERIVATION_EVENT_TYPES),
            crate::derivation::DERIVATION_SCAN,
            crate::derivation::project_row,
        )
        .unwrap_or_default();
    let derived = crate::derivation::derive(&q.plugin_id, &role, &window);
    // The DURABLE member LCT, never the caller-supplied plugin_id — emitting the label here
    // would encode the attribution gap into the graph this projection exists to close.
    // Unmappable (synthetic / malformed) grains get an explicit urn rather than a guess.
    let entity_lct = s
        .member_lct(&q.plugin_id)
        .unwrap_or_else(|| format!("urn:hestia:unmapped:{}", q.plugin_id));
    drop(s);
    let ttl = crate::rdf::trust_to_turtle(&derived, &entity_lct);
    (
        [(
            axum::http::header::CONTENT_TYPE,
            "text/turtle; charset=utf-8",
        )],
        ttl,
    )
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
    let entries: Vec<serde_json::Value> = names
        .iter()
        .filter_map(|name| {
            s.vault.get(name).map(|e| {
                serde_json::json!({
                    "id": name,
                    "name": name,
                    "scope": e.scope,
                    "tags": e.tags,
                    "allowed_consumers": e.allowed_consumers,
                    // HST-001: empty consumer list == readable by any caller. Surfaced so an
                    // operator can see and close exposures rather than discovering them.
                    "exposed": e.allowed_consumers.is_empty(),
                    "created_at": e.created_at,
                    "last_rotated": e.last_rotated,
                })
            })
        })
        .collect();
    Json(serde_json::json!({ "entries": entries }))
}

async fn vault_add(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let name = body.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let value = body.get("value").and_then(|v| v.as_str()).unwrap_or("");
    if name.is_empty() || value.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "name and value required"})),
        );
    }
    let scope: Vec<String> = body
        .get("scope")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();
    let tags: Vec<String> = body
        .get("tags")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();
    let consumers: Vec<String> = body
        .get("allowed_consumers")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();

    let entry = crate::vault::VaultEntry::new(name, value)
        .with_scope(scope)
        .with_tags(tags)
        .with_consumers(consumers);

    let mut s = state.lock().await;
    match s.vault.add(entry) {
        Ok(()) => (StatusCode::OK, Json(serde_json::json!({"ok": true}))),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
        None => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({"error":"proof missing nonce"})),
            );
        }
    };

    let mut s = state.lock().await;

    // Single-use: must be a nonce we issued; consume it.
    if !s.vci_nonces.remove(&proof_nonce) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"unknown or used c_nonce"})),
        );
    }

    // Verify the holder key-possession proof (aud = us, fresh).
    let holder_pk = match verify_holder_proof(&req.proof_jwt, &base, &proof_nonce, 300, now) {
        Ok(pk) => pk,
        Err(e) => {
            return (
                StatusCode::UNAUTHORIZED,
                Json(serde_json::json!({"error": e})),
            );
        }
    };

    // Load the daemon's issuer identity from the vault (init --ai).
    let (issuer_lct, issuer_key) = match s.vault.get("ai_identity_secret").map(|e| e.secret.clone())
    {
        Some(hex) => {
            let lct = s
                .vault
                .get("ai_identity_lct_id")
                .map(|e| e.secret.clone())
                .unwrap_or_default();
            match hex32(&hex) {
                Some(b) => (lct, web4_core::crypto::KeyPair::from_secret_bytes(&b)),
                None => {
                    return (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(serde_json::json!({"error":"identity key malformed"})),
                    );
                }
            }
        }
        None => {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({"error":"no issuer identity — run `hestia init --ai`"})),
            );
        }
    };

    // Assurance level from the local constellation (ties the credential to the
    // device-constellation work); default single_device if none.
    let assurance = crate::constellation::ConstellationStore::load(&s.vault)
        .ok()
        .and_then(|st| serde_json::to_value(st.proof().assurance_level).ok())
        .and_then(|v| v.as_str().map(String::from))
        .unwrap_or_else(|| "single_device".into());

    let host = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("127.0.0.1:7711");
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

    // Witness the issuance (RWOA A): minting a claim signed with the owner's key is a consequential act
    // and must be on the chain, not just the write of a name. The operator gate (route_layer) did the
    // R+W preflight; this records the act it authorized.
    let _ = s.append_chain(
        "credential_issued",
        serde_json::json!({
            "vct": "Web4Presence",
            "issuer": issuer_did,
            "holder": format!("{holder_pk:?}"),
            "assurance_level": assurance,
            "evidence": "operator-gated + holder-proof",
        }),
    );
    (
        StatusCode::OK,
        Json(serde_json::json!({ "credential": credential, "format": "vc+sd-jwt" })),
    )
}

fn hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).ok()?;
    }
    Some(out)
}

// --- Policy endpoints ---

/// Tool categories the policy can match on (mirrors `policy::classify`).
const POLICY_CATEGORIES: &[&str] = &[
    "command",
    "file_read",
    "file_write",
    "network",
    "credential_access",
    "task_management",
];

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
    if let Some(t) = m.tools.as_ref().filter(|v| !v.is_empty()) {
        parts.push(format!("tools: {}", join(t)));
    }
    if let Some(c) = m.categories.as_ref().filter(|v| !v.is_empty()) {
        parts.push(format!("categories: {}", join(c)));
    }
    if let Some(p) = m.target_patterns.as_ref().filter(|v| !v.is_empty()) {
        parts.push(format!("target ~ {}", join(p)));
    }
    if let Some(p) = m.command_patterns.as_ref().filter(|v| !v.is_empty()) {
        parts.push(format!("command ~ {}", join(p)));
    }
    if parts.is_empty() {
        "any".into()
    } else {
        parts.join(" · ")
    }
}

/// `GET /api/policy` — the full editable policy state for the dashboard editor:
/// active preset, the preset's rules with their current override state, the
/// custom rules, and the available presets / categories / decisions.
async fn policy_get(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let ps = s.vault.policy();
    let resolved = ps
        .resolve()
        .unwrap_or_else(|| crate::policy::get_preset("safety").unwrap().config);

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

/// `POST /api/policy/instance` {plugin_id, role, preset, reason, expires_in_secs?}
///
/// Grant one member a preset in place of the local baseline — the operator's scoped exception,
/// so unblocking one agent no longer means setting the whole society permissive.
///
/// Witnessed, because this is the only control in the system that can WIDEN what an agent may
/// do. A tightening that goes unrecorded is an inconvenience; a loosening that goes unrecorded
/// is an unexplained capability in the chain later.
async fn policy_set_instance_grant(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    use crate::server::state::InstanceGrant;
    let sv = |k: &str| {
        body.get(k)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string()
    };
    let (plugin_id, role, preset, reason) =
        (sv("plugin_id"), sv("role"), sv("preset"), sv("reason"));
    if plugin_id.is_empty() || role.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "plugin_id and role are required"})),
        );
    }
    if !crate::policy::is_preset_name(&preset) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": format!("unknown preset: {preset}")})),
        );
    }
    // A reason is REQUIRED to widen, mirroring the escalation channel where approving needs a
    // stated why and refusing does not. Revocation (DELETE) needs none: tightening back toward
    // the baseline is the safe direction and should never be friction.
    if reason.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "reason is required — a grant is an exception to society law and the \
                          record has to say why it was made"
            })),
        );
    }
    let now = crate::server::gate_escalation::now_secs();
    let expires_at = body
        .get("expires_in_secs")
        .and_then(|v| v.as_u64())
        .map(|s| now + s);

    let mut s = state.lock().await;

    // THE DIRECTION DECIDES THE STORE (dp, 2026-08-01). Each half already had the right
    // mechanism; what was missing was routing to it.
    //
    //   TIGHTENING -> vault instance overlay. Persists across restarts and folds strictest-wins
    //                 with everything else, which is exactly what a restriction should do. A
    //                 member restricted for cause must not be freed by a reboot.
    //   LOOSENING  -> in-memory grant. Substitutes the local baseline and dies with the daemon,
    //                 so a permission nobody remembers to revoke expires on its own.
    //
    // Sending a tightening through the memory path would have made restrictions evaporate on
    // restart; sending a loosening through the vault would have made permissions permanent and
    // written to disk. Same control, opposite correct answers.
    let loosening = s.is_loosening(&preset);
    let durability = if loosening {
        s.instance_grants.insert(
            (plugin_id.clone(), role.clone()),
            InstanceGrant {
                preset: preset.clone(),
                granted_by: "operator".to_string(),
                granted_at: now,
                reason: reason.clone(),
                expires_at,
            },
        );
        "memory-only — a daemon restart revokes it"
    } else {
        // A tightening is expressed as the preset's own rules laid over this member, so it
        // composes with society law by the ordinary fold rather than replacing it.
        let rules = crate::policy::get_preset(&preset)
            .map(|p| p.config.rules)
            .unwrap_or_default();
        if let Err(e) = s.vault.set_instance_overlay(&plugin_id, &role, rules) {
            // Fail LOUD. A tightening that silently did not persist is the worst outcome
            // available here: the operator believes a member is restricted, the UI shows the
            // restriction until the next restart, and then it is simply gone.
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({"error": format!("vault write failed: {e}")})),
            );
        }
        s.reload_policy();
        "vault — survives a daemon restart"
    };
    let entry = s.append_chain(
        "policy_instance_grant",
        serde_json::json!({
            "plugin_id": plugin_id,
            "subject_instance_lct": s.member_lct(&plugin_id),
            "role": role,
            "preset": preset,
            "reason": reason,
            "expires_at": expires_at,
            "granted_by": "operator",
            "via": "operator_session",
            "direction": if loosening { "loosening" } else { "tightening" },
            "durability": durability,
        }),
    );
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true,
            "plugin_id": plugin_id,
            "role": role,
            "preset": preset,
            "expires_at": expires_at,
            "witnessEntryHash": entry.map(|e| e.hash).unwrap_or_default(),
            "direction": if loosening { "loosening" } else { "tightening" },
            "durability": durability,
        })),
    )
}

/// `DELETE /api/policy/instance/:plugin_id/:role` — revoke a grant, returning the member to the
/// society baseline. No reason required: tightening is the safe direction.
async fn policy_revoke_instance_grant(
    State(state): State<SharedState>,
    Path((plugin_id, role)): Path<(String, String)>,
) -> impl IntoResponse {
    let mut s = state.lock().await;
    let had = s
        .instance_grants
        .remove(&(plugin_id.clone(), role.clone()))
        .is_some();
    if had {
        let _ = s.append_chain(
            "policy_instance_grant_revoked",
            serde_json::json!({
                "plugin_id": plugin_id,
                "subject_instance_lct": s.member_lct(&plugin_id),
                "role": role,
                "via": "operator_session",
            }),
        );
    }
    (
        StatusCode::OK,
        Json(serde_json::json!({"ok": true, "revoked": had})),
    )
}

/// `GET /api/scope/requests` — every scope request, newest first, with everything needed to rule.
///
/// Carries the member's stated reason inline rather than an id the operator must go look up.
/// dp, 2026-08-02: *"the escalations currently don't provide enough information to actually make
/// an informed decision. that's a real issue."* A decision surface that shows only WHO and WHAT
/// invites approval-by-fatigue; the WHY is the field the ruling is actually about.
async fn scope_list_requests(State(state): State<SharedState>) -> impl IntoResponse {
    let now = crate::server::gate_escalation::now_secs();
    let s = state.lock().await;
    let mut all: Vec<&crate::server::state::ScopeRequest> = s.scope_requests.values().collect();
    all.sort_by_key(|r| std::cmp::Reverse(r.requested_at));
    let items: Vec<serde_json::Value> = all
        .iter()
        .map(|r| {
            serde_json::json!({
                "request_id": r.id,
                "plugin_id": r.plugin_id,
                "role": r.role,
                "path": r.path,
                "reason": r.reason,
                "status": r.status(now),
                "requested_at": r.requested_at,
                "expires_at": r.expires_at,
                "decided_by": r.decided_by,
                "decided_at": r.decided_at,
                "decision_reason": r.decision_reason,
            })
        })
        .collect();
    let pending = items.iter().filter(|i| i["status"] == "pending").count();
    (
        StatusCode::OK,
        Json(serde_json::json!({"requests": items, "pending": pending})),
    )
}

/// `POST /api/scope/decide` {request_id, granted, reason?, expires_in_secs?, standing?}
///
/// The operator's answer. Plain grants are memory-only and time-bounded; refusals are recorded
/// with the same weight, because a channel that only remembers its approvals cannot show that it
/// was ever used as a filter.
///
/// `standing: true` PROMOTES the grant into the durable store (Sprint F R1, dp 2026-08-14):
/// the same ask/answer shape, the same operator wall, but the grant is written to the vault's
/// standing-scope document and survives a restart. `expires_in_secs` then bounds the STANDING
/// grant when given; absent, the grant is durable until revoked (`/api/scope/standing/revoke`)
/// — which is exactly the trade the asymmetry doc records: durability in exchange for an
/// explicit revoke verb, a generation counter, and disclosure in the hashed operating law.
async fn scope_decide(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    use crate::server::state::SCOPE_REQUEST_TTL_SECS;
    let request_id = body
        .get("request_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let standing = body.get("standing").and_then(|v| v.as_bool()).unwrap_or(false);
    let granted = match body.get("granted").and_then(|v| v.as_bool()) {
        Some(g) => g,
        // No default. An absent verdict is not a deny and not an approve — it is a malformed
        // call, and guessing either way would put a ruling in the chain that nobody made.
        None => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({"error": "granted must be explicitly true or false"})),
            );
        }
    };
    let reason = body
        .get("reason")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    // Same asymmetry as every other control here: widening needs a stated why, narrowing does
    // not. Refusing is the safe direction and must never carry more friction than approving.
    if granted && reason.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "reason is required to grant — this widens what a member can reach, and \
                          a widening whose rationale is not recorded is indistinguishable \
                          afterwards from a misconfiguration"
            })),
        );
    }
    // A standing REFUSAL is not a thing: refusing is already durable in effect (nothing was
    // granted, and a re-ask files a new record). Guessing what the caller meant would put a
    // durable ruling in the store nobody made.
    if standing && !granted {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "standing:true is only meaningful with granted:true — a refusal \
                          grants nothing and needs no durability"
            })),
        );
    }
    let now = crate::server::gate_escalation::now_secs();
    let window = body
        .get("expires_in_secs")
        .and_then(|v| v.as_u64())
        .unwrap_or(SCOPE_REQUEST_TTL_SECS);
    // The STANDING expiry is different on purpose: given a window, it is bounded by it;
    // absent one, it is durable until revoked — `None`, never a silent default TTL, because
    // "standing" with an invisible 8h fuse would teach operators the store lies.
    let standing_expires_at: Option<u64> = if standing {
        body.get("expires_in_secs").and_then(|v| v.as_u64()).map(|w| now + w)
    } else {
        None
    };

    let mut s = state.lock().await;
    let Some(req) = s.scope_requests.get(&request_id) else {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "no such scope request"})),
        );
    };
    // An expired or already-decided request is not re-openable here. Re-deciding one would let a
    // refusal become an approval with no new ask on the record, which is precisely the shape the
    // escalation store refuses for the same reason.
    let status = req.status(now);
    if status != "pending" {
        return (
            StatusCode::CONFLICT,
            Json(serde_json::json!({
                "error": format!("request is {status}, not pending — a new request is the way \
                                  back in, so the ask and its answer stay paired"),
            })),
        );
    }
    let (plugin_id, path, ask) = (req.plugin_id.clone(), req.path.clone(), req.reason.clone());
    let expires_at = if granted {
        now + window
    } else {
        req.expires_at
    };

    // ORDER: WITNESS, THEN WIDEN.
    //
    // The record is written before the grant takes effect, and the grant is applied only if the
    // record committed. The reverse order — which `policy_set_instance_grant` still uses — has a
    // window where a failed chain append leaves a LIVE grant that nothing recorded: the exact
    // shape the accountability block calls an A failure, and the worst version of it, since the
    // unrecorded artifact is a widening of what a member may reach.
    //
    // Nothing observes the entry between the append and the apply — one lock, no await — so a
    // recorded-but-unapplied grant is not reachable either. The residual failure is a panic in
    // between, which leaves a record of a grant that is not live: safe direction, and legible.
    let entry = s.append_chain(
        if granted {
            if standing {
                // A STANDING grant is not in force until the vault write lands, so this first
                // record is an INTENT, not a success (GPT review of #462). Naming it
                // `scope_granted` here — as it was — meant a failed commit below left the
                // chain asserting a durable grant that never existed, and every reader,
                // including the reputation fold, would believe it. The success record is
                // appended after the commit, carrying this entry's hash as `intent`.
                //
                // A MEMORY-ONLY grant keeps the single `scope_granted`: its only "apply" step
                // is the in-memory `scope_requests.get_mut` below, which cannot fail, so there
                // is no window in which the record could outlive the thing it records.
                "scope_grant_intent"
            } else {
                "scope_granted"
            }
        } else {
            "scope_refused"
        },
        serde_json::json!({
            "request_id": request_id,
            "plugin_id": plugin_id,
            "subject_instance_lct": s.member_lct(&plugin_id),
            "path": path,
            // The ask travels with the answer. A ruling that records only the verdict leaves a
            // reader to reconstruct what was asked from a separate entry — and the pairing is
            // the whole evidentiary value of the record.
            "requested_because": ask,
            "decision_reason": reason,
            "granted_by": "operator",
            "via": "operator_session",
            "expires_at": expires_at,
            // The promotion is part of the record, not a separate act: the standing grant's
            // expiry and the generation it will mint travel with the ruling that made it.
            "standing": standing,
            "standing_expires_at": standing_expires_at,
            "standing_generation": if standing {
                serde_json::json!(s.standing_scope.generation + 1)
            } else {
                serde_json::Value::Null
            },
            "durability": if standing {
                "STANDING — written to the vault's standing-scope document; survives restart; \
                 revocable via /api/scope/standing/revoke; identity.json is untouched"
            } else {
                "memory-only — a daemon restart revokes it; identity.json is untouched"
            },
        }),
    );
    let entry = match entry {
        Ok(e) => e,
        // Fail LOUD and change nothing. A grant that could not be witnessed must not exist:
        // this is the one surface in the system where an unrecorded success is worse than a
        // recorded failure.
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("witness append failed, decision NOT applied: {e}")
                })),
            );
        }
    };

    // The ruling the disposition obligation will anchor to (revised #480 contract:
    // the terminal ruling IS the witness). For a standing grant the INTENT entry is
    // not the terminal fact — the success `scope_granted` below is, and the standing
    // arm replaces this with its hash.
    let mut ruling_hash = entry.hash.clone();

    // THE STANDING WIDENING, applied after its record committed (same order rule as above).
    // The in-memory mutation and the vault write must land together: a grant live in memory
    // but absent from the vault would silently die at the next restart — the exact lie this
    // store exists to end. `commit_standing_scope` persists a CANDIDATE before swapping it
    // live (GPT review of #431, blocker 1: the previous revoke-as-rollback double-moved the
    // generation and, on a replacement, discarded the prior grant), so on a failed vault
    // write the live store is bit-identical to before — generation included.
    //
    // This comment used to end "...and the chain holds a record of a grant that is not live:
    // the safe direction, and legible." That was wrong, and it is corrected rather than
    // deleted because the wrong version is instructive: the record in question was named
    // `scope_granted`, so "legible" was being asked to do a mechanism's job. It is only the
    // safe direction relative to the OTHER ordering (a live grant nothing recorded); against
    // an auditor it is the worse one, because a false `scope_granted` is a phantom widening
    // nothing contradicts. The first record is now an INTENT and the success is appended
    // after the commit, so neither direction can lie.
    if standing {
        // Snapshot for rollback (revised #480 review, blocker 3): the SUCCESS
        // witness below is part of the grant's finality. If it fails after the
        // commit landed, the grant must NOT stay live — permission in force,
        // requester uninformed, projector without a terminal source is the
        // escalation defect one door over. A whole-store snapshot, not
        // `revoke(member, path)`: a decide can REPLACE an existing grant on the
        // same path, and revoking would destroy the predecessor along with the
        // new grant; restoring the snapshot loses neither.
        let standing_prior = s.standing_scope.clone();
        let grant = crate::server::standing_scope::StandingGrant {
            member: plugin_id.clone(),
            path: path.clone(),
            granted_at: now,
            granted_by: "operator".to_string(),
            reason: reason.clone(),
            expires_at: standing_expires_at,
            request_id: Some(request_id.clone()),
        };
        if let Err(e) = s.commit_standing_scope(|st| st.add(grant)) {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!(
                        "standing grant NOT applied — vault write failed ({e}); the live store \
                         is untouched (the candidate was persisted first), re-decide to retry"
                    ),
                    // The chain holds the INTENT and no `scope_granted`, so nothing reads this
                    // member as holding the path. That is the whole reason the first record is
                    // named for an attempt rather than an outcome.
                    "state": "the chain holds the INTENT and no scope_granted",
                    "intentEntryHash": entry.hash,
                })),
            );
        }
        // SUCCESS — appended only now, when the grant is really durable. Carries the intent's
        // hash so the pair is joinable, and the generation the commit actually produced rather
        // than the `+1` the intent could only predict.
        let success = match s.append_chain(
            "scope_granted",
            serde_json::json!({
                "request_id": request_id,
                "plugin_id": plugin_id,
                "subject_instance_lct": s.member_lct(&plugin_id),
                "path": path,
                "decision_reason": reason,
                "granted_by": "operator",
                "via": "operator_session",
                "origin": "member_request",
                "standing": true,
                "standing_expires_at": standing_expires_at,
                "standing_generation": s.standing_scope.generation,
                "intent": entry.hash,
            }),
        ) {
            Ok(e) => e,
            Err(e) => {
                // Roll the grant back THROUGH the commit path, so memory and the
                // vault's standing-scope document move together and the store is
                // bit-identical to before the decide — generation included. If
                // THAT write fails the grant is live with no terminal record:
                // the dire case, said as loudly as this surface can say it.
                return match s.commit_standing_scope(|st| *st = standing_prior) {
                    Ok(()) => (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(serde_json::json!({
                            "error": format!(
                                "decision NOT applied — the terminal scope_granted append \
                                 failed ({e}); the standing grant was ROLLED BACK (live store \
                                 and vault), the chain holds only the intent. Re-decide to retry."
                            ),
                            "state": "grant NOT in force; chain holds the intent of a \
                                      rolled-back decision",
                            "intentEntryHash": entry.hash,
                        })),
                    ),
                    Err(rb) => (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(serde_json::json!({
                            "error": format!(
                                "THE STANDING GRANT IS LIVE but its success record could not be \
                                 appended ({e}) AND the rollback failed ({rb}). Revoke via \
                                 /api/scope/standing/revoke or repair the chain — do not assume \
                                 the grant is absent because the confirmation is."
                            ),
                            "state": "grant IS in force; chain holds only the intent",
                            "intentEntryHash": entry.hash,
                        })),
                    ),
                };
            }
        };
        // The TERMINAL ruling for a standing grant is this success entry, not the
        // intent: the disposition's obligation key must name the record that says
        // the grant is in force.
        ruling_hash = success.hash;
    }

    if let Some(req) = s.scope_requests.get_mut(&request_id) {
        req.granted = Some(granted);
        req.decided_by = Some("operator".to_string());
        req.decided_at = Some(now);
        req.decision_reason = if reason.is_empty() {
            None
        } else {
            Some(reason.clone())
        };
        req.expires_at = expires_at;
    }

    // #459: the decision's RETURN EDGE. The requester filed through MCP and until
    // now had no way to learn the answer short of polling — a granted or refused
    // ask read exactly like a pending one. Revised #480 contract: the ruling entry
    // IS the witness, so the obligation anchors to its hash directly; a failed
    // ensure is warned about inside `ensure_disposition`, not returned — the
    // decision landed, and the cursor projector retries the notification half.
    let disposition_notice_id = super::handler::ensure_disposition(
        &s,
        &plugin_id,
        &format!("hestia://scope/{request_id}"),
        &ruling_hash,
    );

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true,
            "request_id": request_id,
            "granted": granted,
            "path": path,
            "expires_at": expires_at,
            "standing": standing,
            "standing_expires_at": standing_expires_at,
            "generation": if standing { serde_json::json!(s.standing_scope.generation) } else { serde_json::Value::Null },
            "witnessEntryHash": entry.hash,
            "disposition_notice_id": disposition_notice_id,
        })),
    )
}

/// `POST /api/scope/grant` {plugin_id, path, reason, expires_in_secs?}
///
/// THE OPERATOR'S OWN GRANT — no `request_id`, because no member asked.
///
/// dp, 2026-08-15: *"i still don't have a way of actually granting scope."* This is why.
/// `/api/scope/decide` is the only widening door that existed, and it opens with
/// `scope_requests.get(&request_id)` — it can only ANSWER an ask. So the operator could
/// ratify a member's request and could not originate a grant, and the fleet reached a state
/// no one intended: every member's authoritative envelope empty after a restart, the remedy
/// (`hestia_request_scope`) itself denied by the empty envelope it exists to fill, and the
/// operator holding no verb that could break the cycle from outside it. The one grant that
/// did land only landed because a member routed around its own gate to file the ask.
///
/// That is not a missing convenience, it is backwards against this society's own rule that
/// **only an operator-walled act may compose upward; admission may only narrow**. Making the
/// operator's composing power conditional on a member first failing makes it derivative of a
/// member act — the operator could ratify, never originate. This verb restores the direction.
///
/// **It is its own act, not a synthesized ask.** The obvious shortcut — mint a fake
/// `ScopeRequest` and immediately decide it — would put a request in the chain that no member
/// made, and every later reader of that record would mis-attribute the asking. So this appends
/// `scope_granted` with `request_id: null` and `origin: "operator_initiated"`: a reader can
/// always tell a grant that answered someone from a grant the operator chose to make.
///
/// **It mints a STANDING grant, and only a standing grant.** Live grants are rows in
/// `scope_requests` (see `live_scope_grants`), so a memory-only version would need exactly the
/// fake ask this refuses to write. That constraint points the right way: a proactive grant
/// should outlive a restart. The memory-only form exists because it answers a time-bounded
/// ask; this one answers nothing, so it is durable until revoked, or until `expires_in_secs`
/// if the operator wants it bounded — and a bounded STANDING grant still survives a restart,
/// which is strictly better than what the fleet has been losing on every deploy.
async fn scope_grant(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let plugin_id = body
        .get("plugin_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let raw_path = body
        .get("path")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if plugin_id.is_empty() || raw_path.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "plugin_id and path are required"})),
        );
    }
    let path = crate::server::state::normalize_scope_path(&raw_path);
    let reason = body
        .get("reason")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    // Same asymmetry as every other widening on this surface, and it binds harder here: this
    // grant has no member ask attached to explain it, so the reason is the ONLY statement of
    // why the reach exists. Without it the record is a widening from nowhere.
    if reason.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "reason is required — an operator-initiated grant carries no member \
                          request to explain it, so its rationale is the only account of why \
                          this reach exists"
            })),
        );
    }
    let now = crate::server::gate_escalation::now_secs();
    let expires_at: Option<u64> = body
        .get("expires_in_secs")
        .and_then(|v| v.as_u64())
        .filter(|w| *w > 0)
        .map(|w| now + w);

    let mut s = state.lock().await;
    // A GRANT TO A MEMBER NOBODY HAS SEEN IS ALMOST ALWAYS A TYPO, and it fails silently:
    // the row persists, the generation moves, and nothing ever matches it. Not refused —
    // granting ahead of a member's first connect is legitimate — but REPORTED, so the caller
    // can tell "granted to kimi-code" from "granted to kimi-cod" while still on the screen.
    //
    // THE REGISTRY, NOT `member_lct`. The first version of this asked `member_lct(..).is_some()`
    // and was structurally incapable of failing: `member_lct` DERIVES a label by hashing the
    // plugin_id with the sovereign LCT, so it returns `Some` for any non-empty, non-synthetic
    // string — including `kimi-cod`. It was a guard that could only ever say "known", printing
    // "the gate consults it immediately" over a grant that would never match anything. Caught
    // by running the negative case rather than the happy one; a guard nobody has watched FAIL
    // is a claim, not a check. `member_registry` is the store of members actually recorded, so
    // asking it can return false.
    let member_known = s.member_registry.get(&plugin_id).is_some();
    let replaces = s
        .standing_scope
        .grants
        .iter()
        .any(|g| g.member == plugin_id && g.path == path);

    // ORDER: INTENT → COMMIT → SUCCESS, via the one function that owns it
    // (`witness_and_commit_standing_grant`). This used to append `scope_granted` and THEN
    // commit, so a failed vault write left the chain asserting a grant that never came into
    // force — a PHANTOM WIDENING that the reputation fold, the ledger and any auditor would
    // believe, with nothing to contradict it. GPT caught it on #462 and was right; I had
    // documented the outcome and called it "the safe direction, and legible", which was true
    // only against the OTHER ordering and did the work of a mechanism with a word.
    let record = serde_json::json!({
        // NULL, and load-bearing: this grant answered no ask. A reader that finds a
        // request_id here is looking at a ratification; one that finds null is looking at
        // an act the operator originated.
        "request_id": serde_json::Value::Null,
        "origin": "operator_initiated",
        "plugin_id": plugin_id,
        "subject_instance_lct": s.member_lct(&plugin_id),
        "path": path,
        "path_as_asked": raw_path,
        // There is no `requested_because` because nobody requested it. Saying so beats
        // omitting the field, which reads as a record that lost its ask.
        "requested_because": serde_json::Value::Null,
        "decision_reason": reason,
        "granted_by": "operator",
        "via": "operator_session",
        "standing": true,
        "standing_expires_at": expires_at,
        "replaces_existing": replaces,
        "member_known": member_known,
        "durability": "STANDING — written to the vault's standing-scope document; survives \
                       restart; revocable via /api/scope/standing/revoke; identity.json is \
                       untouched",
    });
    let grant = crate::server::standing_scope::StandingGrant {
        member: plugin_id.clone(),
        path: path.clone(),
        granted_at: now,
        granted_by: "operator".to_string(),
        reason: reason.clone(),
        expires_at,
        // None, for the same reason `request_id` is null in the record above.
        request_id: None,
    };
    let (intent_hash, entry_hash) = match s.witness_and_commit_standing_grant(grant, record) {
        Ok(pair) => pair,
        // Each arm reports WHAT IS TRUE NOW, because "500" alone leaves the operator unable to
        // tell an attempt that changed nothing from one that widened reach without saying so.
        Err(crate::server::state::StandingGrantFailure::IntentNotWitnessed(e)) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("witness append failed, grant NOT applied: {e}"),
                    "state": "nothing was recorded and nothing was granted",
                })),
            );
        }
        Err(crate::server::state::StandingGrantFailure::NotCommitted { intent_hash, err }) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!(
                        "grant NOT applied — vault write failed ({err}); the live store is \
                         untouched (the candidate was persisted first), retry to apply"
                    ),
                    "state": "the chain holds the INTENT and no scope_granted, so nothing \
                              reads this member as holding the path",
                    "intentEntryHash": intent_hash,
                })),
            );
        }
        Err(crate::server::state::StandingGrantFailure::LiveButUnconfirmed {
            intent_hash,
            err,
        }) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!(
                        "THE GRANT IS LIVE but its success record could not be appended \
                         ({err}). This is under-recorded, not unrecorded: the intent is on \
                         the chain. Revoke and re-grant, or repair the chain — do not assume \
                         the grant is absent because the confirmation is."
                    ),
                    "state": "grant IS in force; chain holds only the intent",
                    "intentEntryHash": intent_hash,
                })),
            );
        }
    };

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true,
            "plugin_id": plugin_id,
            "path": path,
            "standing": true,
            "expires_at": expires_at,
            "generation": s.standing_scope.generation,
            "replaced_existing": replaces,
            // Surfaced so a typo is visible at the moment it is made, not at the moment the
            // grant fails to help someone.
            "member_known": member_known,
            "note": if member_known {
                "granted — durable until revoked or expiry; the gate consults it immediately"
            } else {
                "GRANTED, BUT NO MEMBER BY THAT plugin_id HAS EVER CONNECTED to this daemon. \
                 That is legitimate if you are granting ahead of a first connect, and it is \
                 what a typo looks like too. Check the spelling before relying on this."
            },
            "witnessEntryHash": entry_hash,
            // Both halves of the pair are returned, so a caller can verify the ordering on the
            // chain itself rather than trusting this response's word for it.
            "intentEntryHash": intent_hash,
        })),
    )
}

/// `POST /api/scope/floor` {path, reason} — add a path to THE SOCIETY FLOOR.
///
/// dp, 2026-08-16: *"law has to be applied uniformly to ALL. that is the only way the law is
/// trusted."* This is the surface that makes that structural rather than aspirational: one
/// list, consulted for every member, that no member can hold a different copy of.
///
/// **Wider than any grant on this box, and the response says so.** A standing grant widens one
/// member; this widens every member at once, including ones that have never connected and ones
/// nobody is watching. It is operator-walled like every other widening, requires a stated
/// reason for the same evidentiary purpose, and is witnessed before it takes effect.
///
/// **Why this is nonetheless the SAFER instrument.** The alternative — granting each member
/// the same list — produces N copies that drift the moment one member is granted something the
/// others are not, and then the law differs per seat while looking identical. Uniformity has
/// to be structural or it decays. One list cannot drift.
async fn scope_floor_add(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let raw_path = body.get("path").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let reason = body.get("reason").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    if raw_path.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "path is required"})),
        );
    }
    if reason.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "reason is required — this widens EVERY member of this society at \
                          once, and a widening of that breadth whose rationale is not recorded \
                          is indistinguishable afterwards from a misconfiguration"
            })),
        );
    }
    let path = crate::server::state::normalize_scope_path(&raw_path);
    let now = crate::server::gate_escalation::now_secs();

    let mut s = state.lock().await;
    let replaces = s.standing_scope.floor_allows(&path);
    let members_affected = s.member_registry.len();

    // ORDER: WITNESS, THEN WIDEN — and the intent/success split, for the same reason the
    // per-member grant has it: a failed vault write must not leave the chain asserting that
    // the whole society was widened when it was not.
    let entry = match s.append_chain(
        "society_floor_intent",
        serde_json::json!({
            "path": path,
            "path_as_asked": raw_path,
            "reason": reason,
            "added_by": "operator",
            "via": "operator_session",
            "replaces_existing": replaces,
            "members_in_registry": members_affected,
            "scope": "SOCIETY — every member of this society, present and future",
            "semantics": "additive only: effective(m) = society_floor ∪ member(m)",
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("witness append failed, floor NOT changed: {e}"),
                    "state": "nothing recorded, nothing widened",
                })),
            );
        }
    };

    let fe = crate::server::standing_scope::FloorEntry {
        path: path.clone(),
        added_at: now,
        added_by: "operator".to_string(),
        reason: reason.clone(),
    };
    // The terminal success witness is part of finality. Preserve the exact prior store so
    // a failed terminal append can restore both memory and vault, including a predecessor
    // when this call replaces an existing floor entry.
    let standing_prior = s.standing_scope.clone();
    if let Err(e) = s.commit_standing_scope(|st| st.floor_add(fe)) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "error": format!("floor NOT changed — vault write failed ({e}); the live store \
                                  is untouched (the candidate was persisted first), retry"),
                "state": "the chain holds the INTENT and no society_floor_added",
                "intentEntryHash": entry.hash,
            })),
        );
    }
    let generation = s.standing_scope.generation;
    let success = match s.append_chain(
        "society_floor_added",
        serde_json::json!({
            "path": path, "reason": reason, "added_by": "operator",
            "intent": entry.hash, "standing_generation": generation,
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return match s.commit_standing_scope(|st| *st = standing_prior) {
                Ok(()) => (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({
                        "error": format!("floor NOT applied — the terminal society_floor_added \
                                          append failed ({e}); the prior floor was restored in \
                                          memory and vault. Retry this exact call."),
                        "state": "floor change NOT in force; chain holds only the intent",
                        "intentEntryHash": entry.hash,
                    })),
                ),
                Err(rb) => (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({
                        "error": format!("THE FLOOR CHANGE IS LIVE but its success record could \
                                          not be appended ({e}) AND rollback failed ({rb}). \
                                          Remove or repair it explicitly; do not infer absence \
                                          from the missing terminal record."),
                        "state": "floor change IS in force; chain holds only the intent",
                        "intentEntryHash": entry.hash,
                    })),
                ),
            };
        }
    };
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true,
            "path": path,
            "generation": generation,
            "replaced_existing": replaces,
            "applies_to": "every member of this society, including any that connect later",
            "note": "additive only — a member's own grants can widen beyond this, never narrow \
                     below it",
            // The terminal fact, not the intent. This is the record that says the floor is
            // durably in force and is the only correct pointer for downstream consumers.
            "witnessEntryHash": success.hash,
            "intentEntryHash": entry.hash,
        })),
    )
}

/// `POST /api/scope/floor/remove` {path, reason?} — take a path OFF the society floor.
///
/// The tightening direction, and the only one on this surface. It narrows every member at
/// once — including members that never asked for the path, are not watching, and may be
/// mid-act against it. That is strictly more consequential than revoking one member's grant,
/// so it is recorded with the same weight rather than treated as cleanup.
async fn scope_floor_remove(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let raw_path = body.get("path").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    let reason = body.get("reason").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    if raw_path.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "path is required"})),
        );
    }
    let path = crate::server::state::normalize_scope_path(&raw_path);
    let mut s = state.lock().await;
    if !s.standing_scope.floor_allows(&path) && !s.standing_scope_dirty {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "that path is not on the society floor"})),
        );
    }
    let entry = match s.append_chain(
        "society_floor_removed",
        serde_json::json!({
            "path": path, "reason": reason, "removed_by": "operator",
            "via": "operator_session",
            "scope": "SOCIETY — narrows every member at once",
            "standing_generation": s.standing_scope.generation + 1,
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("witness append failed, floor NOT changed: {e}")
                })),
            );
        }
    };
    // Tightening: apply to memory first, then persist — a failed vault write may only ever
    // leave the TIGHTER state in force, which is the same rule `apply_standing_revoke` obeys.
    let removed = s.standing_scope.floor_remove(&path);
    if let Err(e) = s.persist_standing_scope() {
        s.standing_scope_dirty = true;
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "error": format!("removed from the live floor but the vault write FAILED ({e}); \
                                  memory is the tighter state and is kept, but a restart would \
                                  resurrect this path — retry this exact call"),
                "removed_from_memory": removed,
                "witnessEntryHash": entry.hash,
            })),
        );
    }
    s.standing_scope_dirty = false;
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true, "path": path, "removed": removed,
            "generation": s.standing_scope.generation,
            "effect": "every member of this society loses this path unless they hold their own \
                       grant for it",
            "witnessEntryHash": entry.hash,
        })),
    )
}

/// `POST /api/scope/standing/revoke` {plugin_id, path, reason?}
///
/// The revoke half of the durable channel — first-class because a durable widening with no
/// revocation verb would make "restart the daemon" the only way out, which is precisely the
/// backstop the standing store gave up. Behind the operator gate like every scope decision.
///
/// ORDER, deliberately different from the grant path: witness first (a revoke that could not
/// be recorded is refused, same as the grant), but on a failed PERSIST the in-memory removal
/// is KEPT rather than rolled back — a failure here may only ever leave the TIGHTER state in
/// force, and the error says the disk still holds the grant so the operator retries.
async fn scope_standing_revoke(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let plugin_id = body
        .get("plugin_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let raw_path = body
        .get("path")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if plugin_id.is_empty() || raw_path.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "plugin_id and path are required"})),
        );
    }
    let path = crate::server::state::normalize_scope_path(&raw_path);
    let reason = body
        .get("reason")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let mut s = state.lock().await;
    let in_memory = s
        .standing_scope
        .grants
        .iter()
        .any(|g| g.member == plugin_id && g.path == path);
    // 404 only when the store is CONSISTENT and holds no such grant — a typo, bounded here.
    // While `standing_scope_dirty` is set, memory is tighter than the vault (a prior revoke's
    // vault write failed after the row left memory), so a row absent from memory may still be
    // in the vault: that retry must be accepted and re-persisted, not 404ed out of the
    // promised recovery (GPT review of #431, blocker 2).
    if !in_memory && !s.standing_scope_dirty {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "no standing grant of record for that (plugin_id, path)"})),
        );
    }

    let entry = match s.append_chain(
        "scope_standing_revoked",
        serde_json::json!({
            "plugin_id": plugin_id,
            "subject_instance_lct": s.member_lct(&plugin_id),
            "path": path,
            "reason": reason,
            "revoked_by": "operator",
            "via": "operator_session",
            // A retry after a failed vault write re-persists a removal memory already made:
            // recorded as such, so the chain distinguishes the ruling from its durability.
            "retry_sync": !in_memory,
            "standing_generation": if in_memory {
                s.standing_scope.generation + 1
            } else {
                s.standing_scope.generation
            },
        }),
    ) {
        Ok(e) => e,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("witness append failed, revoke NOT applied: {e}")
                })),
            );
        }
    };

    // Remove-from-memory-first, then persist; idempotent so the failure mode is retryable.
    if let Err(e) = s.apply_standing_revoke(&plugin_id, &path) {
        // Memory is already the tighter state; keep it. The vault still holds the grant, so
        // a restart would resurrect a widening — said loudly, and THIS EXACT CALL is the
        // retry (the dirty flag keeps the door open even though the row has left memory).
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "error": format!(
                    "revoked in memory but the vault write FAILED ({e}) — a restart before a \
                     successful retry would resurrect this grant; RETRY this same revoke to \
                     persist the removal"
                ),
                "witnessEntryHash": entry.hash,
            })),
        );
    }

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "ok": true,
            "plugin_id": plugin_id,
            "path": path,
            "retry_sync": !in_memory,
            "generation": s.standing_scope.generation,
            "witnessEntryHash": entry.hash,
        })),
    )
}

async fn policy_set_preset(
    State(state): State<SharedState>,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    let preset = body
        .get("preset")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if !crate::policy::is_preset_name(&preset) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": format!("unknown preset: {preset}")})),
        );
    }
    let mut s = state.lock().await;
    match s.vault.set_active_preset(&preset) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain(
                "policy_edit",
                serde_json::json!({"change": "preset", "preset": preset}),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "preset": preset})),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
            None => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({"error": format!("unknown decision: {d}")})),
                );
            }
        },
    };
    let ov = crate::vault::PolicyOverride {
        decision,
        enabled: body.enabled,
    };
    let mut s = state.lock().await;
    match s.vault.set_policy_override(&body.rule_id, ov) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain(
                "policy_edit",
                serde_json::json!({
                    "change": "override", "rule_id": body.rule_id,
                    "decision": body.decision, "enabled": body.enabled,
                }),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "rule_id": body.rule_id})),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
            let _ = s.append_chain(
                "policy_edit",
                serde_json::json!({"change": "clear_override", "rule_id": rule_id}),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "rule_id": rule_id})),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "rule id and name are required"})),
        );
    }
    let rule_id = rule.id.clone();
    let mut s = state.lock().await;
    match s.vault.upsert_custom_rule(rule) {
        Ok(()) => {
            s.reload_policy();
            let _ = s.append_chain(
                "policy_edit",
                serde_json::json!({"change": "upsert_rule", "rule_id": rule_id}),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "rule_id": rule_id})),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "removed": removed})),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
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
            let _ = s.append_chain(
                "orchestrator_connect",
                serde_json::json!({"id": id, "status": msg}),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({"ok": true, "message": msg})),
            )
        }
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
    }
}

// --- Agent read list (agent-atlas read half) ---

/// `GET /api/agents` → the three inventories: what is installed, what hestia has an
/// adapter for, and what is actually governed. Read-only; the write half is
/// `/api/orchestrators/:id/connect` (govern) and `/api/agents/:id/ungovern`.
async fn agents_inventory() -> impl IntoResponse {
    match crate::server::agents::inventory() {
        Ok(v) => (StatusCode::OK, Json(v)),
        // A failed look is reported as a failed look. Returning an empty inventory here
        // would render as "nothing ungoverned on this machine", which is the precise
        // inversion this surface exists to prevent.
        Err(e) => (
            StatusCode::OK,
            Json(serde_json::json!({
                "status": "UNKNOWN",
                "reason": format!("inventory could not run: {e}"),
            })),
        ),
    }
}

/// `POST /api/agents/:id/ungovern` → remove hestia's hook wiring from an agent's config.
///
/// surface: agent_ungovern   act: remove enforcement from a governed agent
/// S: high/reversible [construct: `ungovern` writes a verified backup before any edit]
/// R: pass [construct: mounted behind `operator_gate` with the rest of /api/*]
/// W: pass [construct: operator_gate proves an Ed25519 challenge-signed session]
/// O: pass [construct: backup written + byte-compared before the config is rewritten]
/// A: pass [construct: append_chain("agent_ungovern") carries agent, backup path and
///    hooks_removed — the evidence the act relied on, not merely that it happened]
/// V: present [construct: TOML configs are refused outright rather than edited
///    approximately; the operator is told to do it by hand]
/// verdict: PASS
///
/// Ungoverning is deliberately louder than governing. Governing adds a gate and a bad
/// outcome is a blocked tool call; ungoverning REMOVES one, and its bad outcome is an
/// agent running unwatched while the dashboard still lists it as known.
async fn agent_ungovern(
    State(state): State<SharedState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match crate::server::agents::ungovern(&id) {
        Ok((backup, removed)) => {
            let s = state.lock().await;
            let _ = s.append_chain(
                "agent_ungovern",
                serde_json::json!({
                    "agent": id, "hooks_removed": removed, "backup": backup,
                }),
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({
                    "ok": true, "hooks_removed": removed, "backup": backup,
                    "message": format!(
                        "{removed} hestia hook(s) removed from {id}; backup at {backup}. \
                         Restart {id} for this to take effect."),
                })),
            )
        }
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": e.to_string()})),
        ),
    }
}

// --- Gate integrity ---

/// The gate set, DISCOVERED rather than declared (thor, hestia#52 review).
///
/// This was four hardcoded `$HOME` paths filtered by `is_file()`, and every way that set
/// could be wrong was silent: a path that is not there is dropped, and a dropped path is
/// indistinguishable from a clean one. Thor measured the consequence on his own machine —
/// `known_gate_paths()` discovered `[]`, `/api/gates/verify` returned `VERIFIED,
/// findings: 0, gates: []`, while that same host had a configured, enabled PreToolUse gate
/// resolving to a file that does not exist and therefore failing open.
///
/// `VERIFIED` over an empty denominator is the declaration-vs-evidence inversion these
/// modules are about, one level up from where they look for it. `agents_inventory`, fifty
/// lines below, already refuses exactly this move by returning UNKNOWN when it could not
/// look; this had no such branch. It is also the SECOND time this blind spot has been
/// reported against my code by the same reviewer — the first was `inventory.inspect()`
/// reading only HOME while the precedence chain is user+project+local.
///
/// So coverage now comes from the inventory, which already stats every hook target on the
/// machine across the full scope chain and simply kept the list to itself. One discovery
/// path, measured once, consumed by both surfaces.
fn discovered_gate_paths() -> Result<Vec<(String, String)>, String> {
    let inv = crate::server::agents::inventory().map_err(|e| e.to_string())?;
    if inv.get("status").and_then(|v| v.as_str()) == Some("UNKNOWN") {
        return Err(inv
            .get("reason")
            .and_then(|v| v.as_str())
            .unwrap_or("inventory could not establish its scope")
            .to_string());
    }
    let mut out = Vec::new();
    for rec in inv
        .get("detail")
        .and_then(|d| d.as_array())
        .into_iter()
        .flatten()
    {
        let agent = rec
            .get("agent")
            .and_then(|v| v.as_str())
            .unwrap_or("?")
            .to_string();
        for t in rec
            .get("hook_targets")
            .and_then(|d| d.as_array())
            .into_iter()
            .flatten()
        {
            // Gate-role hooks only. An observe hook that vanishes loses evidence; a GATE
            // that vanishes fails open, and that is what an integrity check is for.
            if t.get("is_gate").and_then(|v| v.as_bool()) != Some(true) {
                continue;
            }
            if let Some(p) = t.get("path").and_then(|v| v.as_str()) {
                out.push((agent.clone(), p.to_string()));
            }
        }
    }
    out.sort();
    out.dedup();
    Ok(out)
}

/// `GET /api/gates/verify` — hash every known gate and compare to the vault's ratified
/// expectation. The DAEMON hashes the file; it never asks a gate about itself.
async fn gates_verify(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    let exp = s.vault.gate_expectations();
    // An unmeasurable denominator is UNKNOWN, never VERIFIED.
    let discovered = match discovered_gate_paths() {
        Ok(d) => d,
        Err(reason) => {
            return (
                StatusCode::OK,
                Json(serde_json::json!({
                    "status": "UNKNOWN",
                    "reason": format!("gate set could not be established: {reason}"),
                    "note": "Coverage is derived from the inventory's discovered hook \
                             targets. Without it this check cannot tell 'no gates' from \
                             'could not look', so it reports neither.",
                })),
            );
        }
    };
    if discovered.is_empty() {
        return (
            StatusCode::OK,
            Json(serde_json::json!({
                "status": "UNKNOWN",
                "reason": "no gate-role hooks discovered on this machine — that is either a \
                           genuinely ungoverned host or a discovery failure, and this check \
                           cannot tell them apart. VERIFIED over an empty set would assert \
                           the safer of the two without evidence.",
                "discovered": 0,
            })),
        );
    }
    let wired: Vec<String> = discovered.iter().map(|(_, f)| f.clone()).collect();
    let verdicts = crate::vault::gate_integrity::verify(&exp, &wired);
    let findings = verdicts.iter().filter(|v| v.is_finding()).count();
    (
        StatusCode::OK,
        Json(serde_json::json!({
            // MODIFIED outranks everything: a rewritten gate is the live attack, where an
            // unratified one is merely unexamined.
            "status": if verdicts.iter().any(|v| matches!(v, crate::vault::gate_integrity::GateVerdict::Modified{..})) {
                "MODIFIED"
            } else if findings > 0 { "FINDINGS" } else { "VERIFIED" },
            "findings": findings,
            // The denominator, stated. A reader can now tell how many gates this verdict
            // covers, which is the fact the previous version silently omitted.
            "discovered": discovered.len(),
            "coverage_source": "agent-inventory hook_targets (full scope chain), gate-role only",
            "gates": verdicts,
            "note": "Tamper-EVIDENT, not tamper-proof. The agent can rewrite its gate; it \
                     cannot rewrite this expectation, which lives in the operator-gated vault. \
                     See hestia#49 for what would make a rewritten gate's verdicts stop counting.",
        })),
    )
}

/// `POST /api/gates/ratify` — record the CURRENT bytes of every known gate as expected.
///
/// surface: gates_ratify   act: define what a correct gate is
/// S: high/reversible [construct: previous expectations are replaced, not merged; the
///    chain keeps the prior ratification]
/// R: pass [construct: behind `operator_gate` with the rest of /api/*]
/// W: pass [construct: operator_gate proves an Ed25519 challenge-signed session]
/// O: pass [construct: hashes computed before the vault write]
/// A: pass [construct: append_chain("gate_ratified") carries every path and digest]
/// V: present [construct: refuses when a gate is unreadable — ratifying what you could
///    not read would launder exactly the tampering this exists to catch]
/// verdict: PASS
///
/// The dangerous direction is ratifying an ALREADY-tampered gate, which would bless the
/// attack. Nothing here can tell a good build from a bad one; the operator must ratify
/// from a state they believe correct. The chain entry is what makes that judgement
/// reviewable afterwards.
async fn gates_ratify(State(state): State<SharedState>) -> impl IntoResponse {
    use crate::vault::gate_integrity::{GateExpectation, GateExpectations};
    let mut s = state.lock().await;
    let mut exp: GateExpectations = GateExpectations::new();
    let mut recorded = Vec::new();
    // Ratify the DISCOVERED set, for the same reason verify checks it: ratifying a
    // hardcoded list would bless whichever gates that list happened to name and leave the
    // rest unratified-and-unmentioned.
    let discovered = match discovered_gate_paths() {
        Ok(d) if !d.is_empty() => d,
        Ok(_) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "error": "refusing to ratify: no gate-role hooks discovered. Ratifying an \
                              empty set would record 'this machine's gates are correct' on the \
                              basis of having found none.",
                })),
            )
                .into_response();
        }
        Err(reason) => {
            return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
                "error": format!("refusing to ratify: gate set could not be established ({reason})"),
            }))).into_response();
        }
    };
    for (plugin_id, path) in discovered {
        match crate::vault::gate_integrity::hash_file(std::path::Path::new(&path)) {
            Ok(sha256) => {
                recorded.push(
                    serde_json::json!({"path": path, "plugin_id": plugin_id, "sha256": sha256}),
                );
                exp.insert(
                    path,
                    GateExpectation {
                        sha256,
                        plugin_id,
                        ratified_at: chrono::Utc::now(),
                        note: "operator ratification".into(),
                    },
                );
            }
            Err(e) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({
                        "error": format!("refusing to ratify: {path} unreadable ({e}). \
                                          Ratifying a gate you could not read would launder the \
                                          tampering this is meant to catch."),
                    })),
                )
                    .into_response();
            }
        }
    }
    if let Err(e) = s.vault.set_gate_expectations(exp) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": e.to_string()})),
        )
            .into_response();
    }
    let _ = s.append_chain("gate_ratified", serde_json::json!({"gates": recorded}));
    (
        StatusCode::OK,
        Json(serde_json::json!({"ok": true, "ratified": recorded})),
    )
        .into_response()
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
    // A FAILED read must not render as an EMPTY chain. This is the third site of the defect fixed
    // in the dashboard snapshot on 2026-08-01 (stats) and 2026-08-02 (#190, the recent feed): a
    // `.unwrap_or_default()` turned a read error into a green, empty, entirely plausible display.
    // dp read that as "chain display still blank for all agents all timelines" — the display was
    // not blank, it was LYING, and a 119MB witness.db is what made the failure ordinary. Fixing
    // one call site and not the class is why it came back; this is the call site the history view
    // actually uses.
    // PROJECT AND FILTER INSIDE THE SCAN. Two wins over the old read-then-filter:
    // no `Vec<ChainEntry>` of parsed documents is ever built, and a row the caller
    // filters out costs nothing at all — previously every row was parsed in full and
    // then discarded by the `event_type` / `tool` predicates below.
    //
    // The event-type filter is applied by the SCAN where it can be, so it becomes an
    // indexed SQL predicate rather than a post-hoc `!=`. The tool filter stays here
    // because it is a substring match on a projected field, which SQL cannot do for us
    // without reaching into the JSON.
    let type_filter: Option<Vec<&str>> = q.event_type.as_deref().map(|t| vec![t]);
    let (entries, read_error) =
        match s
            .chain_store
            .scan_recent(cutoff_str.as_deref(), type_filter.as_deref(), limit, |r| {
                let e = super::dashboard::flatten_row(r);
                if let Some(ref tf) = q.tool {
                    match e.tool_name {
                        Some(ref tn) if tn.contains(tf.as_str()) => {}
                        // A row with no tool_name cannot match a tool filter. Dropping it
                        // here is the same verdict the old post-filter reached.
                        _ => return None,
                    }
                }
                Some(e)
            }) {
            Ok(v) => (v, None),
            Err(e) => {
                tracing::error!("chain query read failed: {e}");
                (Vec::new(), Some(e.to_string()))
            }
        };
    Json(serde_json::json!({ "entries": entries, "read_error": read_error }))
}

/// `GET /api/governance/ledger?status=&range=&limit=` — the operator's ledger of ADMIN acts.
///
/// dp, 2026-08-05: *"i need a separate witness chain of admin actions from which i can
/// select/review/approve/deny, sortable by all/open/approved/denied ... currently i do not see any
/// escalations for me to approve/deny, nor can i see any history."*
///
/// The pending panels answered only "what is waiting". Everything decided, and everything nobody
/// ruled on before its window closed, was invisible — not missing from the chain, just never
/// projected by any reader. This is that reader. See `governance_ledger` for why it is a
/// projection over the one chain rather than a second store.
///
/// Behind `operator_gate` like every other consequential surface: this is the whole governance
/// history of the society, including who ruled on what and why.
async fn governance_ledger(
    State(state): State<SharedState>,
    Query(q): Query<LedgerQuery>,
) -> impl IntoResponse {
    use crate::server::governance_ledger as gl;

    // THE STATE LOCK IS TAKEN ONLY TO CLONE THE CHAIN HANDLE, AND RELEASED BEFORE THE READ.
    //
    // This handler used to hold `state.lock()` across the SQL read, the projection and the
    // paging — 8–15s against the live chain — so the dashboard's own ledger poll starved every
    // other caller of the daemon. Measured 2026-08-16: with this panel open `hestia_connect`
    // took 3.3–7.0s; with it closed, 0.001s.
    //
    // That is a governance failure, not a performance one. The plugin gate's witness budget is
    // 1.5s and its escalation round trip is barely more, so an operator READING the governance
    // screen prevented every member's gate from witnessing a refusal or opening an escalation
    // — and a hook killed at the harness's 5s clamp FAILS OPEN. The surface built to make
    // governance visible was, while visible, switching governance off.
    //
    // The store locks internally and is Send + Sync, so nothing about correctness required the
    // outer lock. `Arc::clone` here, `drop(s)` immediately, and the expensive work runs with
    // the daemon free.
    let chain = {
        let s = state.lock().await;
        std::sync::Arc::clone(&s.chain_store)
    };
    let now_dt = chrono::Utc::now();
    // Admin acts are rare compared with member traffic, so the default window reaches back FAR.
    // A day-shaped default would reproduce the original complaint for anything ruled last week.
    let cutoff = match q.range.as_deref() {
        Some("day") => Some(now_dt - chrono::Duration::days(1)),
        Some("week") => Some(now_dt - chrono::Duration::weeks(1)),
        Some("all") => None,
        // Default: a month. Long enough that an operator returning after a break sees the period
        // they were away for, which is exactly when this view matters most.
        _ => Some(now_dt - chrono::Duration::days(30)),
    };
    let cutoff_str = cutoff.map(|c: chrono::DateTime<chrono::Utc>| c.to_rfc3339());
    // The cap counts ADMIN ACTS, not chain entries — `read_recent_by_types` filters in SQL — so a
    // wide range costs what its answer costs. Scanning the whole chain to discard member traffic
    // would put the heaviest read in the daemon behind a UI panel.
    const LEDGER_CAP: u64 = 5_000;

    let (raw, read_error) = match chain.read_recent_by_types(
        cutoff_str.as_deref(),
        gl::GOVERNANCE_EVENTS,
        LEDGER_CAP,
    ) {
        Ok(v) => (v, None),
        Err(e) => {
            tracing::error!("governance ledger chain read failed: {e}");
            (Vec::new(), Some(e.to_string()))
        }
    };
    let scanned = raw.len() as u64;
    // The window FILLED. There may be older admin acts this page cannot see, and a reader must be
    // told rather than shown a short list that looks complete.
    let truncated = scanned >= LEDGER_CAP;

    let now = crate::server::gate_escalation::now_secs();
    let rows = gl::project(&raw, now);
    let mut page = gl::page(
        rows,
        q.status.as_deref().unwrap_or("all"),
        q.limit.unwrap_or(500).min(2_000) as usize,
    );
    page.truncated = truncated;
    page.scanned = scanned;
    page.read_error = read_error;
    Json(page)
}

#[derive(serde::Deserialize)]
struct LedgerQuery {
    /// all | open | approved | denied | expired | recorded
    status: Option<String>,
    /// day | week | month (default) | all
    range: Option<String>,
    limit: Option<u64>,
}

/// `POST /api/operator/gate-escalation` {id, approve, reason?} — the STRONG decision channel for
/// a governance-surface write (stage 2 of dp's 2026-07-29 ruling).
///
/// Behind `operator_gate`, so the caller has proved an operator LCT by challenge/response. That
/// is what makes this channel different from `hestia gate approve` on the CLI, which is
/// authenticated only by filesystem access to HESTIA_HOME — the same access every member on this
/// box already has. Both are recorded; `via` keeps them apart, because a reader must be able to
/// tell a proof from a convenience.
#[derive(serde::Deserialize)]
struct GateEscalationDecision {
    id: String,
    approve: bool,
    #[serde(default)]
    reason: Option<String>,
}

async fn operator_gate_escalation(
    State(state): State<SharedState>,
    Json(d): Json<GateEscalationDecision>,
) -> impl IntoResponse {
    use crate::server::gate_escalation::{Channel, now_secs};

    // A DENY needs no justification; an APPROVE of a governance write does. The asymmetry is the
    // point: refusing is the default and costs nothing to explain, while permitting is the act
    // that will need to be read back later.
    if d.approve {
        let r = d.reason.as_deref().unwrap_or("").trim();
        if r.is_empty() || r.len() > 512 || r.chars().any(char::is_control) {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "error": "approving a governance-surface write requires a single-line \
                              'reason' (<=512 bytes). A deny does not — refusing is the default \
                              and permitting is what a reader will have to weigh later"
                })),
            )
                .into_response();
        }
    }

    let now = now_secs();
    let mut s = state.lock().await;
    // Witness IS finality (revised #480 review, defect 2), same shape as the MCP
    // surface: the store mutation happens first only because the witness payload
    // is built from the post-decision record, and a failed append ROLLS THE
    // DECISION BACK — an applied-but-unwitnessed ruling has no ruling hash, no
    // projector source, and no representable obligation.
    let prior = s.gate_escalations.get(&d.id).cloned();
    match s.gate_escalations.decide(
        &d.id,
        d.approve,
        "operator",
        // The SOVEREIGN role, named as a role. Who or what fills it is contingent; the
        // authority is not. dp, 2026-07-30.
        "role:constellation:sovereign",
        Channel::OperatorSession,
        None,
        d.reason.as_deref(),
        now,
    ) {
        Ok(esc) => {
            let entry = match s.append_chain(
                "gate_escalation_decided",
                serde_json::json!({
                    "escalation_id": esc.id,
                    "plugin_id": esc.plugin_id,
                    "subject_instance_lct": s.member_lct(&esc.plugin_id),
                    "tool_name": esc.tool_name,
                    "marker": esc.marker,
                    "status": esc.stored_status(),
                    "decided_by": esc.decided_by,
                    "decided_role": esc.decided_role,
                    "decided_via": esc.decided_via,
                    "reason": esc.reason,
                    // Bar, evidence, sufficiency — recorded together (dp + claude-code,
                    // 2026-07-30): a reader should never have to infer whether the evidence
                    // was enough from the fact that someone said yes.
                    "bar": esc.bar,
                    "factors_present": esc.factors,
                    "bar_met": esc.bar_met(),
                    "secs_into_window": now.saturating_sub(esc.opened_at),
                }),
            ) {
                Ok(e) => e,
                Err(append_err) => {
                    // The ruling is NOT final: restore the exact pre-decision row
                    // (`decide` succeeded, so it existed) and tell the operator.
                    if let Some(p) = prior {
                        s.gate_escalations.undo_decide(p);
                    }
                    return (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(serde_json::json!({
                            "error": format!(
                                "decision NOT applied — its witness append failed \
                                 ({append_err}); the escalation stays pending and the \
                                 write stays refused"
                            ),
                            "escalation_id": d.id,
                        })),
                    )
                        .into_response();
                }
            };
            // #459: the decision's RETURN EDGE, on the channel that decides 207 of
            // 210 rulings. Minted at this layer because `EscalationStore::decide`
            // has no inbox access. Revised #480 contract: the decision entry IS
            // the witness, so the obligation anchors to its hash, and a failed
            // ensure is warned about rather than returned — the decision landed;
            // the cursor projector re-derives the obligation and retries.
            let disposition_notice_id = super::handler::ensure_disposition(
                &s,
                &esc.plugin_id,
                &format!("hestia://escalation/{}#decided", esc.id),
                &entry.hash,
            );
            // THE DECIDER SEES THE BAR — on this surface too.
            //
            // This reply used to be `{escalation_id, status, witnessEntryHash}`. #219 measured
            // what that costs: the chain entry directly above records `bar` and `bar_met`, and
            // the operator who just ruled was told neither, so an approval that `is_claimable`
            // would refuse came back looking identical to one that works. The remedy shipped
            // in `tool_gate_arbitrate_escalation` and stopped there — and THAT path has ruled
            // 3 escalations, lifetime, against 207 through this one
            // (`tools/cbp_invitation_census_1304.py`, 111,620 entries). The fix landed on the
            // surface nobody uses.
            //
            // `decision_reply` is now the single answer both callers read, so the next field
            // added to one cannot silently miss the other.
            let mut body = esc.decision_reply();
            if let Some(o) = body.as_object_mut() {
                o.insert(
                    "witnessEntryHash".into(),
                    serde_json::json!(entry.hash),
                );
                o.insert(
                    "disposition_notice_id".into(),
                    serde_json::json!(disposition_notice_id),
                );
            }
            (StatusCode::OK, Json(body)).into_response()
        }
        // Every failure mode here leaves the write refused, which is why none of them is a 500.
        Err(e) => (
            StatusCode::CONFLICT,
            Json(serde_json::json!({
                "error": e.to_string(),
                "effect": "the write stays refused",
            })),
        )
            .into_response(),
    }
}
#[cfg(test)]
mod disposition_tests {
    //! #459: petition surfaces get a return edge. Ruling a scope request or an
    //! escalation used to end at the ruling — the petitioner was never told and
    //! had to poll. These drive the two operator-side decision surfaces and
    //! assert the daemon-only `disposition` notice lands in the petitioner's
    //! inbox, witnessed first, the way `unreachable` is reported at the
    //! retirement site.
    use super::*;
    use crate::vault::Vault;
    use tempfile::TempDir;

    async fn test_state() -> (TempDir, SharedState) {
        let dir = TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = crate::server::build_state(vault, dir.path(), "p").unwrap();
        (dir, state)
    }

    /// Minting site B (#459): the operator's scope decision tells the REQUESTER.
    #[tokio::test]
    async fn a_scope_decision_reports_its_disposition_to_the_requester() {
        let (_dir, state) = test_state().await;
        let now = crate::server::gate_escalation::now_secs();
        {
            let mut s = state.lock().await;
            s.scope_requests.insert(
                "scope-test459b".into(),
                crate::server::state::ScopeRequest {
                    id: "scope-test459b".into(),
                    plugin_id: "kimi-code".into(),
                    role: String::new(),
                    path: "/x/y.md".into(),
                    reason: "needed for the task at hand".into(),
                    requested_at: now,
                    expires_at: now + 3600,
                    granted: None,
                    decided_by: None,
                    decided_at: None,
                    decision_reason: None,
                },
            );
        }
        let resp = scope_decide(
            State(state.clone()),
            Json(serde_json::json!({
                "request_id": "scope-test459b", "granted": true, "reason": "yes, that file",
            })),
        )
        .await
        .into_response();
        assert_eq!(resp.status(), StatusCode::OK, "the decision itself must land");

        let s = state.lock().await;
        // Revised #480 doctrine: the ruling IS the witness — no
        // `member_notice_disposition` entry, and the notice row anchors to the
        // scope_granted entry's hash.
        assert!(
            !s.recent_chain(20)
                .iter()
                .any(|e| e.event_type == "member_notice_disposition"),
            "the struck pre-enqueue witness must stay struck"
        );
        let ruling = s
            .recent_chain(20)
            .into_iter()
            .find(|e| e.event_type == "scope_granted")
            .expect("the decision itself must be witnessed");
        assert_eq!(
            ruling.event_data.get("request_id").and_then(|v| v.as_str()),
            Some("scope-test459b")
        );

        let mail = s.inbox_store.drain_member("kimi-code").unwrap();
        let note = mail
            .iter()
            .find(|n| n.kind == "disposition")
            .expect("the requester must learn its ask was decided: {mail:?}");
        assert_eq!(note.from_plugin, "hestia");
        assert_eq!(note.pointer_uri.as_deref(), Some("hestia://scope/scope-test459b"));
        assert_eq!(
            note.chain_hash, ruling.hash,
            "the obligation anchors to the terminal ruling, not to a notice-side entry"
        );
    }

    /// Minting site C, the operator channel (#459): deciding an escalation tells
    /// the ASKER. Same return edge as the peer-ruling path, minted here because
    /// this surface decides 207 of 210 rulings and the store layer has no inbox.
    #[tokio::test]
    async fn an_operator_escalation_decision_reports_its_disposition_to_the_asker() {
        let (_dir, state) = test_state().await;
        let esc_id = {
            let mut s = state.lock().await;
            let now = crate::server::gate_escalation::now_secs();
            s.gate_escalations
                .open("kimi-code", "", "policy_edit", "policy.json", None, None, now, 3600)
                .unwrap()
                .id
        };
        let resp = operator_gate_escalation(
            State(state.clone()),
            Json(GateEscalationDecision {
                id: esc_id.clone(),
                approve: true,
                reason: Some("reviewed the diff".into()),
            }),
        )
        .await
        .into_response();
        assert_eq!(resp.status(), StatusCode::OK, "the decision itself must land");

        let s = state.lock().await;
        let mail = s.inbox_store.drain_member("kimi-code").unwrap();
        let note = mail
            .iter()
            .find(|n| n.kind == "disposition")
            .expect("the asker must learn its escalation was decided: {mail:?}");
        assert_eq!(note.from_plugin, "hestia");
        assert_eq!(
            note.pointer_uri.as_deref(),
            Some(format!("hestia://escalation/{esc_id}#decided")).as_deref()
        );
    }

    /// Revised #480 review, defect 2, on the channel that decides 207 of 210
    /// rulings: a failed witness append rolls the decision BACK — the operator
    /// gets a 500, the escalation stays Pending, and nothing was authorised.
    #[tokio::test]
    async fn an_unwitnessed_operator_decision_is_rolled_back() {
        let (dir, state) = test_state().await;
        let esc_id = {
            let mut s = state.lock().await;
            let now = crate::server::gate_escalation::now_secs();
            s.gate_escalations
                .open("kimi-code", "", "policy_edit", "policy.json", None, None, now, 3600)
                .unwrap()
                .id
        };
        let decision = GateEscalationDecision {
            id: esc_id.clone(),
            approve: true,
            reason: Some("reviewed the diff".into()),
        };

        // RESERVED lock on witness.db: reads proceed, writes fail BUSY.
        let key = crate::storage::storage_key(dir.path(), "p").unwrap();
        let blocker = rusqlite::Connection::open(dir.path().join("witness.db")).unwrap();
        blocker.pragma_update(None, "key", hex::encode(key)).unwrap();
        blocker.execute_batch("BEGIN IMMEDIATE").unwrap();

        let resp = operator_gate_escalation(State(state.clone()), Json(decision))
            .await
            .into_response();
        assert_eq!(
            resp.status(),
            StatusCode::INTERNAL_SERVER_ERROR,
            "an unwitnessed ruling is an error, not a null-hash success"
        );
        {
            let s = state.lock().await;
            let now = crate::server::gate_escalation::now_secs();
            assert_eq!(
                s.gate_escalations.status_of(&esc_id, now),
                crate::server::gate_escalation::Status::Pending,
                "the decision was rolled back — finality requires its witness"
            );
        }
        blocker.execute_batch("COMMIT").unwrap();

        let decision = GateEscalationDecision {
            id: esc_id.clone(),
            approve: true,
            reason: Some("reviewed the diff".into()),
        };
        let resp = operator_gate_escalation(State(state.clone()), Json(decision))
            .await
            .into_response();
        assert_eq!(resp.status(), StatusCode::OK, "the retry rules cleanly");
    }

    /// Revised #480 review, blocker 3: the standing grant's SUCCESS witness is
    /// part of finality. If the terminal `scope_granted` append fails after the
    /// commit landed, the grant is rolled back (live store AND vault), the
    /// operator gets an error, and the request stays pending. Failure injected
    /// by a trigger that fails only the success insert (the intent names no
    /// `intent` key; the success entry does).
    #[tokio::test]
    async fn an_unwitnessed_standing_grant_is_rolled_back() {
        let (dir, state) = test_state().await;
        let now = crate::server::gate_escalation::now_secs();
        {
            let mut s = state.lock().await;
            s.scope_requests.insert(
                "scope-standing-rb".into(),
                crate::server::state::ScopeRequest {
                    id: "scope-standing-rb".into(),
                    plugin_id: "kimi-code".into(),
                    role: String::new(),
                    path: "/x/standing.md".into(),
                    reason: "needed durably".into(),
                    requested_at: now,
                    expires_at: now + 3600,
                    granted: None,
                    decided_by: None,
                    decided_at: None,
                    decision_reason: None,
                },
            );
        }
        let decide = |state: &SharedState| {
            let state = state.clone();
            async move {
                scope_decide(
                    State(state),
                    Json(serde_json::json!({
                        "request_id": "scope-standing-rb", "granted": true,
                        "standing": true, "reason": "durable, reviewed",
                    })),
                )
                .await
                .into_response()
            }
        };

        let key = crate::storage::storage_key(dir.path(), "p").unwrap();
        let conn = rusqlite::Connection::open(dir.path().join("witness.db")).unwrap();
        conn.pragma_update(None, "key", hex::encode(key)).unwrap();
        conn.execute_batch(
            "CREATE TRIGGER fail_scope_granted_success
             BEFORE INSERT ON chain_entries
             WHEN NEW.event_type = 'scope_granted' AND NEW.event_data LIKE '%\"intent\"%'
             BEGIN SELECT RAISE(FAIL, 'injected witness failure'); END;",
        )
        .unwrap();

        let resp = decide(&state).await;
        assert_eq!(
            resp.status(),
            StatusCode::INTERNAL_SERVER_ERROR,
            "an unwitnessed standing grant is an error, not a live permission"
        );
        {
            let s = state.lock().await;
            assert!(
                !s.standing_scope.has_live("kimi-code", "/x/standing.md", now),
                "the grant was rolled back — no live permission without its witness"
            );
            let chain = s.recent_chain(20);
            assert!(
                chain.iter().any(|e| e.event_type == "scope_grant_intent"),
                "the intent stays on the chain as the record of the rolled-back act"
            );
            assert!(
                !chain.iter().any(|e| e.event_type == "scope_granted"),
                "no terminal record exists for a grant that is not in force"
            );
            assert_eq!(
                s.scope_requests["scope-standing-rb"].granted, None,
                "the request stays pending — a re-decide is the retry"
            );
        }
        conn.execute_batch("DROP TRIGGER fail_scope_granted_success")
            .unwrap();

        let resp = decide(&state).await;
        assert_eq!(resp.status(), StatusCode::OK, "the retry rules cleanly");
        let s = state.lock().await;
        assert!(s.standing_scope.has_live("kimi-code", "/x/standing.md", now));
    }

    /// #483 finality: a society-wide widening is not in force until its terminal
    /// `society_floor_added` record lands. Failure restores the exact prior store, then an
    /// identical retry succeeds once witnessing is available again.
    #[tokio::test]
    async fn an_unwitnessed_society_floor_change_is_rolled_back() {
        let (dir, state) = test_state().await;
        let add = |state: &SharedState| {
            let state = state.clone();
            async move {
                scope_floor_add(
                    State(state),
                    Json(serde_json::json!({
                        "path": "/x/society",
                        "reason": "common working surface",
                    })),
                )
                .await
                .into_response()
            }
        };

        let key = crate::storage::storage_key(dir.path(), "p").unwrap();
        let conn = rusqlite::Connection::open(dir.path().join("witness.db")).unwrap();
        conn.pragma_update(None, "key", hex::encode(key)).unwrap();
        conn.execute_batch(
            "CREATE TRIGGER fail_society_floor_success
             BEFORE INSERT ON chain_entries
             WHEN NEW.event_type = 'society_floor_added'
             BEGIN SELECT RAISE(FAIL, 'injected witness failure'); END;",
        )
        .unwrap();

        let resp = add(&state).await;
        assert_eq!(resp.status(), StatusCode::INTERNAL_SERVER_ERROR);
        {
            let s = state.lock().await;
            assert!(
                !s.standing_scope.floor_allows("/x/society"),
                "a society-wide permission without its terminal witness must be rolled back"
            );
            assert_eq!(s.standing_scope.generation, 0, "rollback restores generation too");
            let chain = s.recent_chain(20);
            assert!(chain.iter().any(|e| e.event_type == "society_floor_intent"));
            assert!(!chain.iter().any(|e| e.event_type == "society_floor_added"));
        }
        conn.execute_batch("DROP TRIGGER fail_society_floor_success")
            .unwrap();

        let resp = add(&state).await;
        assert_eq!(resp.status(), StatusCode::OK, "the identical retry lands cleanly");
        let s = state.lock().await;
        assert!(s.standing_scope.floor_allows("/x/society"));
        assert_eq!(s.standing_scope.generation, 1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Vault;
    use crate::server::state::ServerState;

    fn make_shared_state() -> (tempfile::TempDir, SharedState) {
        let dir = tempfile::TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = ServerState::open(vault, dir.path(), "p").unwrap();
        (dir, Arc::new(tokio::sync::Mutex::new(state)))
    }

    /// Issue #482 regression probe: a governance-ledger read must NOT hold the
    /// global state lock. Before 14be6a5 the handler held `state.lock()` across
    /// the whole SQL read + projection + paging (8–15s on the live chain), so the
    /// dashboard's own poll starved every other caller — and the plugin gate's
    /// witness budget is 1.5s. The acceptance question is therefore: while
    /// ledger reads are in flight, how long does an UNRELATED state-lock
    /// acquisition wait? That is a wall-clock quantity by definition, and that
    /// is what this test measures.
    ///
    /// Construction:
    /// 1. Seed a chain whose rows carry a large padding field, then run ONE
    ///    ledger read to calibrate: `read` is what the expensive section costs
    ///    on THIS box (~2s here; the padding keeps it from collapsing to
    ///    nothing on a fast box — every row is fetched and its event_data
    ///    parsed). The calibration response is also checked field by field:
    ///    the lock change must not change the ledger's answer.
    /// 2. Hold the state lock, spawn ONE reader (it signals `started` and parks
    ///    on the lock in the same poll), then drop the guard and immediately
    ///    re-acquire, timing the wait. `tokio::sync::Mutex` grants fairly, so
    ///    the wait is exactly the reader's lock hold: microseconds under the
    ///    fix (an `Arc::clone`), a full read under the old shape.
    ///
    /// Why the spinner tasks: this probe depends on a woken waiter being
    /// POLLED promptly, and empirically it is not. The reader's read is
    /// synchronous, so once it starts it occupies its worker for the whole
    /// read; a waiter woken into that worker's local queue is not looked at
    /// until the read ends, and on a loaded box no parked worker came to steal
    /// it — measured here: a woken waiter sat unpolled behind NINE completed
    /// 410ms reads on a 14-worker runtime. The spinners (`yield_now` in a loop)
    /// keep every other worker awake and stealing, so a woken waiter is polled
    /// within microseconds. With them, the measured wait is the lock hold and
    /// nothing else.
    ///
    /// Why the margins are safe:
    /// * Fixed code: the wait is one `Arc::clone` hold plus one task handoff —
    ///   microseconds to single-digit milliseconds — against a 1s bound. The
    ///   bound does NOT depend on the read being slow, so the test cannot flake
    ///   on a fast box, and the measured interval starts inside the test task
    ///   itself, so the test's own scheduling latency before the measurement
    ///   is not part of it.
    /// * Old shape: the wait is a full read. The primary bound (1s, against the
    ///   gate's 1.5s witness budget) catches it wherever a padded read costs
    ///   >1s; the comparative bound (wait < read/4, applied only when the
    ///   calibration read is >= 100ms) catches it on any box where the read is
    ///   measurable at all, because under the old shape wait == read.
    /// * Earlier versions of this test failed in instructive ways, recorded so
    ///   they are not re-tried: (a) asserting `JoinHandle::is_finished` at the
    ///   re-acquisition point PASSED against the old shape (the guard's drop
    ///   at function end races the task's completion mark) and FAILED against
    ///   the fixed shape when the read was short (a ~10ms read is the same
    ///   order as wakeup latency); (b) amplifying with K queued readers
    ///   serialized the readers themselves on one worker — K x read even with
    ///   the fix — because nobody was awake to steal the woken waiters.
    #[tokio::test(flavor = "multi_thread", worker_threads = 8)]
    async fn governance_ledger_read_does_not_hold_the_state_lock() {
        // ~77MB of event_data in total: the read costs ~2s on the 2026-08 WSL
        // dev box. ROWS stays well under LEDGER_CAP (5000) so every seeded act
        // is scanned; the per-row pad is what the fetch + parse pays for.
        const ROWS: usize = 1_200;
        const PAD: usize = 65_536;

        let (_dir, state) = make_shared_state();
        {
            let s = state.lock().await;
            let pad = "x".repeat(PAD);
            for i in 0..ROWS {
                s.append_chain(
                    "policy_edit",
                    serde_json::json!({"change": "add_rule", "rule_id": format!("r{i}"), "pad": pad}),
                )
                .unwrap();
            }
        }

        let spawn_handler = |state: &SharedState| {
            let (started_tx, started_rx) = tokio::sync::oneshot::channel::<()>();
            let handle = tokio::spawn({
                let state = Arc::clone(state);
                async move {
                    let _ = started_tx.send(());
                    governance_ledger(
                        State(state),
                        Query(LedgerQuery {
                            status: None,
                            range: Some("all".into()),
                            limit: Some(2_000),
                        }),
                    )
                    .await
                    .into_response()
                }
            });
            (handle, started_rx)
        };

        // Calibrate: one full ledger read — and check the answer while at it:
        // every seeded admin act, no read error (the lock change must not
        // change the ledger's semantics).
        let t = std::time::Instant::now();
        let (h, started) = spawn_handler(&state);
        started.await.unwrap();
        let resp = h.await.unwrap();
        let read = t.elapsed();
        assert_eq!(resp.status(), StatusCode::OK);
        let body = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let page: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(page["scanned"].as_u64(), Some(ROWS as u64));
        assert_eq!(page["rows"].as_array().map(Vec::len), Some(ROWS));
        assert!(page.get("read_error").is_none());

        // The spinners: keep every other worker awake and stealing, so the
        // woken waiter below is polled promptly (see the doc comment).
        let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let mut spinners = Vec::new();
        for _ in 0..6 {
            let stop = Arc::clone(&stop);
            spinners.push(tokio::spawn(async move {
                while !stop.load(std::sync::atomic::Ordering::Relaxed) {
                    tokio::task::yield_now().await;
                }
            }));
        }

        let guard = state.lock().await;
        let (h, started) = spawn_handler(&state);
        started.await.unwrap();
        // The handler signalled started and parked on the lock in the same
        // poll; the settle is belt-and-braces. A laggard would only weaken
        // old-shape discrimination, never fail the fixed code.
        tokio::time::sleep(Duration::from_millis(20)).await;

        let t_drop = std::time::Instant::now();
        drop(guard);
        let reacquired = state.lock().await;
        let wait = t_drop.elapsed();
        stop.store(true, std::sync::atomic::Ordering::Relaxed);
        drop(reacquired);

        assert!(
            wait < Duration::from_secs(1),
            "an unrelated state-lock acquisition waited {wait:?} behind one in-flight \
             ledger read (calibrated at {read:?} on this box) — the read is holding the \
             global lock again (issue #482: the gate's 1.5s witness budget starves \
             behind a dashboard poll)"
        );
        if read >= Duration::from_millis(100) {
            assert!(
                wait < read / 4,
                "the state-lock wait {wait:?} is a substantial fraction of the full \
                 ledger read {read:?} — the read is serialized behind the state lock \
                 again (issue #482)"
            );
        }

        // The reader completes without ever needing the state lock again.
        assert_eq!(h.await.unwrap().status(), StatusCode::OK);
        for s in spinners {
            s.await.unwrap();
        }
    }
}
