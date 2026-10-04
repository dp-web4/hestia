//! F3 one-host receiver: Hub receipt-mode mailbox -> exact local member inbox.
//!
//! Custody order is non-negotiable:
//!   FETCH (non-destructive) -> durable stage -> idempotent witness ->
//!   durable member enqueue -> Hub ACK.
//!
//! Wake/session launch is deliberately absent. Address chooses the inbox; local
//! law chooses whether anything wakes. Routing of non-local destinations is in
//! receiver_routing and is deliberately separate from mailbox custody.

use anyhow::{Context, Result};
use serde::Serialize;
use serde_json::json;
use uuid::Uuid;

use crate::hub::{member_signing_keypair, HubClient, HubConnection};
use crate::member_registry::{load_members, LocalChildResolution};
use crate::receiver_routing::ReceiverRoutingTable;
use crate::storage::{SqliteChainStore, SqliteInboxStore};
use crate::vault::Vault;

pub const HUB_RECEIVE_PROTOCOL: &str = "hub-mailbox-receive-v1";
const FETCH_LIMIT: usize = 100;
const MAX_FETCH_PAGES: usize = 20;

#[derive(Debug, Clone, Serialize)]
pub struct ReceiverBindingReport {
    pub child_lct: String,
    pub plugin_id: Option<String>,
    pub binding_id: Uuid,
    pub fetched: usize,
    pub accepted_local: usize,
    pub acked: usize,
    pub remaining: Option<u64>,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReceiverDrainReport {
    pub router_lct: String,
    pub bindings: Vec<ReceiverBindingReport>,
    pub fetched: usize,
    pub accepted_local: usize,
    pub acked: usize,
    pub errors: usize,
}

fn connection_from_binding(binding: &crate::receiver_routing::LocalMailboxBinding) -> HubConnection {
    HubConnection {
        id: binding.binding_id,
        url: binding.hub_url.clone(),
        hub_lct_id: binding.hub_lct_id,
        our_lct_id: binding.hub_member_lct,
        connected_at: chrono::Utc::now(),
        last_seen: None,
        api_version: "v1".into(),
        rest_endpoint: binding.rest_endpoint.clone(),
        hubs_joined: vec![binding.hub_lct_id],
        member_key_source: binding.member_key_source.clone(),
    }
}

fn abs_rest(conn: &HubConnection) -> String {
    if conn.rest_endpoint.starts_with("http://") || conn.rest_endpoint.starts_with("https://") {
        conn.rest_endpoint.trim_end_matches('/').to_string()
    } else {
        format!(
            "{}/{}",
            conn.url.trim_end_matches('/'),
            conn.rest_endpoint.trim_matches('/')
        )
    }
}

fn value_string(v: &serde_json::Value, key: &str) -> Option<String> {
    v.get(key).and_then(|x| x.as_str()).map(str::to_string)
}

async fn open_verified_channel(
    client: &HubClient,
    vault: &Vault,
    conn: &HubConnection,
) -> Result<(crate::hub::HubChannel, web4_core::crypto::KeyPair, String)> {
    let keypair = member_signing_keypair(vault, &conn.member_key_source)
        .with_context(|| format!("resolving credential for Hub member {}", conn.our_lct_id))?;
    let rest = abs_rest(conn);

    // Identity resolution is not credential resolution (#1210). Before polling,
    // prove that the unattended key Hestia is about to use is the key the Hub
    // actually pins for this member. A stale path/config is a refusal, not a guess.
    let pinned = client
        .resolve_member_pubkey(&rest, conn.hub_lct_id, conn.our_lct_id)
        .await
        .with_context(|| format!("resolving Hub pin for {}", conn.our_lct_id))?;
    anyhow::ensure!(
        pinned.to_hex() == keypair.verifying_key().to_hex(),
        "credential mismatch for Hub member {}: configured key is not the Hub-pinned key",
        conn.our_lct_id
    );

    let channel = client
        .open_channel(&conn.url, Uuid::new_v4())
        .await
        .with_context(|| format!("opening sealed channel to {}", conn.url))?;
    anyhow::ensure!(
        channel.hub_lct_id == conn.hub_lct_id,
        "Hub discovery identity changed: connection pins {}, discovery returned {}",
        conn.hub_lct_id,
        channel.hub_lct_id
    );
    Ok((channel, keypair, rest))
}

async fn ack_one(
    client: &HubClient,
    conn: &HubConnection,
    channel: &crate::hub::HubChannel,
    keypair: &web4_core::crypto::KeyPair,
    rest: &str,
    notice_id: &str,
) -> Result<()> {
    let out = client
        .channel_query(
            rest,
            channel,
            keypair,
            conn.our_lct_id,
            "notifications_ack",
            json!({ "id": notice_id }),
        )
        .await
        .with_context(|| format!("ACK Hub notice {notice_id}"))?;
    anyhow::ensure!(
        out.get("protocol").and_then(|v| v.as_str()) == Some(HUB_RECEIVE_PROTOCOL),
        "Hub ACK returned unexpected protocol"
    );
    anyhow::ensure!(
        out.get("acknowledged").and_then(|v| v.as_bool()) == Some(true),
        "Hub ACK did not confirm acknowledged=true"
    );
    Ok(())
}

/// One complete machine-level receipt pass.
///
/// Only bindings whose canonical child LCT is explicitly parent-bound to
/// `router_lct` are polled. A stale local binding for a migrated child is not
/// default-routed and not polled: the route table may know where that child went,
/// but possession of its old mailbox credential is not authority to keep receiving.
pub async fn drain_once(
    vault: &Vault,
    router_lct: &str,
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
) -> Result<ReceiverDrainReport> {
    let registry = load_members(vault);
    let routes = ReceiverRoutingTable::load(vault)
        .context("loading receiver routing table (unreadable is not empty)")?;
    let client = HubClient::new();

    let mut reports = Vec::new();

    for binding in &routes.local_mailboxes {
        let mut report = ReceiverBindingReport {
            child_lct: binding.child_lct.clone(),
            plugin_id: None,
            binding_id: binding.binding_id,
            fetched: 0,
            accepted_local: 0,
            acked: 0,
            remaining: None,
            errors: Vec::new(),
        };

        let local = match registry.resolve_child_of(router_lct, &binding.child_lct) {
            Ok(LocalChildResolution::Local(m)) => {
                report.plugin_id = Some(m.plugin_id.to_string());
                (m.plugin_id.to_string(), m.lct.lct_id())
            }
            Ok(LocalChildResolution::KnownButNotChild(m)) => {
                report.errors.push(format!(
                    "route-stale: {} is known as '{}' but is not a child of router {}",
                    binding.child_lct, m.plugin_id, router_lct
                ));
                reports.push(report);
                continue;
            }
            Ok(LocalChildResolution::Unknown) => {
                report.errors.push(format!(
                    "route-stale: bound child {} no longer resolves locally",
                    binding.child_lct
                ));
                reports.push(report);
                continue;
            }
            Err(e) => {
                report.errors.push(format!("child resolution failed: {e:#}"));
                reports.push(report);
                continue;
            }
        };
        let (plugin_id, canonical_child_lct) = local;

        // The receiver owns its own hosted-mailbox interface table. Do NOT look
        // this child up in HubStore: HubStore intentionally models the historical
        // one-member-per-Hub CLI connection and rejects duplicate URLs, while a
        // machine router must host N independently-authenticated child identities
        // against the same Hub endpoint.
        let conn = connection_from_binding(binding);

        let (channel, keypair, rest) = match open_verified_channel(&client, vault, &conn).await {
            Ok(v) => v,
            Err(e) => {
                report.errors.push(format!("credential/channel verification: {e:#}"));
                reports.push(report);
                continue;
            }
        };

        // Resume the lost-ACK-response crash edge before fetching new work. The
        // Hub retains ACK tombstones, so an already-landed ACK returns success.
        match inbox.pending_hub_receipt_acks(conn.id) {
            Ok(ids) => {
                for id in ids {
                    match ack_one(&client, &conn, &channel, &keypair, &rest, &id).await {
                        Ok(()) => match inbox.mark_hub_receipt_acked(conn.id, &id) {
                            Ok(()) => report.acked += 1,
                            Err(e) => report.errors.push(format!(
                                "Hub ACK {id} succeeded but local ACK watermark failed: {e:#}"
                            )),
                        },
                        Err(e) => report.errors.push(format!("pending ACK {id}: {e:#}")),
                    }
                }
            }
            Err(e) => report.errors.push(format!("loading pending ACKs: {e:#}")),
        }

        for _page in 0..MAX_FETCH_PAGES {
            let fetched = match client
                .channel_query(
                    &rest,
                    &channel,
                    &keypair,
                    conn.our_lct_id,
                    "notifications_fetch",
                    json!({ "limit": FETCH_LIMIT }),
                )
                .await
            {
                Ok(v) => v,
                Err(e) => {
                    report.errors.push(format!("notifications_fetch: {e:#}"));
                    break;
                }
            };
            if fetched.get("protocol").and_then(|v| v.as_str()) != Some(HUB_RECEIVE_PROTOCOL) {
                report.errors.push("notifications_fetch returned unexpected protocol".into());
                break;
            }
            report.remaining = fetched.get("remaining").and_then(|v| v.as_u64());
            let Some(items) = fetched.get("notifications").and_then(|v| v.as_array()) else {
                report.errors.push("notifications_fetch returned no notifications array".into());
                break;
            };
            if items.is_empty() {
                break;
            }

            let mut batch_failed = false;
            for item in items {
                report.fetched += 1;
                let Some(notice_id) = item.get("id").and_then(|v| v.as_str()) else {
                    report.errors.push("fetched notice missing id".into());
                    batch_failed = true;
                    continue;
                };
                let Some(notice) = item.get("notice") else {
                    report.errors.push(format!("fetched notice {notice_id} missing notice body"));
                    batch_failed = true;
                    continue;
                };
                let kind = value_string(notice, "kind").unwrap_or_else(|| "notify".into());
                let pointer_uri = value_string(notice, "pointer_uri");

                // This slice delivers POINTER-BASED coordination mail into
                // hestia_member_inbox. A member-sealed secret is a different
                // release surface: acknowledging it here would transfer Hub
                // custody into a queue whose consumer cannot open the payload.
                // Leave it on the Hub until the paired/secret consumer is wired.
                let member_sealed = notice
                    .get("sealed_by")
                    .is_some_and(|v| !v.is_null());
                if member_sealed || kind == "secret" {
                    report.errors.push(format!(
                        "notice {notice_id} kind={kind} carries member-sealed/secret payload; \
                         receiver Slice B has no secret-release consumer, so it was NOT acked"
                    ));
                    batch_failed = true;
                    continue;
                }

                let notice_json = match serde_json::to_string(notice) {
                    Ok(v) => v,
                    Err(e) => {
                        report.errors.push(format!("notice {notice_id} serialization: {e}"));
                        batch_failed = true;
                        continue;
                    }
                };

                if let Err(e) = inbox.stage_hub_receipt(
                    conn.id,
                    conn.hub_lct_id,
                    conn.our_lct_id,
                    &canonical_child_lct,
                    &plugin_id,
                    notice_id,
                    &notice_json,
                    &kind,
                    pointer_uri.as_deref(),
                ) {
                    report.errors.push(format!("stage {notice_id}: {e:#}"));
                    batch_failed = true;
                    continue;
                }

                let event_key = format!(
                    "hub-receive:{}:{}:{}",
                    conn.hub_lct_id, conn.our_lct_id, notice_id
                );
                let event = json!({
                    "notice_id": notice_id,
                    "router_lct": router_lct,
                    "destination_lct": canonical_child_lct,
                    "to_plugin": plugin_id,
                    "hub_connection_id": conn.id,
                    "hub_lct": conn.hub_lct_id,
                    "hub_member_lct": conn.our_lct_id,
                    "from": notice.get("from"),
                    "kind": kind,
                    "pointer_uri": pointer_uri,
                    "queued_at": notice.get("queued_at"),
                    "route": "local-direct",
                    "wake": "not-considered",
                    "custody": "member-inbox",
                });
                let witness = match chain.append_once(
                    &event_key,
                    "hub.notice.received",
                    event,
                    router_lct,
                ) {
                    Ok((entry, _inserted)) => entry,
                    Err(e) => {
                        report.errors.push(format!("witness {notice_id}: {e:#}"));
                        batch_failed = true;
                        continue;
                    }
                };

                if let Err(e) = inbox.accept_hub_receipt(conn.id, notice_id, &witness.hash) {
                    report.errors.push(format!("local enqueue {notice_id}: {e:#}"));
                    batch_failed = true;
                    continue;
                }
                report.accepted_local += 1;

                match ack_one(&client, &conn, &channel, &keypair, &rest, notice_id).await {
                    Ok(()) => match inbox.mark_hub_receipt_acked(conn.id, notice_id) {
                        Ok(()) => report.acked += 1,
                        Err(e) => {
                            report.errors.push(format!(
                                "ACK {notice_id} succeeded but local watermark failed: {e:#}"
                            ));
                            batch_failed = true;
                        }
                    },
                    Err(e) => {
                        report.errors.push(format!("ACK {notice_id}: {e:#}"));
                        batch_failed = true;
                    }
                }
            }

            // A failed item remains at the front of receipt-mode fetch. Do not spin
            // on it in one pass; next scheduled/explicit pass retries from durable state.
            if batch_failed || report.remaining == Some(0) {
                break;
            }
        }

        reports.push(report);
    }

    let fetched = reports.iter().map(|r| r.fetched).sum();
    let accepted_local = reports.iter().map(|r| r.accepted_local).sum();
    let acked = reports.iter().map(|r| r.acked).sum();
    let errors = reports.iter().map(|r| r.errors.len()).sum();
    Ok(ReceiverDrainReport {
        router_lct: router_lct.to_string(),
        bindings: reports,
        fetched,
        accepted_local,
        acked,
        errors,
    })
}
