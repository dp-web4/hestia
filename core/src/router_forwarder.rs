//! F3 router transit plane.
//!
//! A router receipt is not ACKed upstream until the packet has crossed one
//! witnessed custody boundary: exact local child, durable next-hop router, or a
//! terminal unreachable outcome. Route decisions and exact outbound bytes are
//! persisted before network I/O, so a crash/retry cannot silently choose a new
//! route because configuration changed.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use crate::hub::{member_signing_keypair, HubChannel, HubClient, HubConnection};
use crate::member_registry::{load_members, MemberRegistry};
use crate::receiver_routing::{
    decide_route, ReceiverRoutingTable, RouteDecision, RoutePacketV1, RouterIngressBinding,
};
use crate::storage::{SqliteChainStore, SqliteInboxStore};
use crate::vault::Vault;

const FETCH_LIMIT: usize = 100;
const MAX_FETCH_PAGES: usize = 20;
const HUB_RECEIVE_PROTOCOL: &str = "hub-mailbox-receive-v1";

#[derive(Debug, Clone, Serialize)]
pub struct RouterIngressReport {
    pub binding_id: Uuid,
    pub hub_member_lct: Uuid,
    pub fetched: usize,
    pub completed: usize,
    pub refused: usize,
    pub acked: usize,
    pub remaining: Option<u64>,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RouterDrainReport {
    pub router_lct: String,
    pub ingresses: Vec<RouterIngressReport>,
    pub fetched: usize,
    pub completed: usize,
    pub refused: usize,
    pub acked: usize,
    pub errors: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "action", rename_all = "snake_case")]
enum PersistedAction {
    Local {
        plugin_id: String,
        child_lct: String,
        from_lct: String,
        kind: String,
        pointer_uri: String,
        source: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        delivery_packet_json: Option<String>,
    },
    Forward {
        next_hop_lct: String,
        via: String,
        link_id: Uuid,
        operation_id: String,
        packet_kind: String,
    },
    Terminal {
        reason: String,
    },
}

fn ingress_connection(binding: &RouterIngressBinding) -> HubConnection {
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

fn sha256_content(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("sha256-content:{}", hex::encode(Sha256::digest(bytes)))
}

async fn open_verified_channel(
    client: &HubClient,
    vault: &Vault,
    conn: &HubConnection,
) -> Result<(HubChannel, web4_core::crypto::KeyPair, String)> {
    let keypair = member_signing_keypair(vault, &conn.member_key_source)
        .with_context(|| format!("resolving credential for Hub member {}", conn.our_lct_id))?;
    let rest = abs_rest(conn);
    let pinned = client
        .resolve_member_pubkey(&rest, conn.hub_lct_id, conn.our_lct_id)
        .await
        .with_context(|| format!("resolving Hub pin for {}", conn.our_lct_id))?;
    anyhow::ensure!(
        pinned.to_hex() == keypair.verifying_key().to_hex(),
        "credential mismatch for Hub member {}",
        conn.our_lct_id
    );
    let channel = client
        .open_channel(&conn.url, Uuid::new_v4())
        .await
        .with_context(|| format!("opening sealed channel to {}", conn.url))?;
    anyhow::ensure!(
        channel.hub_lct_id == conn.hub_lct_id,
        "Hub discovery identity changed: expected {}, got {}",
        conn.hub_lct_id,
        channel.hub_lct_id
    );
    Ok((channel, keypair, rest))
}

async fn ack_one(
    client: &HubClient,
    conn: &HubConnection,
    channel: &HubChannel,
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
            json!({"id": notice_id}),
        )
        .await
        .with_context(|| format!("ACK router Hub notice {notice_id}"))?;
    anyhow::ensure!(
        out.get("protocol").and_then(|v| v.as_str()) == Some(HUB_RECEIVE_PROTOCOL)
            && out.get("acknowledged").and_then(|v| v.as_bool()) == Some(true),
        "Hub did not confirm router receipt ACK"
    );
    Ok(())
}

fn plan_failure(
    packet: &RoutePacketV1,
    reason: String,
    registry: &MemberRegistry,
    routes: &ReceiverRoutingTable,
    router_lct: &str,
) -> Result<(PersistedAction, Option<String>)> {
    if packet.failure.is_some() || packet.original_kind == "unreachable" {
        return Ok((
            PersistedAction::Terminal {
                reason: format!("unreachable-return-path-terminal:{reason}"),
            },
            None,
        ));
    }

    let bounce = packet.unreachable_bounce(router_lct, reason, routes.hop_limit)?;
    match decide_route(
        registry,
        routes,
        router_lct,
        &bounce.destination_lct,
        &bounce.trace(),
    )? {
        RouteDecision::Local {
            plugin_id,
            child_lct,
            ..
        } => Ok((
            PersistedAction::Local {
                plugin_id,
                child_lct,
                from_lct: router_lct.to_string(),
                kind: "unreachable".to_string(),
                pointer_uri: bounce.pointer_uri.clone(),
                source: "unreachable-bounce-local".to_string(),
                delivery_packet_json: Some(serde_json::to_string(&bounce)?),
            },
            None,
        )),
        RouteDecision::Forward {
            next_hop_lct,
            via,
            ..
        } => {
            if bounce.hops_remaining <= 1 {
                return Ok((
                    PersistedAction::Terminal {
                        reason: "unreachable-return-path-hop-limit".to_string(),
                    },
                    None,
                ));
            }
            let Some(neighbor) = routes.neighbor(&next_hop_lct) else {
                return Ok((
                    PersistedAction::Terminal {
                        reason: format!("unreachable-return-path-no-neighbor:{next_hop_lct}"),
                    },
                    None,
                ));
            };
            let outbound = bounce.after_forward(router_lct)?;
            let operation_id = format!("route:{}", outbound.packet_id);
            Ok((
                PersistedAction::Forward {
                    next_hop_lct,
                    via: via.to_string(),
                    link_id: neighbor.link_id,
                    operation_id,
                    packet_kind: "unreachable-bounce".to_string(),
                },
                Some(serde_json::to_string(&outbound)?),
            ))
        }
        RouteDecision::LocalUnavailable { reason, .. } => Ok((
            PersistedAction::Terminal {
                reason: format!("unreachable-return-path-local-unavailable:{reason}"),
            },
            None,
        )),
        RouteDecision::Unreachable { reason, .. } => Ok((
            PersistedAction::Terminal {
                reason: format!("unreachable-return-path:{reason}"),
            },
            None,
        )),
    }
}

fn plan_action(
    packet: &RoutePacketV1,
    registry: &MemberRegistry,
    routes: &ReceiverRoutingTable,
    router_lct: &str,
) -> Result<(PersistedAction, Option<String>)> {
    match decide_route(
        registry,
        routes,
        router_lct,
        &packet.destination_lct,
        &packet.trace(),
    )? {
        RouteDecision::Local {
            plugin_id,
            child_lct,
            ..
        } => Ok((
            PersistedAction::Local {
                plugin_id,
                child_lct,
                from_lct: packet.origin_lct.clone(),
                kind: packet.original_kind.clone(),
                pointer_uri: packet.pointer_uri.clone(),
                source: "routed-data-local".to_string(),
                delivery_packet_json: None,
            },
            None,
        )),
        RouteDecision::Forward {
            next_hop_lct,
            via,
            ..
        } => {
            if packet.hops_remaining <= 1 {
                return plan_failure(
                    packet,
                    "hop-limit-exhausted".to_string(),
                    registry,
                    routes,
                    router_lct,
                );
            }
            let Some(neighbor) = routes.neighbor(&next_hop_lct) else {
                return plan_failure(
                    packet,
                    format!("no-neighbor:{next_hop_lct}"),
                    registry,
                    routes,
                    router_lct,
                );
            };
            let outbound = packet.after_forward(router_lct)?;
            Ok((
                PersistedAction::Forward {
                    next_hop_lct,
                    via: via.to_string(),
                    link_id: neighbor.link_id,
                    operation_id: format!("route:{}", packet.packet_id),
                    packet_kind: "data-forward".to_string(),
                },
                Some(serde_json::to_string(&outbound)?),
            ))
        }
        RouteDecision::LocalUnavailable { reason, .. } => plan_failure(
            packet,
            format!("local-unavailable:{reason}"),
            registry,
            routes,
            router_lct,
        ),
        RouteDecision::Unreachable { reason, .. } => {
            plan_failure(packet, reason, registry, routes, router_lct)
        }
    }
}

async fn execute_action(
    action: &PersistedAction,
    packet: &RoutePacketV1,
    state_outbound: Option<&str>,
    stage_witness_hash: &str,
    upstream_neighbor_lct: &str,
    upstream_hub_member: Uuid,
    vault: &Vault,
    routes: &ReceiverRoutingTable,
    router_lct: &str,
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
    client: &HubClient,
) -> Result<()> {
    match action {
        PersistedAction::Local {
            plugin_id,
            child_lct,
            from_lct,
            kind,
            pointer_uri,
            source,
            delivery_packet_json,
        } => {
            let local_notice_id = inbox.accept_router_packet_local(
                packet.packet_id,
                plugin_id,
                from_lct,
                kind,
                pointer_uri,
                stage_witness_hash,
            )?;
            let key = format!("route-complete:{}", packet.packet_id);
            let event = json!({
                "packet_id": packet.packet_id,
                "router_lct": router_lct,
                "destination_lct": child_lct,
                "to_plugin": plugin_id,
                "member_notice_id": local_notice_id,
                "stage_witness_hash": stage_witness_hash,
                "upstream_neighbor_lct": upstream_neighbor_lct,
                "upstream_hub_member": upstream_hub_member,
                "source": source,
                "delivery_packet_json": delivery_packet_json,
                "wake": "not-considered",
            });
            let (witness, _) = chain.append_once(
                &key,
                "router.packet.delivered-local",
                event,
                router_lct,
            )?;
            inbox.complete_router_packet(
                packet.packet_id,
                "delivered-local",
                &witness.hash,
            )?;
        }
        PersistedAction::Terminal { reason } => {
            let key = format!("route-complete:{}", packet.packet_id);
            let event = json!({
                "packet_id": packet.packet_id,
                "router_lct": router_lct,
                "destination_lct": packet.destination_lct,
                "reason": reason,
                "stage_witness_hash": stage_witness_hash,
                "upstream_neighbor_lct": upstream_neighbor_lct,
                "upstream_hub_member": upstream_hub_member,
                "terminal": true,
            });
            let (witness, _) = chain.append_once(
                &key,
                "router.packet.unreachable-terminal",
                event,
                router_lct,
            )?;
            inbox.complete_router_packet(
                packet.packet_id,
                "unreachable-terminal",
                &witness.hash,
            )?;
        }
        PersistedAction::Forward {
            next_hop_lct,
            via,
            link_id,
            operation_id,
            packet_kind,
        } => {
            let outbound = state_outbound
                .ok_or_else(|| anyhow::anyhow!(
                    "route packet {} lost its persisted outbound bytes",
                    packet.packet_id
                ))?;
            let neighbor = routes.neighbor_by_link(*link_id)
                .ok_or_else(|| anyhow::anyhow!(
                    "route packet {} is pinned to missing neighbor link {}",
                    packet.packet_id, link_id
                ))?;
            anyhow::ensure!(
                neighbor.next_hop_lct == *next_hop_lct,
                "neighbor link {} now names {}, expected {}",
                link_id,
                neighbor.next_hop_lct,
                next_hop_lct
            );
            let interface = routes
                .router_ingress_by_id(neighbor.interface_binding_id)
                .ok_or_else(|| anyhow::anyhow!(
                    "neighbor link {} references missing router interface {}",
                    link_id, neighbor.interface_binding_id
                ))?;
            anyhow::ensure!(
                interface.router_lct == router_lct,
                "neighbor link {} uses interface {} belonging to router {}, not {}",
                link_id, interface.binding_id, interface.router_lct, router_lct
            );
            let conn = ingress_connection(interface);
            let (channel, keypair, rest) = open_verified_channel(client, vault, &conn).await?;
            let out = client
                .channel_query(
                    &rest,
                    &channel,
                    &keypair,
                    conn.our_lct_id,
                    "route_forward",
                    json!({
                        "to": neighbor.next_hop_hub_member_lct,
                        "operation_id": operation_id,
                        "route_packet_json": outbound,
                    }),
                )
                .await
                .with_context(|| format!(
                    "forwarding route packet {} to {}",
                    packet.packet_id, next_hop_lct
                ))?;
            anyhow::ensure!(
                out.get("delivered").and_then(|v| v.as_bool()) == Some(true)
                    && out.get("durably_accepted").and_then(|v| v.as_bool()) == Some(true),
                "next-hop Hub did not return durable route acceptance"
            );
            let notice_id = out.get("notice_id").and_then(|v| v.as_str())
                .ok_or_else(|| anyhow::anyhow!("route_forward receipt has no notice_id"))?;
            let entry_index = out.get("entry_index").and_then(|v| v.as_u64())
                .ok_or_else(|| anyhow::anyhow!("route_forward receipt has no entry_index"))?;
            inbox.record_router_downstream_receipt(
                packet.packet_id,
                notice_id,
                entry_index,
            )?;

            let key = format!("route-complete:{}", packet.packet_id);
            let event = json!({
                "packet_id": packet.packet_id,
                "router_lct": router_lct,
                "destination_lct": packet.destination_lct,
                "next_hop_lct": next_hop_lct,
                "via": via,
                "link_id": link_id,
                "operation_id": operation_id,
                "downstream_notice_id": notice_id,
                "downstream_entry_index": entry_index,
                "outbound_packet_hash": sha256_content(outbound.as_bytes()),
                "packet_kind": packet_kind,
                "stage_witness_hash": stage_witness_hash,
                "upstream_neighbor_lct": upstream_neighbor_lct,
                "upstream_hub_member": upstream_hub_member,
            });
            let event_type = if packet_kind == "unreachable-bounce" {
                "router.packet.unreachable-bounced"
            } else {
                "router.packet.forwarded"
            };
            let (witness, _) = chain.append_once(&key, event_type, event, router_lct)?;
            inbox.complete_router_packet(packet.packet_id, packet_kind, &witness.hash)?;
        }
    }
    Ok(())
}

fn parse_route_notice(
    notice: &serde_json::Value,
    channel: &HubChannel,
    keypair: &web4_core::crypto::KeyPair,
) -> Result<(RoutePacketV1, String, String)> {
    anyhow::ensure!(
        notice.get("kind").and_then(|v| v.as_str()) == Some("route.forward"),
        "router ingress accepts only kind=route.forward"
    );
    anyhow::ensure!(
        notice.get("sealed_by").is_none() || notice.get("sealed_by").is_some_and(|v| v.is_null()),
        "route.forward must be Hub-sealed, not member-pre-sealed"
    );
    let pair_id = notice.get("pair_id").and_then(|v| v.as_str())
        .and_then(|v| Uuid::parse_str(v).ok())
        .ok_or_else(|| anyhow::anyhow!("route.forward notice has no valid pair_id"))?;
    let sealed = notice.get("sealed").and_then(|v| v.as_str())
        .ok_or_else(|| anyhow::anyhow!("route.forward notice has no sealed body"))?;

    let mut notification_channel = channel.clone();
    notification_channel.pair_id = pair_id;
    let body = notification_channel
        .open_notification(keypair, sealed)
        .context("opening Hub-sealed route.forward body")?;
    anyhow::ensure!(
        body.get("kind").and_then(|v| v.as_str()) == Some("route.forward"),
        "opened route body has the wrong kind"
    );
    let packet_json = body.get("route_packet_json").and_then(|v| v.as_str())
        .ok_or_else(|| anyhow::anyhow!("opened route body has no route_packet_json"))?
        .to_string();
    let packet_hash = sha256_content(packet_json.as_bytes());
    anyhow::ensure!(
        body.get("content_hash").and_then(|v| v.as_str()) == Some(packet_hash.as_str()),
        "route packet bytes do not match the Hub-witnessed content hash"
    );
    let packet_value: serde_json::Value = serde_json::from_str(&packet_json)
        .context("parsing route packet JSON")?;
    let packet: RoutePacketV1 = serde_json::from_value(packet_value)
        .context("decoding route packet fields")?;
    packet.validate()?;
    let expected_pointer = format!("web4-route:{}", packet.packet_id);
    anyhow::ensure!(
        body.get("pointer_uri").and_then(|v| v.as_str()) == Some(expected_pointer.as_str())
            && notice.get("pointer_uri").and_then(|v| v.as_str()) == Some(expected_pointer.as_str()),
        "route packet pointer does not match packet_id"
    );
    anyhow::ensure!(
        body.get("from") == notice.get("from"),
        "route body sender differs from clear Hub envelope sender"
    );
    Ok((packet, packet_json, packet_hash))
}

async fn refuse_ingress_receipt(
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
    client: &HubClient,
    conn: &HubConnection,
    channel: &HubChannel,
    keypair: &web4_core::crypto::KeyPair,
    rest: &str,
    binding: &RouterIngressBinding,
    router_lct: &str,
    notice_id: &str,
    notice_json: &str,
    packet: &RoutePacketV1,
    packet_hash: &str,
    upstream_member: Uuid,
    configured_neighbor_lct: Option<&str>,
    reason: &str,
) -> Result<()> {
    let key = format!(
        "route-ingress-refusal:{}:{}",
        binding.binding_id, notice_id
    );
    let (witness, _) = chain.append_once(
        &key,
        "router.packet.ingress-refused",
        json!({
            "packet_id": packet.packet_id,
            "packet_hash": packet_hash,
            "notice_hash": sha256_content(notice_json.as_bytes()),
            "router_lct": router_lct,
            "ingress_binding_id": binding.binding_id,
            "hub_notice_id": notice_id,
            "from_hub_member": upstream_member,
            "configured_neighbor_lct": configured_neighbor_lct,
            "claimed_previous_router": packet.visited_routers.last(),
            "destination_lct": packet.destination_lct,
            "reason": reason,
        }),
        router_lct,
    )?;
    inbox.record_router_ingress_rejection(
        binding.binding_id,
        notice_id,
        notice_json,
        Some(packet.packet_id),
        &witness.hash,
    )?;
    ack_one(client, conn, channel, keypair, rest, notice_id).await?;
    inbox.mark_router_rejection_acked(binding.binding_id, notice_id)?;
    Ok(())
}

pub async fn drain_router_once(
    vault: &Vault,
    router_lct: &str,
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
) -> Result<RouterDrainReport> {
    let registry = load_members(vault);
    let routes = ReceiverRoutingTable::load(vault)
        .context("loading receiver routing table (unreadable is not empty)")?;
    let client = HubClient::new();
    let mut reports = Vec::new();

    for binding in routes.router_ingress.iter().filter(|b| b.router_lct == router_lct) {
        let mut report = RouterIngressReport {
            binding_id: binding.binding_id,
            hub_member_lct: binding.hub_member_lct,
            fetched: 0,
            completed: 0,
            refused: 0,
            acked: 0,
            remaining: None,
            errors: Vec::new(),
        };
        let conn = ingress_connection(binding);
        let (channel, keypair, rest) = match open_verified_channel(&client, vault, &conn).await {
            Ok(v) => v,
            Err(e) => {
                report.errors.push(format!("ingress credential/channel: {e:#}"));
                reports.push(report);
                continue;
            }
        };

        match inbox.pending_router_ingress_acks(binding.binding_id) {
            Ok(ids) => {
                for id in ids {
                    match ack_one(&client, &conn, &channel, &keypair, &rest, &id).await {
                        Ok(()) => match inbox.mark_router_ingress_acked(binding.binding_id, &id) {
                            Ok(()) => report.acked += 1,
                            Err(e) => report.errors.push(format!(
                                "router ACK {id} landed but local watermark failed: {e:#}"
                            )),
                        },
                        Err(e) => report.errors.push(format!("pending router ACK {id}: {e:#}")),
                    }
                }
            }
            Err(e) => report.errors.push(format!("loading pending router ACKs: {e:#}")),
        }

        match inbox.pending_router_rejection_acks(binding.binding_id) {
            Ok(ids) => {
                for id in ids {
                    match ack_one(&client, &conn, &channel, &keypair, &rest, &id).await {
                        Ok(()) => match inbox.mark_router_rejection_acked(binding.binding_id, &id) {
                            Ok(()) => report.acked += 1,
                            Err(e) => report.errors.push(format!(
                                "rejection ACK {id} landed but local watermark failed: {e:#}"
                            )),
                        },
                        Err(e) => report.errors.push(format!(
                            "pending rejection ACK {id}: {e:#}"
                        )),
                    }
                }
            }
            Err(e) => report.errors.push(format!(
                "loading pending router rejection ACKs: {e:#}"
            )),
        }

        for _ in 0..MAX_FETCH_PAGES {
            let fetched = match client.channel_query(
                &rest,
                &channel,
                &keypair,
                conn.our_lct_id,
                "notifications_fetch",
                json!({"limit": FETCH_LIMIT}),
            ).await {
                Ok(v) => v,
                Err(e) => {
                    report.errors.push(format!("router notifications_fetch: {e:#}"));
                    break;
                }
            };
            if fetched.get("protocol").and_then(|v| v.as_str()) != Some(HUB_RECEIVE_PROTOCOL) {
                report.errors.push("router fetch returned unexpected protocol".to_string());
                break;
            }
            report.remaining = fetched.get("remaining").and_then(|v| v.as_u64());
            let Some(items) = fetched.get("notifications").and_then(|v| v.as_array()) else {
                report.errors.push("router fetch returned no notifications array".to_string());
                break;
            };
            if items.is_empty() {
                break;
            }

            let mut batch_failed = false;
            for item in items {
                report.fetched += 1;
                let Some(notice_id) = item.get("id").and_then(|v| v.as_str()) else {
                    report.errors.push("router fetched notice missing id".to_string());
                    batch_failed = true;
                    continue;
                };
                let Some(notice) = item.get("notice") else {
                    report.errors.push(format!("router notice {notice_id} missing body"));
                    batch_failed = true;
                    continue;
                };
                let notice_json = match serde_json::to_string(notice) {
                    Ok(v) => v,
                    Err(e) => {
                        report.errors.push(format!("router notice {notice_id} serialization: {e}"));
                        batch_failed = true;
                        continue;
                    }
                };
                let (packet, packet_json, packet_hash) =
                    match parse_route_notice(notice, &channel, &keypair) {
                        Ok(v) => v,
                        Err(e) => {
                            report.errors.push(format!("route notice {notice_id}: {e:#}"));
                            batch_failed = true;
                            continue;
                        }
                    };

                let upstream_member = match notice
                    .get("from")
                    .and_then(|v| v.as_str())
                    .and_then(|v| Uuid::parse_str(v).ok())
                {
                    Some(v) => v,
                    None => {
                        report.errors.push(format!(
                            "route notice {notice_id} has no valid authenticated Hub sender"
                        ));
                        batch_failed = true;
                        continue;
                    }
                };

                // Authorize the immediate hop BEFORE claiming packet_id globally.
                // Otherwise an unconfigured Hub citizen could send a validly sealed
                // packet with a guessed packet_id and different bytes, get refused,
                // yet poison the idempotency namespace for the legitimate neighbor.
                let ingress_auth = match routes.ingress_neighbor(
                    binding.binding_id,
                    upstream_member,
                ) {
                    Ok(Some(n))
                        if packet.visited_routers.last().map(String::as_str)
                            == Some(n.next_hop_lct.as_str()) =>
                    {
                        Ok(n)
                    }
                    Ok(Some(n)) => Err((
                        format!(
                            "trace-neighbor-mismatch: authenticated Hub sender {} maps to {}, packet names previous router {:?}",
                            upstream_member,
                            n.next_hop_lct,
                            packet.visited_routers.last()
                        ),
                        Some(n.next_hop_lct.as_str()),
                    )),
                    Ok(None) => Err((
                        format!(
                            "unconfigured-neighbor: Hub member {} is not a neighbor on interface {}",
                            upstream_member, binding.binding_id
                        ),
                        None,
                    )),
                    Err(e) => {
                        report.errors.push(format!(
                            "route notice {notice_id} neighbor resolution: {e:#}"
                        ));
                        batch_failed = true;
                        continue;
                    }
                };

                let upstream_neighbor = match ingress_auth {
                    Ok(n) => n,
                    Err((reason, configured_neighbor_lct)) => {
                        match refuse_ingress_receipt(
                            inbox,
                            chain,
                            &client,
                            &conn,
                            &channel,
                            &keypair,
                            &rest,
                            binding,
                            router_lct,
                            notice_id,
                            &notice_json,
                            &packet,
                            &packet_hash,
                            upstream_member,
                            configured_neighbor_lct,
                            &reason,
                        ).await {
                            Ok(()) => {
                                report.refused += 1;
                                report.acked += 1;
                            }
                            Err(e) => {
                                report.errors.push(format!(
                                    "refuse route ingress {notice_id}: {e:#}"
                                ));
                                batch_failed = true;
                            }
                        }
                        continue;
                    }
                };

                // A packet id is immutable once THIS router has accepted it.
                // A later authorized arrival with different hop/trace bytes may
                // be an alternate-path duplicate or a hostile replay; either way
                // it is a per-receipt refusal, not a reason to wedge the mailbox.
                match inbox.router_packet_state(packet.packet_id) {
                    Ok(Some(existing))
                        if existing.packet_json != packet_json
                            || existing.packet_hash != packet_hash =>
                    {
                        let reason = format!(
                            "packet-id-conflict: {} already names different bytes at this router",
                            packet.packet_id
                        );
                        match refuse_ingress_receipt(
                            inbox,
                            chain,
                            &client,
                            &conn,
                            &channel,
                            &keypair,
                            &rest,
                            binding,
                            router_lct,
                            notice_id,
                            &notice_json,
                            &packet,
                            &packet_hash,
                            upstream_member,
                            Some(upstream_neighbor.next_hop_lct.as_str()),
                            &reason,
                        ).await {
                            Ok(()) => {
                                report.refused += 1;
                                report.acked += 1;
                            }
                            Err(e) => {
                                report.errors.push(format!(
                                    "refuse packet-id conflict {notice_id}: {e:#}"
                                ));
                                batch_failed = true;
                            }
                        }
                        continue;
                    }
                    Ok(_) => {}
                    Err(e) => {
                        report.errors.push(format!(
                            "load packet {} before stage: {e:#}",
                            packet.packet_id
                        ));
                        batch_failed = true;
                        continue;
                    }
                }

                let mut state = match inbox.stage_router_packet(
                    binding.binding_id,
                    notice_id,
                    packet.packet_id,
                    &notice_json,
                    &packet_json,
                    &packet_hash,
                ) {
                    Ok(v) => v,
                    Err(e) => {
                        report.errors.push(format!("stage packet {}: {e:#}", packet.packet_id));
                        batch_failed = true;
                        continue;
                    }
                };

                let stage_key = format!(
                    "route-ingress:{}:{}",
                    binding.binding_id, notice_id
                );
                let stage_event = json!({
                    "packet_id": packet.packet_id,
                    "packet_hash": packet_hash,
                    "router_lct": router_lct,
                    "ingress_binding_id": binding.binding_id,
                    "hub_notice_id": notice_id,
                    "hub_lct": binding.hub_lct_id,
                    "hub_member_lct": binding.hub_member_lct,
                    "from_hub_member": upstream_member,
                    "upstream_neighbor_lct": upstream_neighbor.next_hop_lct,
                    "upstream_link_id": upstream_neighbor.link_id,
                    "destination_lct": packet.destination_lct,
                    "origin_lct": packet.origin_lct,
                    "hops_remaining": packet.hops_remaining,
                    "visited_routers": packet.visited_routers,
                    "custody": "router-staged",
                });
                let stage_witness = match chain.append_once(
                    &stage_key,
                    "router.packet.receipt-staged",
                    stage_event,
                    router_lct,
                ) {
                    Ok((entry, _)) => entry,
                    Err(e) => {
                        report.errors.push(format!("route stage witness: {e:#}"));
                        batch_failed = true;
                        continue;
                    }
                };
                if let Err(e) = inbox.record_router_stage_witness(
                    binding.binding_id,
                    notice_id,
                    packet.packet_id,
                    &stage_witness.hash,
                ) {
                    report.errors.push(format!("record route stage witness: {e:#}"));
                    batch_failed = true;
                    continue;
                }

                if state.completion_witness_hash.is_none() {
                    let action: PersistedAction = if let Some(decision) = &state.decision_json {
                        match serde_json::from_str(decision) {
                            Ok(v) => v,
                            Err(e) => {
                                report.errors.push(format!(
                                    "persisted route decision for {} is unreadable: {e}",
                                    packet.packet_id
                                ));
                                batch_failed = true;
                                continue;
                            }
                        }
                    } else {
                        let (action, outbound) = match plan_action(
                            &packet,
                            &registry,
                            &routes,
                            router_lct,
                        ) {
                            Ok(v) => v,
                            Err(e) => {
                                report.errors.push(format!(
                                    "route planning for {}: {e:#}",
                                    packet.packet_id
                                ));
                                batch_failed = true;
                                continue;
                            }
                        };
                        let decision_json = serde_json::to_string(&action)?;
                        let persist = match &action {
                            PersistedAction::Forward {
                                next_hop_lct,
                                link_id,
                                operation_id,
                                ..
                            } => inbox.record_router_forward_decision(
                                packet.packet_id,
                                &decision_json,
                                outbound.as_deref().expect("forward plan carries packet"),
                                next_hop_lct,
                                *link_id,
                                operation_id,
                            ),
                            PersistedAction::Local { child_lct, .. } => {
                                inbox.record_router_local_decision(
                                    packet.packet_id,
                                    &decision_json,
                                    Some(child_lct),
                                )
                            }
                            PersistedAction::Terminal { .. } => {
                                inbox.record_router_local_decision(
                                    packet.packet_id,
                                    &decision_json,
                                    None,
                                )
                            }
                        };
                        if let Err(e) = persist {
                            report.errors.push(format!(
                                "persist route decision for {}: {e:#}",
                                packet.packet_id
                            ));
                            batch_failed = true;
                            continue;
                        }
                        action
                    };

                    state = match inbox.router_packet_state(packet.packet_id) {
                        Ok(Some(v)) => v,
                        Ok(None) => {
                            report.errors.push(format!(
                                "route packet {} disappeared after decision",
                                packet.packet_id
                            ));
                            batch_failed = true;
                            continue;
                        }
                        Err(e) => {
                            report.errors.push(format!("reload route packet state: {e:#}"));
                            batch_failed = true;
                            continue;
                        }
                    };

                    if let Err(e) = execute_action(
                        &action,
                        &packet,
                        state.outbound_packet_json.as_deref(),
                        &stage_witness.hash,
                        &upstream_neighbor.next_hop_lct,
                        upstream_member,
                        vault,
                        &routes,
                        router_lct,
                        inbox,
                        chain,
                        &client,
                    ).await {
                        report.errors.push(format!(
                            "execute route packet {}: {e:#}",
                            packet.packet_id
                        ));
                        batch_failed = true;
                        continue;
                    }
                    report.completed += 1;
                }

                match ack_one(&client, &conn, &channel, &keypair, &rest, notice_id).await {
                    Ok(()) => match inbox.mark_router_ingress_acked(binding.binding_id, notice_id) {
                        Ok(()) => report.acked += 1,
                        Err(e) => {
                            report.errors.push(format!(
                                "route ACK {notice_id} landed but local watermark failed: {e:#}"
                            ));
                            batch_failed = true;
                        }
                    },
                    Err(e) => {
                        report.errors.push(format!("route ACK {notice_id}: {e:#}"));
                        batch_failed = true;
                    }
                }
            }

            if batch_failed || report.remaining == Some(0) {
                break;
            }
        }
        reports.push(report);
    }

    let fetched = reports.iter().map(|r| r.fetched).sum();
    let completed = reports.iter().map(|r| r.completed).sum();
    let refused = reports.iter().map(|r| r.refused).sum();
    let acked = reports.iter().map(|r| r.acked).sum();
    let errors = reports.iter().map(|r| r.errors.len()).sum();
    Ok(RouterDrainReport {
        router_lct: router_lct.to_string(),
        ingresses: reports,
        fetched,
        completed,
        refused,
        acked,
        errors,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_route_becomes_a_bounded_unreachable_packet_when_return_path_exists() {
        let dir = tempfile::tempdir().unwrap();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let router = "lct:web4:mb32:router";
        let mut registry = load_members(&vault);
        let origin = crate::member_registry::ensure_member(
            &mut vault,
            &mut registry,
            "origin-being",
            false,
            router,
            "anchor",
        ).unwrap();
        let mut routes = ReceiverRoutingTable::default();
        routes.bind_local(crate::receiver_routing::LocalMailboxBinding {
            binding_id: Uuid::new_v4(),
            child_lct: origin.clone(),
            hub_url: "https://hub.test".to_string(),
            hub_lct_id: Uuid::new_v4(),
            rest_endpoint: "https://hub.test/v1".to_string(),
            hub_member_lct: Uuid::new_v4(),
            member_key_source: crate::hub::MemberKeySource::ChannelKeyFile {
                path: "/tmp/none".to_string(),
            },
            reason: "test".to_string(),
            set_by: "test".to_string(),
            set_at: 1,
        }).unwrap();

        let packet = RoutePacketV1 {
            protocol: RoutePacketV1::PROTOCOL.to_string(),
            packet_id: Uuid::new_v4(),
            destination_lct: "lct:web4:mb32:missing".to_string(),
            origin_lct: origin,
            original_kind: "coordination".to_string(),
            pointer_uri: "shared-context/x".to_string(),
            content_hash: format!("sha256-pointer:{}", "a".repeat(64)),
            hops_remaining: 8,
            visited_routers: vec![],
            failure: None,
        };
        let (action, outbound) = plan_action(
            &packet, &registry, &routes, router
        ).unwrap();
        assert!(outbound.is_none(), "a local bounce needs no network packet");
        assert!(matches!(
            action,
            PersistedAction::Local {
                kind, source, delivery_packet_json: Some(_), ..
            } if kind == "unreachable" && source == "unreachable-bounce-local"
        ));
    }

    #[test]
    fn unreachable_packet_never_recursively_bounces() {
        let registry = MemberRegistry::default();
        let routes = ReceiverRoutingTable::default();
        let packet = RoutePacketV1 {
            protocol: RoutePacketV1::PROTOCOL.to_string(),
            packet_id: Uuid::new_v4(),
            destination_lct: "lct:web4:mb32:missing".to_string(),
            origin_lct: "lct:web4:mb32:also-missing".to_string(),
            original_kind: "unreachable".to_string(),
            pointer_uri: "hestia://route-error/x".to_string(),
            content_hash: format!("sha256-pointer:{}", "b".repeat(64)),
            hops_remaining: 4,
            visited_routers: vec![],
            failure: Some(crate::receiver_routing::RouteFailure {
                original_packet_id: Uuid::new_v4(),
                failed_destination_lct: "lct:web4:mb32:x".to_string(),
                failed_at_router_lct: "lct:web4:mb32:r".to_string(),
                reason: "no-route".to_string(),
            }),
        };
        let (action, outbound) = plan_action(
            &packet, &registry, &routes, "router"
        ).unwrap();
        assert!(outbound.is_none());
        assert!(matches!(action, PersistedAction::Terminal { .. }));
    }
}
