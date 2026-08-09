//! Dashboard hub tab — daemon-side client for a Web4 hub (join + discuss).
//!
//! The dashboard card drives these `/api/hub/*` endpoints; the DAEMON does the
//! network calls and the signing, with hestia's own member identity from the
//! vault (`ai_identity_*` — the SAME identity `hestia hub join` / `profile push`
//! use, so the CLI and the dashboard are one member, not two). Browser-side
//! there is no key material and no cross-origin call: the tab works against a
//! hub behind any tunnel (trycloudflare, tailscale funnel) without CORS.
//!
//! Routes ride the operator surface (bearer session), so every act here is
//! operator-driven: reads are cheap, and the consequential acts (join, topic,
//! post — outward messages on behalf of this hestia's identity) happen only for
//! a signed-in operator. The acts themselves are witnessed by the HUB's
//! hash-chained ledger (each response carries the entry index/hash), which is
//! the record of consequence for these remote acts.
//!
//! The hub address is hardwired for the demo (env `HESTIA_HUB_URL` overrides).

use axum::{extract::State, response::IntoResponse, Json};
use serde::Deserialize;
use uuid::Uuid;

use crate::hub::{HubClient, JoinOutcome, SignedEnvelope};
use crate::server::state::SharedState;
use crate::vault::{Vault, VaultEntry};
use web4_core::crypto::KeyPair;

/// Demo hub behind the cloudflare quick tunnel (2026-08-08 hackathon).
/// Quick-tunnel hostnames are ephemeral — override with `HESTIA_HUB_URL`
/// when the tunnel moves.
const DEFAULT_HUB_URL: &str =
    "https://meaning-hospital-ahead-instrumentation.trycloudflare.com";

/// Network budget per upstream call. The tunnel adds latency; a dead tunnel
/// must fail the card, not hang the daemon worker.
const NET_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(12);

fn hub_url() -> String {
    std::env::var("HESTIA_HUB_URL")
        .ok()
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| DEFAULT_HUB_URL.to_string())
}

/// Discovery may advertise a relative REST path (e.g. "/v1"); make it absolute.
fn abs_rest(base: &str, rest: &str) -> String {
    if rest.starts_with("http://") || rest.starts_with("https://") {
        rest.trim_end_matches('/').to_string()
    } else {
        format!("{}/{}", base.trim_end_matches('/'), rest.trim_matches('/'))
    }
}

fn hex_to_32(s: &str) -> Option<[u8; 32]> {
    let s = s.trim();
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[2 * i..2 * i + 2], 16).ok()?;
    }
    Some(out)
}

/// Read the member identity from the vault if provisioned (no side effects).
fn read_member_identity(vault: &Vault) -> Option<(Uuid, KeyPair)> {
    let lct_e = vault.get("ai_identity_lct_id")?;
    let sec_e = vault.get("ai_identity_secret")?;
    let lct = Uuid::parse_str(&lct_e.secret).ok()?;
    let bytes = hex_to_32(&sec_e.secret)?;
    Some((lct, KeyPair::from_secret_bytes(&bytes)))
}

/// Load-or-provision the member identity — mirror of the CLI's
/// `ensure_member_identity` (same vault keys), so dashboard and CLI share
/// one member LCT and the hub pins one key for both.
fn ensure_member_identity(vault: &mut Vault) -> anyhow::Result<(Uuid, KeyPair)> {
    if let Some(found) = read_member_identity(vault) {
        return Ok(found);
    }
    let kp = KeyPair::generate();
    let lct = Uuid::new_v4();
    let secret_hex: String = kp
        .secret_key_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    vault.add(
        VaultEntry::new("ai_identity_lct_id", lct.to_string()).with_tags(vec!["identity".into()]),
    )?;
    vault.add(
        VaultEntry::new("ai_identity_pubkey", kp.verifying_key().to_hex())
            .with_tags(vec!["identity".into()]),
    )?;
    vault.add(
        VaultEntry::new("ai_identity_secret", secret_hex)
            .with_tags(vec!["identity".into(), "secret".into()]),
    )?;
    Ok((lct, kp))
}

fn err_json(status: axum::http::StatusCode, msg: String) -> axum::response::Response {
    (status, Json(serde_json::json!({ "error": msg }))).into_response()
}

async fn discover_with_timeout(
    url: &str,
) -> anyhow::Result<crate::hub::HubInfo> {
    let client = HubClient::new();
    tokio::time::timeout(NET_TIMEOUT, client.discover(url))
        .await
        .map_err(|_| anyhow::anyhow!("hub discovery timed out after {:?}", NET_TIMEOUT))?
}

/// GET /api/hub/status — hub reachability + our identity state. Read-only.
pub async fn hub_status(State(state): State<SharedState>) -> impl IntoResponse {
    let url = hub_url();
    let identity = {
        let s = state.lock().await;
        read_member_identity(&s.vault).map(|(lct, kp)| (lct, kp.verifying_key().to_hex()))
    };
    let (member_lct, member_pubkey) = match identity {
        Some((l, p)) => (Some(l.to_string()), Some(p)),
        None => (None, None),
    };

    match discover_with_timeout(&url).await {
        Ok(info) => Json(serde_json::json!({
            "url": url,
            "reachable": true,
            "hub_lct_id": info.hub_lct_id,
            "hubs": info.hubs,
            "member_lct": member_lct,
            "member_pubkey": member_pubkey,
        }))
        .into_response(),
        Err(e) => Json(serde_json::json!({
            "url": url,
            "reachable": false,
            "error": e.to_string(),
            "member_lct": member_lct,
            "member_pubkey": member_pubkey,
        }))
        .into_response(),
    }
}

#[derive(Deserialize)]
pub struct JoinReq {
    #[serde(default)]
    pub name: Option<String>,
}

/// POST /api/hub/join — provision (if needed) the member identity and self-add
/// to the hardwired hub. Closed admission comes back as `pending`.
pub async fn hub_join(
    State(state): State<SharedState>,
    Json(req): Json<JoinReq>,
) -> impl IntoResponse {
    let url = hub_url();

    // Provision under the lock, then release it before any network await —
    // holding the daemon-wide mutex across a tunnel round-trip would stall
    // every other handler.
    let (member_lct, keypair) = {
        let mut s = state.lock().await;
        match ensure_member_identity(&mut s.vault) {
            Ok(v) => v,
            Err(e) => {
                return err_json(
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    format!("provisioning member identity: {e}"),
                )
            }
        }
    };

    let info = match discover_with_timeout(&url).await {
        Ok(i) => i,
        Err(e) => return err_json(axum::http::StatusCode::BAD_GATEWAY, e.to_string()),
    };
    let rest = abs_rest(&url, &info.endpoints.rest);

    let client = HubClient::new();
    let joined = tokio::time::timeout(
        NET_TIMEOUT,
        client.join(&rest, info.hub_lct_id, member_lct, &keypair, req.name),
    )
    .await;

    match joined {
        Err(_) => err_json(
            axum::http::StatusCode::GATEWAY_TIMEOUT,
            "join timed out".into(),
        ),
        Ok(Err(e)) => err_json(axum::http::StatusCode::BAD_GATEWAY, e.to_string()),
        Ok(Ok(JoinOutcome::Admitted(resp))) => Json(serde_json::json!({
            "status": "admitted",
            "member_lct": member_lct,
            "detail": resp,
        }))
        .into_response(),
        Ok(Ok(JoinOutcome::Escalated { reason })) => Json(serde_json::json!({
            "status": "pending",
            "member_lct": member_lct,
            "reason": reason,
        }))
        .into_response(),
    }
}

/// GET /api/hub/topics — the discussion, topics with posts. Unauthenticated on
/// the hub side; proxied here so the browser never needs cross-origin access.
pub async fn hub_topics(State(_state): State<SharedState>) -> impl IntoResponse {
    let url = hub_url();
    let info = match discover_with_timeout(&url).await {
        Ok(i) => i,
        Err(e) => return err_json(axum::http::StatusCode::BAD_GATEWAY, e.to_string()),
    };
    let rest = abs_rest(&url, &info.endpoints.rest);
    let http = reqwest::Client::new();

    let list_url = format!("{rest}/hubs/{}/topics", info.hub_lct_id);
    let list: serde_json::Value = match tokio::time::timeout(NET_TIMEOUT, async {
        http.get(&list_url).send().await?.json().await
    })
    .await
    {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => {
            return err_json(
                axum::http::StatusCode::BAD_GATEWAY,
                format!("listing topics: {e}"),
            )
        }
        Err(_) => {
            return err_json(axum::http::StatusCode::GATEWAY_TIMEOUT, "topics timed out".into())
        }
    };

    // Enrich each topic with its posts (best-effort; a topic whose detail read
    // fails still appears, postless, rather than sinking the whole card).
    let mut topics = list
        .get("topics")
        .and_then(|t| t.as_array())
        .cloned()
        .unwrap_or_default();
    for t in topics.iter_mut() {
        let tid = t
            .get("topic_id")
            .or_else(|| t.get("id"))
            .and_then(|v| v.as_str())
            .map(str::to_string);
        if let Some(tid) = tid {
            let detail_url = format!("{rest}/hubs/{}/topics/{tid}", info.hub_lct_id);
            if let Ok(Ok(detail)) = tokio::time::timeout(NET_TIMEOUT, async {
                http.get(&detail_url).send().await?.json::<serde_json::Value>().await
            })
            .await
            {
                let posts = detail
                    .get("posts")
                    .or_else(|| detail.get("topic").and_then(|x| x.get("posts")))
                    .cloned()
                    .unwrap_or(serde_json::Value::Array(vec![]));
                t["posts"] = posts;
            }
        }
    }

    Json(serde_json::json!({ "hub_lct_id": info.hub_lct_id, "topics": topics })).into_response()
}

#[derive(Deserialize)]
pub struct TopicReq {
    pub title: String,
}

#[derive(Deserialize)]
pub struct PostReq {
    pub topic_id: Uuid,
    pub body: String,
}

/// Shared act path: challenge → SignedEnvelope → POST /events. The hub
/// law-evaluates the act and commits it to its ledger; we pass its verdict
/// (including a deny) through to the card verbatim.
async fn submit_act(
    state: &SharedState,
    payload: serde_json::Value,
) -> axum::response::Response {
    let url = hub_url();

    let identity = {
        let s = state.lock().await;
        read_member_identity(&s.vault)
    };
    let Some((member_lct, keypair)) = identity else {
        return err_json(
            axum::http::StatusCode::CONFLICT,
            "no member identity yet — join the hub first".into(),
        );
    };

    let info = match discover_with_timeout(&url).await {
        Ok(i) => i,
        Err(e) => return err_json(axum::http::StatusCode::BAD_GATEWAY, e.to_string()),
    };
    let rest = abs_rest(&url, &info.endpoints.rest);
    let client = HubClient::new();

    let outcome = tokio::time::timeout(NET_TIMEOUT, async {
        let challenge = client.challenge(&rest, member_lct).await?;
        let envelope = SignedEnvelope::create(challenge.nonce, payload, member_lct, &keypair);
        let events_url = format!("{rest}/hubs/{}/events", info.hub_lct_id);
        let resp = reqwest::Client::new()
            .post(&events_url)
            .json(&envelope)
            .send()
            .await?;
        let status = resp.status();
        let body: serde_json::Value = resp
            .json()
            .await
            .unwrap_or_else(|_| serde_json::json!({ "note": "non-JSON hub response" }));
        anyhow::Ok((status, body))
    })
    .await;

    match outcome {
        Err(_) => err_json(axum::http::StatusCode::GATEWAY_TIMEOUT, "act timed out".into()),
        Ok(Err(e)) => err_json(axum::http::StatusCode::BAD_GATEWAY, e.to_string()),
        Ok(Ok((status, body))) => {
            let code = axum::http::StatusCode::from_u16(status.as_u16())
                .unwrap_or(axum::http::StatusCode::BAD_GATEWAY);
            (code, Json(body)).into_response()
        }
    }
}

/// POST /api/hub/topic — open a governance topic on the hub.
pub async fn hub_topic_create(
    State(state): State<SharedState>,
    Json(req): Json<TopicReq>,
) -> impl IntoResponse {
    submit_act(
        &state,
        serde_json::json!({ "action": "create_topic", "title": req.title }),
    )
    .await
}

/// POST /api/hub/post — post to a topic on the hub.
pub async fn hub_post(
    State(state): State<SharedState>,
    Json(req): Json<PostReq>,
) -> impl IntoResponse {
    submit_act(
        &state,
        serde_json::json!({ "action": "add_post", "body": req.body, "topic_id": req.topic_id }),
    )
    .await
}
