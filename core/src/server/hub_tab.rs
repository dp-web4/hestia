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

/// Last-resort hub address, used only when neither `HESTIA_HUB_URL` nor a
/// vault-stored known-hub list resolves one. Quick-tunnel hostnames are
/// ephemeral — this is a compiled fallback, not the configuration surface. The
/// configuration surface is the editable list ([`HubUrls`]) and the env
/// override, both of which take precedence and neither of which needs a rebuild.
const DEFAULT_HUB_URL: &str =
    "https://meaning-hospital-ahead-instrumentation.trycloudflare.com";

/// The vault key under which the known-hub list is stored (config-in-vault:
/// PRD_CONFIG_IN_VAULT). The list is not a secret, but the vault is hestia's
/// persistent, encrypted-at-rest config store, so a hub address the daemon will
/// talk to on the operator's behalf lives there and survives restart.
const HUB_URLS_VAULT_KEY: &str = "hub_urls";

/// Network budget per upstream call. The tunnel adds latency; a dead tunnel
/// must fail the card, not hang the daemon worker.
const NET_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(12);

/// One entry in the operator-editable known-hub list.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct HubUrlEntry {
    /// Normalised absolute URL (scheme + host, no trailing slash).
    pub url: String,
    /// Optional operator label ("demo tunnel", "fly prod", …).
    #[serde(default)]
    pub label: Option<String>,
    /// When it was added (RFC3339). Diagnostic only.
    #[serde(default)]
    pub added_at: Option<String>,
}

/// The persisted known-hub list plus which one is active.
///
/// Editable at runtime through `/api/hub/urls*` — the whole point is to point
/// the daemon at a different hub **without a rebuild or a relaunch**. Persisted
/// as JSON in the vault under [`HUB_URLS_VAULT_KEY`].
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct HubUrls {
    /// The URL the daemon uses (unless the env override is set). Must be one of
    /// `entries`, or `None` (then resolution falls to the first entry).
    #[serde(default)]
    pub active: Option<String>,
    #[serde(default)]
    pub entries: Vec<HubUrlEntry>,
}

/// Where the currently-resolved hub URL came from — surfaced to the UI so an
/// operator can see *why* the daemon is talking to a given hub, not just which.
#[derive(Debug, Clone, Copy, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HubUrlSource {
    /// `HESTIA_HUB_URL` env override — wins over everything, unchanged behaviour.
    Env,
    /// The `active` selection in the vault list.
    Active,
    /// No active set: the first entry in the list.
    FirstEntry,
    /// Nothing configured: the compiled [`DEFAULT_HUB_URL`].
    Default,
}

/// Normalise a URL for storage/compare: trim, strip a trailing slash. Returns
/// `None` for anything that is not an http(s) URL — the list must never hold a
/// value the client cannot dial.
fn normalise_hub_url(raw: &str) -> Option<String> {
    let s = raw.trim().trim_end_matches('/').to_string();
    if s.starts_with("http://") || s.starts_with("https://") {
        // A bare scheme with no host is not dialable.
        let host = s.trim_start_matches("https://").trim_start_matches("http://");
        if host.is_empty() { None } else { Some(s) }
    } else {
        None
    }
}

impl HubUrls {
    /// Load the list from the vault, or an empty list if unset/corrupt. A corrupt
    /// blob is treated as empty rather than an error: the daemon must still
    /// resolve *a* hub (falling through to env/default), never hang the card on
    /// unparseable config.
    fn load(vault: &Vault) -> Self {
        vault
            .get(HUB_URLS_VAULT_KEY)
            .and_then(|e| serde_json::from_str::<HubUrls>(&e.secret).ok())
            .unwrap_or_default()
    }

    /// Persist (upsert — create or replace). Auto-saves the encrypted vault.
    fn store(&self, vault: &mut Vault) -> anyhow::Result<()> {
        let json = serde_json::to_string(self)?;
        vault.upsert(
            VaultEntry::new(HUB_URLS_VAULT_KEY, json).with_tags(vec!["config".into(), "hub".into()]),
        )?;
        Ok(())
    }

    fn contains(&self, url: &str) -> bool {
        self.entries.iter().any(|e| e.url == url)
    }
}

/// Resolve the hub URL the daemon should use right now, and say where it came
/// from. Precedence: env override → vault active → first vault entry → default.
fn resolve_hub_url(vault: &Vault) -> (String, HubUrlSource) {
    if let Some(env) = std::env::var("HESTIA_HUB_URL")
        .ok()
        .and_then(|s| normalise_hub_url(&s))
    {
        return (env, HubUrlSource::Env);
    }
    resolve_from_list(&HubUrls::load(vault))
}

/// The env-independent half of resolution: active → first entry → default.
/// Split out so precedence is testable without touching the process-global env.
fn resolve_from_list(list: &HubUrls) -> (String, HubUrlSource) {
    if let Some(active) = list.active.as_ref().filter(|a| list.contains(a)) {
        return (active.clone(), HubUrlSource::Active);
    }
    if let Some(first) = list.entries.first() {
        return (first.url.clone(), HubUrlSource::FirstEntry);
    }
    (DEFAULT_HUB_URL.to_string(), HubUrlSource::Default)
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

/// GET /api/hub/memberships — every known hub, with whether this node is ACTUALLY
/// ENROLLED in it, asked of the hub rather than inferred locally.
///
/// The distinction is the point. Holding a member identity in the vault says only that
/// this node has *an* identity; it says nothing about whether any particular hub has
/// admitted it. The old hubs card inferred "joined" from the local identity, which is
/// the same class of error as reading a green health check as proof of currency. So
/// enrollment is probed: `GET /v1/hubs/{hub}/members/{me}/pubkey` answers 200 when the
/// hub has this LCT pinned and 404 when it does not. Only those two answers set
/// `enrolled`; any other status leaves it `null` and reports `probe_error`, because
/// a 500 -- or the same route's 404 for a mismatched hub id -- says nothing about
/// membership and must not be rendered as "not a member".
///
/// Read-only, and every probe is bounded by `NET_TIMEOUT`; an unreachable hub reports
/// `reachable: false` and an UNKNOWN enrollment rather than a false negative — "we could
/// not ask" must never render as "you are not a member".
pub async fn hub_memberships(State(state): State<SharedState>) -> impl IntoResponse {
    let (entries, active, me) = {
        let s = state.lock().await;
        let list = HubUrls::load(&s.vault);
        let me = read_member_identity(&s.vault).map(|(lct, _)| lct);
        (list.entries, list.active, me)
    };

    let http = reqwest::Client::new();
    let mut out = Vec::new();
    for e in entries {
        let mut row = serde_json::json!({
            "url": e.url,
            "label": e.label,
            "active": Some(&e.url) == active.as_ref(),
            "reachable": false,
            "hub_lct_id": serde_json::Value::Null,
            "hub_name": serde_json::Value::Null,
            // `null` means UNASKED/UNKNOWN, never "no". Only an answered probe sets a bool.
            "enrolled": serde_json::Value::Null,
        });
        if let Ok(info) = discover_with_timeout(&e.url).await {
            row["reachable"] = serde_json::json!(true);
            row["hub_lct_id"] = serde_json::json!(info.hub_lct_id);
            if let Some(h) = info.hubs.first() {
                row["hub_name"] = serde_json::json!(h.name);
            }
            if let Some(me) = me {
                let probe = format!(
                    "{}/v1/hubs/{}/members/{}/pubkey",
                    e.url.trim_end_matches('/'), info.hub_lct_id, me
                );
                if let Ok(Ok(resp)) =
                    tokio::time::timeout(NET_TIMEOUT, http.get(&probe).send()).await
                {
                    // Only two answers are informative. 200 means the hub has this
                    // LCT pinned. 404 means "no pinned pubkey" -- BUT the same route
                    // also 404s when the hub_id in the path does not match the hub,
                    // and that 404 says nothing about membership. Verified live: a
                    // wrong hub id returns `hub id X does not match this hub Y`.
                    // Anything else (500, 403, a proxy's error page) is likewise not
                    // a statement about membership, so it stays UNKNOWN. Mapping
                    // every non-200 to `false` would render a broken hub as a
                    // confident "not a member" -- the failure this endpoint exists
                    // to avoid, in the direction that misleads.
                    let status = resp.status();
                    if status.is_success() {
                        row["enrolled"] = serde_json::json!(true);
                    } else if status.as_u16() == 404 {
                        let body = resp.text().await.unwrap_or_default();
                        if body.contains("does not match this hub") {
                            row["probe_error"] =
                                serde_json::json!("hub id mismatch — enrollment not determined");
                        } else {
                            row["enrolled"] = serde_json::json!(false);
                        }
                    } else {
                        row["probe_error"] = serde_json::json!(format!("probe HTTP {status}"));
                    }
                }
            }
        }
        out.push(row);
    }

    Json(serde_json::json!({
        "member_lct": me.map(|m| m.to_string()),
        "hubs": out,
        // Capabilities this build actually has, so the UI can render honest controls
        // instead of buttons that silently do nothing (dp, 2026-09-01).
        "supported": {
            "apply": true,
            "remove_from_list": true,
            // No member-initiated departure exists: the hub has an operator-only
            // /admin/api/members/:id/remove and no withdraw route or event.
            // Tracked as a hub-side gap against PRD_HUB_V2_FEDERATED R8.2 (exit).
            "withdraw": false,
            // Discovery today is "paste a URL"; there is no registry to search.
            "discover": false
        }
    }))
    .into_response()
}

/// GET /api/hub/status — hub reachability + our identity state. Read-only.
pub async fn hub_status(State(state): State<SharedState>) -> impl IntoResponse {
    let (url, url_source, identity) = {
        let s = state.lock().await;
        let (url, src) = resolve_hub_url(&s.vault);
        let identity =
            read_member_identity(&s.vault).map(|(lct, kp)| (lct, kp.verifying_key().to_hex()));
        (url, src, identity)
    };
    let _ = url_source; // (reachability payload already carries `url`; source is on /api/hub/urls)
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

// ─────────────────────────────────────────────────────────────────────────
// Known-hub list — view / add / remove / select, all at runtime, no rebuild.
// ─────────────────────────────────────────────────────────────────────────

/// Build the `/api/hub/urls` response body: the list, the active selection, and
/// the URL that would actually be dialed right now plus WHERE it resolved from
/// (so the UI can show `env`-override precedence honestly rather than implying
/// the list is in control when it is not).
fn hub_urls_response(vault: &Vault) -> serde_json::Value {
    let list = HubUrls::load(vault);
    let (resolved, source) = resolve_hub_url(vault);
    serde_json::json!({
        "active": list.active,
        "entries": list.entries,
        "resolved": resolved,
        "source": source,
        // A truthful UI note: while the env override is set it wins over any
        // selection here, so editing the list will not change the dialed hub.
        "env_override_active": matches!(source, HubUrlSource::Env),
    })
}

/// GET /api/hub/urls — view the known-hub list, the active pick, and what
/// resolves right now.
pub async fn hub_urls_list(State(state): State<SharedState>) -> impl IntoResponse {
    let s = state.lock().await;
    Json(hub_urls_response(&s.vault)).into_response()
}

#[derive(Deserialize)]
pub struct HubUrlAddReq {
    pub url: String,
    #[serde(default)]
    pub label: Option<String>,
    /// Make this the active hub in the same call (default: activate iff it is
    /// the only entry, so a first add is usable immediately).
    #[serde(default)]
    pub activate: Option<bool>,
}

/// POST /api/hub/urls — add a hub to the list (idempotent on URL).
pub async fn hub_urls_add(
    State(state): State<SharedState>,
    Json(req): Json<HubUrlAddReq>,
) -> impl IntoResponse {
    let Some(url) = normalise_hub_url(&req.url) else {
        return err_json(
            axum::http::StatusCode::BAD_REQUEST,
            format!("not a dialable http(s) URL: {:?}", req.url),
        );
    };
    let mut s = state.lock().await;
    let mut list = HubUrls::load(&s.vault);

    if let Some(existing) = list.entries.iter_mut().find(|e| e.url == url) {
        // Idempotent: re-adding updates the label rather than duplicating.
        if req.label.is_some() {
            existing.label = req.label.clone();
        }
    } else {
        list.entries.push(HubUrlEntry {
            url: url.clone(),
            label: req.label.clone(),
            added_at: Some(chrono::Utc::now().to_rfc3339()),
        });
    }

    let first_and_only = list.entries.len() == 1;
    if req.activate.unwrap_or(first_and_only) {
        list.active = Some(url.clone());
    }

    if let Err(e) = list.store(&mut s.vault) {
        return err_json(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            format!("persisting hub list: {e}"),
        );
    }
    Json(hub_urls_response(&s.vault)).into_response()
}

#[derive(Deserialize)]
pub struct HubUrlRefReq {
    pub url: String,
}

/// DELETE /api/hub/urls — remove a hub from the list. If it was the active pick,
/// active clears (resolution falls to the first remaining entry, then env/default).
pub async fn hub_urls_remove(
    State(state): State<SharedState>,
    Json(req): Json<HubUrlRefReq>,
) -> impl IntoResponse {
    // Normalise the same way it was stored, so a caller passing a trailing slash
    // still matches. If it is not a URL at all, nothing could match — say so.
    let Some(url) = normalise_hub_url(&req.url) else {
        return err_json(
            axum::http::StatusCode::BAD_REQUEST,
            format!("not a URL: {:?}", req.url),
        );
    };
    let mut s = state.lock().await;
    let mut list = HubUrls::load(&s.vault);
    let before = list.entries.len();
    list.entries.retain(|e| e.url != url);
    if list.entries.len() == before {
        return err_json(
            axum::http::StatusCode::NOT_FOUND,
            format!("not in the list: {url}"),
        );
    }
    if list.active.as_deref() == Some(url.as_str()) {
        list.active = None;
    }
    if let Err(e) = list.store(&mut s.vault) {
        return err_json(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            format!("persisting hub list: {e}"),
        );
    }
    Json(hub_urls_response(&s.vault)).into_response()
}

/// PUT /api/hub/urls/active — select which known hub the daemon uses. The URL
/// must already be in the list (add it first) — activating an unknown URL would
/// point the daemon at a hub the operator never reviewed.
pub async fn hub_urls_set_active(
    State(state): State<SharedState>,
    Json(req): Json<HubUrlRefReq>,
) -> impl IntoResponse {
    let Some(url) = normalise_hub_url(&req.url) else {
        return err_json(
            axum::http::StatusCode::BAD_REQUEST,
            format!("not a URL: {:?}", req.url),
        );
    };
    let mut s = state.lock().await;
    let mut list = HubUrls::load(&s.vault);
    if !list.contains(&url) {
        return err_json(
            axum::http::StatusCode::NOT_FOUND,
            format!("not in the list (add it first): {url}"),
        );
    }
    list.active = Some(url);
    if let Err(e) = list.store(&mut s.vault) {
        return err_json(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            format!("persisting hub list: {e}"),
        );
    }
    Json(hub_urls_response(&s.vault)).into_response()
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
    let url = { let s = state.lock().await; resolve_hub_url(&s.vault).0 };

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
pub async fn hub_topics(State(state): State<SharedState>) -> impl IntoResponse {
    let url = { let s = state.lock().await; resolve_hub_url(&s.vault).0 };
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
    let url = { let s = state.lock().await; resolve_hub_url(&s.vault).0 };

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vault::Vault;

    fn temp_vault() -> (tempfile::TempDir, Vault) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("vault.enc");
        let v = Vault::init(path, "p".into()).unwrap();
        (dir, v)
    }

    #[test]
    fn normalise_rejects_non_dialable_and_strips_trailing_slash() {
        assert_eq!(
            normalise_hub_url("  https://h.example/ "),
            Some("https://h.example".to_string()),
        );
        assert_eq!(normalise_hub_url("http://x"), Some("http://x".to_string()));
        // Not dialable: no scheme, bare scheme, empty.
        assert_eq!(normalise_hub_url("h.example"), None);
        assert_eq!(normalise_hub_url("https://"), None);
        assert_eq!(normalise_hub_url("   "), None);
        assert_eq!(normalise_hub_url("ftp://h"), None);
    }

    #[test]
    fn list_resolution_precedence_active_then_first_then_default() {
        // Empty list → compiled default.
        let empty = HubUrls::default();
        let (u, src) = resolve_from_list(&empty);
        assert_eq!(u, DEFAULT_HUB_URL);
        assert!(matches!(src, HubUrlSource::Default));

        // Entries but no active → first entry.
        let mut list = HubUrls {
            active: None,
            entries: vec![
                HubUrlEntry { url: "https://a".into(), label: None, added_at: None },
                HubUrlEntry { url: "https://b".into(), label: None, added_at: None },
            ],
        };
        let (u, src) = resolve_from_list(&list);
        assert_eq!(u, "https://a");
        assert!(matches!(src, HubUrlSource::FirstEntry));

        // Active set (and present) → active, even though it is not first.
        list.active = Some("https://b".into());
        let (u, src) = resolve_from_list(&list);
        assert_eq!(u, "https://b");
        assert!(matches!(src, HubUrlSource::Active));

        // Active pointing at a URL NOT in the list must not be honoured — that is
        // a stale/dangling selection, and honouring it would dial a hub the list
        // no longer vouches for. Falls back to first.
        list.active = Some("https://gone".into());
        let (u, src) = resolve_from_list(&list);
        assert_eq!(u, "https://a");
        assert!(matches!(src, HubUrlSource::FirstEntry));
    }

    #[test]
    fn list_round_trips_through_the_vault_and_survives_reopen() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("vault.enc");
        {
            let mut v = Vault::init(path.clone(), "p".into()).unwrap();
            let list = HubUrls {
                active: Some("https://one".into()),
                entries: vec![HubUrlEntry {
                    url: "https://one".into(),
                    label: Some("demo".into()),
                    added_at: Some("2026-08-09T00:00:00Z".into()),
                }],
            };
            list.store(&mut v).unwrap();
        }
        // Reopen from disk — the whole point is that config survives a restart.
        let v = Vault::open(path, "p".into()).unwrap();
        let loaded = HubUrls::load(&v);
        assert_eq!(loaded.active.as_deref(), Some("https://one"));
        assert_eq!(loaded.entries.len(), 1);
        assert_eq!(loaded.entries[0].label.as_deref(), Some("demo"));
    }

    #[test]
    fn a_corrupt_blob_reads_as_empty_not_an_error() {
        let (_dir, mut v) = temp_vault();
        // Plant a non-JSON value under the key.
        v.upsert(VaultEntry::new(HUB_URLS_VAULT_KEY, "not json {{{")).unwrap();
        let loaded = HubUrls::load(&v);
        assert!(loaded.entries.is_empty() && loaded.active.is_none());
        // And resolution still yields a usable default rather than hanging.
        let (u, src) = resolve_from_list(&loaded);
        assert_eq!(u, DEFAULT_HUB_URL);
        assert!(matches!(src, HubUrlSource::Default));
    }

    #[test]
    fn env_override_wins_over_the_list() {
        // The one test that touches the process-global env. Set → resolve → clear.
        let (_dir, mut v) = temp_vault();
        HubUrls {
            active: Some("https://list-pick".into()),
            entries: vec![HubUrlEntry {
                url: "https://list-pick".into(),
                label: None,
                added_at: None,
            }],
        }
        .store(&mut v)
        .unwrap();

        std::env::set_var("HESTIA_HUB_URL", "https://env-pick/");
        let (u, src) = resolve_hub_url(&v);
        std::env::remove_var("HESTIA_HUB_URL");

        assert_eq!(u, "https://env-pick", "env override must win and be normalised");
        assert!(matches!(src, HubUrlSource::Env));

        // With env cleared, the list pick resolves.
        let (u2, src2) = resolve_hub_url(&v);
        assert_eq!(u2, "https://list-pick");
        assert!(matches!(src2, HubUrlSource::Active));
    }
}
