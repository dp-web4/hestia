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
use crate::member_registry::{load_members, LocalChildResolution, MemberRegistry};
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

#[derive(Debug, Clone, Serialize)]
pub struct RouteOriginReport {
    pub operation_id: String,
    pub packet_id: Uuid,
    pub replayed: bool,
    pub completed: bool,
    /// Semantic outcome, deliberately stronger than the internal completion
    /// watermark. "delivered-local" alone is ambiguous because it can describe
    /// either DATA delivered to its destination or an UNREACHABLE bounce
    /// delivered back to the origin.
    pub outcome: String,
    pub completion_kind: Option<String>,
    pub completion_witness_hash: Option<String>,
    pub decision_json: Option<String>,
}

#[derive(Serialize)]
struct RouteOriginBinding<'a> {
    protocol: &'static str,
    origin_lct: &'a str,
    destination_lct: &'a str,
    original_kind: &'a str,
    pointer_uri: &'a str,
    content_hash: &'a str,
    /// D2 compatibility constraint. Omitted for native F3 callers so the
    /// serialized binding remains byte-compatible with pre-D2 D1 operations.
    #[serde(skip_serializing_if = "Option::is_none")]
    expected_first_hop_hub_member: Option<&'a str>,
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

const ROUTED_MEMBER_NOTICE_ROOTS: &[&str] = &[
    "coordination",
    "review_request",
    "review_done",
    "reply",
    "handoff",
    "forum-note",
    "ack",
];

fn routable_member_notice_kind(kind: &str) -> bool {
    if kind.is_empty() || kind.len() > 64 {
        return false;
    }
    let Some(root) = ROUTED_MEMBER_NOTICE_ROOTS
        .iter()
        .find(|root| kind == **root || kind.starts_with(&format!("{root}.")))
    else {
        return false;
    };
    if kind.len() == root.len() {
        return true;
    }
    kind[root.len() + 1..].split('.').all(|segment| {
        !segment.is_empty()
            && segment.bytes().all(|b| {
                b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-'
            })
    })
}

fn routable_member_pointer(pointer: &str) -> bool {
    !pointer.is_empty()
        && pointer.len() <= 512
        && !pointer.chars().any(char::is_control)
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
        } => {
            let unreachable =
                packet.failure.is_some() || packet.original_kind == "unreachable";
            if !unreachable && !routable_member_notice_kind(&packet.original_kind) {
                return plan_failure(
                    packet,
                    format!("local-kind-refused:{}", packet.original_kind),
                    registry,
                    routes,
                    router_lct,
                );
            }
            if !unreachable && !routable_member_pointer(&packet.pointer_uri) {
                return plan_failure(
                    packet,
                    "local-pointer-refused".to_string(),
                    registry,
                    routes,
                    router_lct,
                );
            }
            Ok((
                PersistedAction::Local {
                    plugin_id,
                    child_lct,
                    from_lct: packet.origin_lct.clone(),
                    kind: packet.original_kind.clone(),
                    pointer_uri: packet.pointer_uri.clone(),
                    source: if unreachable {
                        "unreachable-routed-local".to_string()
                    } else {
                        "routed-data-local".to_string()
                    },
                    delivery_packet_json: if unreachable {
                        Some(serde_json::to_string(packet)?)
                    } else {
                        None
                    },
                },
                None,
            ))
        },
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

fn verify_neighbor_certificate_live(
    neighbor: &crate::receiver_routing::RouterNeighbor,
    interface: &RouterIngressBinding,
    live_peer_key: &web4_core::crypto::PublicKey,
) -> Result<String> {
    let cert = neighbor.peer_certificate.as_ref().ok_or_else(|| anyhow::anyhow!(
        "neighbor {} has no router-interface certificate",
        neighbor.next_hop_lct
    ))?;
    cert.verify()
        .context("verifying neighbor router-interface certificate")?;
    anyhow::ensure!(
        cert.payload.router_lct == neighbor.next_hop_lct,
        "neighbor certificate router {} differs from configured {}",
        cert.payload.router_lct,
        neighbor.next_hop_lct
    );
    anyhow::ensure!(
        cert.payload.hub_member_lct == neighbor.next_hop_hub_member_lct,
        "neighbor certificate Hub member {} differs from configured {}",
        cert.payload.hub_member_lct,
        neighbor.next_hop_hub_member_lct
    );
    anyhow::ensure!(
        cert.payload.hub_lct_id == interface.hub_lct_id,
        "neighbor certificate Hub {} differs from egress interface Hub {}",
        cert.payload.hub_lct_id,
        interface.hub_lct_id
    );
    anyhow::ensure!(
        live_peer_key.to_hex() == cert.payload.hub_member_pubkey_hex,
        "neighbor {} certificate key no longer matches live Hub pin for {}",
        neighbor.next_hop_lct,
        neighbor.next_hop_hub_member_lct
    );
    cert.fingerprint()
}

async fn execute_action(
    action: &PersistedAction,
    packet: &RoutePacketV1,
    state_outbound: Option<&str>,
    stage_witness_hash: &str,
    upstream_neighbor_lct: Option<&str>,
    upstream_hub_member: Option<Uuid>,
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
            // A routed unreachable is itself the payload the local recipient
            // must inspect. The synthetic hestia://route-error/... locator in
            // the packet is a routing label, not a readable resource. Materialize
            // a chain-addressable evidence record BEFORE enqueue so every local
            // unreachable notice points at something the existing resource
            // resolver can actually dereference.
            let mut delivered_pointer = pointer_uri.clone();
            let mut delivery_chain_hash = stage_witness_hash.to_string();
            let mut failure_evidence_hash: Option<String> = None;
            if let Some(packet_json) = delivery_packet_json {
                let evidence_key = format!("route-unreachable-evidence:{}", packet.packet_id);
                let (evidence, _) = chain.append_once(
                    &evidence_key,
                    "router.packet.unreachable-evidence",
                    json!({
                        "packet_id": packet.packet_id,
                        "router_lct": router_lct,
                        "destination_lct": child_lct,
                        "to_plugin": plugin_id,
                        "source": source,
                        "route_packet_json": packet_json,
                        "ingress_stage_witness_hash": stage_witness_hash,
                        "upstream_neighbor_lct": upstream_neighbor_lct,
                        "upstream_hub_member": upstream_hub_member,
                    }),
                    router_lct,
                )?;
                delivered_pointer = format!("hestia://chain/{}", evidence.hash);
                delivery_chain_hash = evidence.hash.clone();
                failure_evidence_hash = Some(evidence.hash);
            }

            let local_notice_id = inbox.accept_router_packet_local(
                packet.packet_id,
                plugin_id,
                from_lct,
                kind,
                &delivered_pointer,
                &delivery_chain_hash,
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
                "original_pointer_uri": pointer_uri,
                "delivered_pointer_uri": delivered_pointer,
                "failure_evidence_hash": failure_evidence_hash,
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
            let live_peer_key = client
                .resolve_member_pubkey(
                    &rest,
                    interface.hub_lct_id,
                    neighbor.next_hop_hub_member_lct,
                )
                .await
                .with_context(|| format!(
                    "re-resolving live Hub pin for next-hop router {} ({})",
                    next_hop_lct, neighbor.next_hop_hub_member_lct
                ))?;
            let neighbor_certificate_fingerprint =
                verify_neighbor_certificate_live(neighbor, interface, &live_peer_key)?;
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
                "neighbor_certificate_fingerprint": neighbor_certificate_fingerprint,
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

fn valid_origin_operation_id(operation_id: &str) -> bool {
    !operation_id.is_empty()
        && operation_id.len() <= 128
        && !operation_id.chars().any(char::is_control)
}

fn persisted_action(
    packet: &RoutePacketV1,
    state: &crate::storage::RouterPacketState,
) -> Result<PersistedAction> {
    let decision = state
        .decision_json
        .as_deref()
        .ok_or_else(|| anyhow::anyhow!(
            "route packet {} has no persisted decision", packet.packet_id
        ))?;
    serde_json::from_str(decision)
        .with_context(|| format!(
            "decoding persisted route decision for {}", packet.packet_id
        ))
}

/// Originate one Web4 route packet from a canonical local child.
///
/// operation_id is a caller-stable retry key scoped by origin_lct. The first
/// call atomically binds it to one random packet UUID and immutable send intent.
/// A lost caller response can therefore retry without minting a second packet;
/// reusing the key for different destination/content is refused.
#[allow(clippy::too_many_arguments)]
pub async fn originate_once(
    vault: &Vault,
    router_lct: &str,
    origin_lct: &str,
    destination_lct: &str,
    original_kind: &str,
    pointer_uri: &str,
    content_hash: &str,
    operation_id: &str,
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
) -> Result<RouteOriginReport> {
    originate_once_constrained(
        vault,
        router_lct,
        origin_lct,
        destination_lct,
        original_kind,
        pointer_uri,
        content_hash,
        operation_id,
        inbox,
        chain,
        None,
    )
    .await
}

/// D2 compatibility entrypoint. When an old transport binding promised a
/// particular Hub carrier, the actual persisted first-hop route must use that
/// same Hub member. The constraint is part of the operation binding, so retry
/// cannot silently weaken/change it.
#[allow(clippy::too_many_arguments)]
pub async fn originate_once_constrained(
    vault: &Vault,
    router_lct: &str,
    origin_lct: &str,
    destination_lct: &str,
    original_kind: &str,
    pointer_uri: &str,
    content_hash: &str,
    operation_id: &str,
    inbox: &SqliteInboxStore,
    chain: &SqliteChainStore,
    expected_first_hop_hub_member: Option<&str>,
) -> Result<RouteOriginReport> {
    anyhow::ensure!(
        valid_origin_operation_id(operation_id),
        "route origin operation_id must be 1..128 bytes with no control characters"
    );
    anyhow::ensure!(
        destination_lct.starts_with("lct:web4:mb32:"),
        "route destination must be a canonical lct:web4:mb32:* identity"
    );
    anyhow::ensure!(
        routable_member_notice_kind(original_kind),
        "route origin kind '{original_kind}' is not a Hestia member-notice kind"
    );
    anyhow::ensure!(
        routable_member_pointer(pointer_uri),
        "route origin pointer_uri must be a non-empty single-line pointer <=512 bytes"
    );

    let registry = load_members(vault);
    match registry.resolve_child_of(router_lct, origin_lct)? {
        LocalChildResolution::Local(member) => {
            anyhow::ensure!(
                member.lct.lct_id() == origin_lct
                    && origin_lct.starts_with("lct:web4:mb32:"),
                "route origin must be the canonical LCT of a child of router {router_lct}"
            );
        }
        LocalChildResolution::KnownButNotChild(member) => anyhow::bail!(
            "route origin {} ({}) is known but is not a child of router {}",
            member.plugin_id, member.lct.lct_id(), router_lct
        ),
        LocalChildResolution::Unknown => anyhow::bail!(
            "route origin {origin_lct} is not a registered local child of router {router_lct}"
        ),
    }

    let routes = ReceiverRoutingTable::load(vault)
        .context("loading receiver routing table (unreadable is not empty)")?;

    let binding_json = serde_json::to_string(&RouteOriginBinding {
        protocol: "hestia-route-origin-v1",
        origin_lct,
        destination_lct,
        original_kind,
        pointer_uri,
        content_hash,
        expected_first_hop_hub_member,
    })?;

    let candidate = RoutePacketV1 {
        protocol: RoutePacketV1::PROTOCOL.to_string(),
        packet_id: Uuid::new_v4(),
        destination_lct: destination_lct.to_string(),
        origin_lct: origin_lct.to_string(),
        original_kind: original_kind.to_string(),
        pointer_uri: pointer_uri.to_string(),
        content_hash: content_hash.to_string(),
        hops_remaining: routes.hop_limit,
        visited_routers: Vec::new(),
        failure: None,
    };
    candidate.validate()?;
    let candidate_json = serde_json::to_string(&candidate)?;
    let candidate_hash = sha256_content(candidate_json.as_bytes());

    let (mut state, inserted) = inbox.stage_router_origin(
        origin_lct,
        operation_id,
        &binding_json,
        candidate.packet_id,
        &candidate_json,
        &candidate_hash,
    )?;

    // On a retry the FIRST packet wins, including its original hop limit. Never
    // reconstruct an already-originated packet from today's routing config.
    let packet: RoutePacketV1 = serde_json::from_str(&state.packet_json)
        .context("decoding originated route packet from custody")?;
    packet.validate()?;
    anyhow::ensure!(
        packet.origin_lct == origin_lct
            && packet.destination_lct == destination_lct
            && packet.original_kind == original_kind
            && packet.pointer_uri == pointer_uri
            && packet.content_hash == content_hash,
        "persisted route-origin operation does not match requested send intent"
    );

    let origin_key = format!("route-origin:{}", packet.packet_id);
    let (origin_witness, _) = chain.append_once(
        &origin_key,
        "router.packet.originated",
        json!({
            "packet_id": packet.packet_id,
            "packet_hash": state.packet_hash,
            "operation_id": operation_id,
            "router_lct": router_lct,
            "origin_lct": packet.origin_lct,
            "destination_lct": packet.destination_lct,
            "original_kind": packet.original_kind,
            "pointer_uri": packet.pointer_uri,
            "content_hash": packet.content_hash,
            "hops_remaining": packet.hops_remaining,
            "custody": "router-origin",
        }),
        router_lct,
    )?;

    if state.decision_json.is_none() {
        let (action, outbound) = plan_action(&packet, &registry, &routes, router_lct)?;

        if let (
            Some(expected),
            PersistedAction::Forward { next_hop_lct, link_id, .. },
        ) = (expected_first_hop_hub_member, &action)
        {
            let neighbor = routes.neighbor_by_link(*link_id).ok_or_else(|| anyhow::anyhow!(
                "F3 route selects next hop {next_hop_lct} on missing neighbor link {link_id}"
            ))?;
            let interface = routes
                .router_ingress_by_id(neighbor.interface_binding_id)
                .ok_or_else(|| anyhow::anyhow!(
                    "F3 neighbor {next_hop_lct} references missing interface {}",
                    neighbor.interface_binding_id
                ))?;
            anyhow::ensure!(
                interface.hub_member_lct.to_string() == expected,
                "F3 first-hop carrier {} does not match transport-bound carrier {}",
                interface.hub_member_lct,
                expected
            );
        }

        let decision_json = serde_json::to_string(&action)?;
        match &action {
            PersistedAction::Forward {
                next_hop_lct,
                link_id,
                operation_id,
                ..
            } => inbox.record_router_forward_decision(
                packet.packet_id,
                &decision_json,
                outbound.as_deref().expect("forward plan carries packet bytes"),
                next_hop_lct,
                *link_id,
                operation_id,
            )?,
            PersistedAction::Local { child_lct, .. } => {
                inbox.record_router_local_decision(
                    packet.packet_id,
                    &decision_json,
                    Some(child_lct),
                )?
            }
            PersistedAction::Terminal { .. } => {
                inbox.record_router_local_decision(
                    packet.packet_id,
                    &decision_json,
                    None,
                )?
            }
        }
        state = inbox.router_packet_state(packet.packet_id)?
            .ok_or_else(|| anyhow::anyhow!(
                "originated route packet {} disappeared after route decision",
                packet.packet_id
            ))?;
    }

    if state.completion_witness_hash.is_none() {
        let action = persisted_action(&packet, &state)?;
        execute_action(
            &action,
            &packet,
            state.outbound_packet_json.as_deref(),
            &origin_witness.hash,
            None,
            None,
            vault,
            &routes,
            router_lct,
            inbox,
            chain,
            &HubClient::new(),
        ).await?;
        state = inbox.router_packet_state(packet.packet_id)?
            .ok_or_else(|| anyhow::anyhow!(
                "originated route packet {} disappeared after execution",
                packet.packet_id
            ))?;
    }

    let outcome = match state
        .decision_json
        .as_deref()
        .and_then(|v| serde_json::from_str::<PersistedAction>(v).ok())
    {
        Some(PersistedAction::Local { kind, source, .. })
            if kind == "unreachable" || source == "unreachable-bounce-local" =>
        {
            "unreachable_bounced"
        }
        Some(PersistedAction::Local { .. }) => "destination_local",
        Some(PersistedAction::Forward { packet_kind, .. })
            if packet_kind == "unreachable-bounce" =>
        {
            "unreachable_bounced"
        }
        Some(PersistedAction::Forward { .. }) => "next_hop_durable",
        Some(PersistedAction::Terminal { .. }) => "unreachable_terminal",
        None if state.completion_witness_hash.is_none() => "incomplete",
        None => "completed_unknown",
    }
    .to_string();

    Ok(RouteOriginReport {
        operation_id: operation_id.to_string(),
        packet_id: packet.packet_id,
        replayed: !inserted,
        completed: state.completion_witness_hash.is_some(),
        outcome,
        completion_kind: state.completion_kind,
        completion_witness_hash: state.completion_witness_hash,
        decision_json: state.decision_json,
    })
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
                        Some(&upstream_neighbor.next_hop_lct),
                        Some(upstream_member),
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
    fn runtime_neighbor_certificate_rejects_live_key_rotation_until_renewed() {
        let peer_router_key = web4_core::crypto::KeyPair::generate();
        let peer_member_key = web4_core::crypto::KeyPair::generate();
        let peer_router = web4_core::derive_lct_id(&peer_router_key.verifying_key());
        let hub = Uuid::new_v4();
        let peer_member = Uuid::new_v4();
        let cert = crate::router_certificate::RouterInterfaceCertificate::issue(
            crate::router_certificate::RouterInterfaceCertificatePayload {
                protocol: crate::router_certificate::ROUTER_CERT_PROTOCOL.into(),
                router_lct: peer_router.clone(),
                router_pubkey_hex: peer_router_key.verifying_key().to_hex(),
                hub_lct_id: hub,
                hub_member_lct: peer_member,
                hub_member_pubkey_hex: peer_member_key.verifying_key().to_hex(),
                interface_binding_id: Uuid::new_v4(),
                receipt_protocol: crate::router_certificate::RECEIPT_PROTOCOL.into(),
                issued_at: 9,
            },
            &peer_router_key,
            &peer_member_key,
        ).unwrap();
        let interface = RouterIngressBinding {
            binding_id: Uuid::new_v4(),
            router_lct: web4_core::derive_lct_id(
                &web4_core::crypto::KeyPair::generate().verifying_key(),
            ),
            hub_url: "https://hub.test".into(),
            hub_lct_id: hub,
            rest_endpoint: "https://hub.test/v1".into(),
            hub_member_lct: Uuid::new_v4(),
            member_key_source: crate::hub::MemberKeySource::VaultIdentity,
            reason: "test".into(),
            set_by: "test".into(),
            set_at: 1,
        };
        let neighbor = crate::receiver_routing::RouterNeighbor {
            link_id: Uuid::new_v4(),
            next_hop_lct: peer_router,
            interface_binding_id: interface.binding_id,
            next_hop_hub_member_lct: peer_member,
            peer_certificate: Some(cert),
            reason: "test".into(),
            set_by: "test".into(),
            set_at: 1,
        };

        assert!(verify_neighbor_certificate_live(
            &neighbor,
            &interface,
            &peer_member_key.verifying_key(),
        ).is_ok());

        let rotated = web4_core::crypto::KeyPair::generate();
        let err = verify_neighbor_certificate_live(
            &neighbor,
            &interface,
            &rotated.verifying_key(),
        ).unwrap_err();
        assert!(format!("{err:#}").contains("no longer matches live Hub pin"));
    }

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

    #[tokio::test]
    async fn route_origin_refuses_legacy_destination_identity() {
        let dir = tempfile::tempdir().unwrap();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let router = "lct:web4:mb32:router";
        let mut registry = load_members(&vault);
        let origin = crate::member_registry::ensure_member(
            &mut vault, &mut registry, "origin-being", false, router, "anchor",
        ).unwrap();
        ReceiverRoutingTable::default().save(&mut vault).unwrap();
        let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [0x53; 32]).unwrap();
        let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x53; 32]).unwrap();

        let err = originate_once(
            &vault,
            router,
            &origin,
            "lct:web4:member:legacy-name",
            "coordination",
            "shared-context/forum/origin-test.md",
            &format!("sha256-pointer:{}", "a".repeat(64)),
            "legacy-destination",
            &inbox,
            &chain,
        ).await.unwrap_err();
        assert!(format!("{err:#}").contains("canonical lct:web4:mb32"), "{err:#}");
    }

    #[tokio::test]
    async fn local_origin_retry_is_one_packet_one_local_notice() {
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
        let destination = crate::member_registry::ensure_member(
            &mut vault,
            &mut registry,
            "destination-being",
            false,
            router,
            "anchor",
        ).unwrap();

        let mut routes = ReceiverRoutingTable::default();
        routes.save(&mut vault).unwrap();

        let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [0x52; 32]).unwrap();
        let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x52; 32]).unwrap();
        let hash = format!("sha256-pointer:{}", "a".repeat(64));

        let first = originate_once(
            &vault,
            router,
            &origin,
            &destination,
            "coordination",
            "shared-context/forum/origin-test.md",
            &hash,
            "origin-op-1",
            &inbox,
            &chain,
        ).await.unwrap();
        assert!(!first.replayed);
        assert!(first.completed);
        assert_eq!(first.outcome, "destination_local");
        assert_eq!(first.completion_kind.as_deref(), Some("delivered-local"));

        let again = originate_once(
            &vault,
            router,
            &origin,
            &destination,
            "coordination",
            "shared-context/forum/origin-test.md",
            &hash,
            "origin-op-1",
            &inbox,
            &chain,
        ).await.unwrap();
        assert!(again.replayed);
        assert_eq!(again.packet_id, first.packet_id);
        assert_eq!(inbox.member_pending("destination-being").unwrap(), 1);

        let mail = inbox.drain_member("destination-being").unwrap();
        assert_eq!(mail.len(), 1);
        assert_eq!(mail[0].kind, "coordination");
        assert_eq!(
            mail[0].pointer_uri.as_deref(),
            Some("shared-context/forum/origin-test.md")
        );

        let err = originate_once(
            &vault,
            router,
            &origin,
            &destination,
            "coordination",
            "shared-context/forum/CHANGED.md",
            &hash,
            "origin-op-1",
            &inbox,
            &chain,
        ).await.unwrap_err();
        assert!(
            format!("{err:#}").contains("different send intent"),
            "{err:#}"
        );
    }

    #[tokio::test]
    async fn constrained_origin_refuses_wrong_actual_first_hop_carrier_before_network() {
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

        let destination = "lct:web4:mb32:remote-child";
        let peer_router_key = web4_core::crypto::KeyPair::generate();
        let next_hop = web4_core::derive_lct_id(&peer_router_key.verifying_key());
        let peer_member_key = web4_core::crypto::KeyPair::generate();
        let next_hop_member = Uuid::new_v4();
        let hub_lct = Uuid::new_v4();
        let peer_cert = crate::router_certificate::RouterInterfaceCertificate::issue(
            crate::router_certificate::RouterInterfaceCertificatePayload {
                protocol: crate::router_certificate::ROUTER_CERT_PROTOCOL.to_string(),
                router_lct: next_hop.clone(),
                router_pubkey_hex: peer_router_key.verifying_key().to_hex(),
                hub_lct_id: hub_lct,
                hub_member_lct: next_hop_member,
                hub_member_pubkey_hex: peer_member_key.verifying_key().to_hex(),
                interface_binding_id: Uuid::new_v4(),
                receipt_protocol: crate::router_certificate::RECEIPT_PROTOCOL.to_string(),
                issued_at: 1,
            },
            &peer_router_key,
            &peer_member_key,
        ).unwrap();
        let interface_id = Uuid::new_v4();
        let actual_carrier = Uuid::new_v4();
        let mut routes = ReceiverRoutingTable::default();
        routes.bind_router_ingress(crate::receiver_routing::RouterIngressBinding {
            binding_id: interface_id,
            router_lct: router.to_string(),
            hub_url: "https://hub.invalid".to_string(),
            hub_lct_id: hub_lct,
            rest_endpoint: "https://hub.invalid/v1".to_string(),
            hub_member_lct: actual_carrier,
            member_key_source: crate::hub::MemberKeySource::ChannelKeyFile {
                path: "/tmp/not-used-before-carrier-check".to_string(),
            },
            reason: "test interface".to_string(),
            set_by: "test".to_string(),
            set_at: 1,
        }).unwrap();
        routes.bind_neighbor(crate::receiver_routing::RouterNeighbor {
            link_id: Uuid::new_v4(),
            next_hop_lct: next_hop.clone(),
            interface_binding_id: interface_id,
            next_hop_hub_member_lct: next_hop_member,
            peer_certificate: Some(peer_cert),
            reason: "test neighbor".to_string(),
            set_by: "test".to_string(),
            set_at: 1,
        }).unwrap();
        routes.set_route(crate::receiver_routing::StaticRoute {
            destination_lct: destination.to_string(),
            next_hop_lct: next_hop.clone(),
            metric: 1,
            reason: "test route".to_string(),
        });
        routes.save(&mut vault).unwrap();

        let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [0x63; 32]).unwrap();
        let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x63; 32]).unwrap();
        let expected_other_carrier = Uuid::new_v4().to_string();

        let err = originate_once_constrained(
            &vault,
            router,
            &origin,
            destination,
            "coordination",
            "shared-context/forum/cutover-test.md",
            &format!("sha256-pointer:{}", "c".repeat(64)),
            "legacy-op-carrier-bound",
            &inbox,
            &chain,
            Some(&expected_other_carrier),
        ).await.unwrap_err();

        let msg = format!("{err:#}");
        assert!(msg.contains("does not match transport-bound carrier"), "{msg}");
        assert!(msg.contains(&actual_carrier.to_string()), "{msg}");
        assert!(msg.contains(&expected_other_carrier), "{msg}");
        // The deliberately invalid Hub URL is never touched: if carrier
        // validation happened after route commit/network I/O this test would fail
        // with a network/credential error instead of the mismatch above.
        assert!(
            msg.contains("transport-bound carrier"),
            "carrier mismatch must happen before route commit/network send"
        );
    }

    #[test]
    fn final_child_edge_reapplies_member_inbox_kind_and_pointer_contract() {
        assert!(routable_member_notice_kind("coordination"));
        assert!(routable_member_notice_kind("coordination.renotify"));
        assert!(routable_member_notice_kind("review_done.pr"));
        assert!(!routable_member_notice_kind("unreachable"));
        assert!(!routable_member_notice_kind("disposition"));
        assert!(!routable_member_notice_kind("coordinationX"));
        assert!(!routable_member_notice_kind("coordination."));
        assert!(!routable_member_notice_kind("Coordination"));
        assert!(!routable_member_notice_kind(&format!("coordination.{}", "a".repeat(64))));

        assert!(routable_member_pointer("shared-context/forum/x.md"));
        assert!(!routable_member_pointer(""));
        assert!(!routable_member_pointer("shared-context/ok\nINJECT"));
        assert!(!routable_member_pointer(&"x".repeat(513)));
    }

    #[test]
    fn unsafe_final_payload_bounces_instead_of_entering_child_inbox() {
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
        let destination = crate::member_registry::ensure_member(
            &mut vault,
            &mut registry,
            "destination-being",
            false,
            router,
            "anchor",
        ).unwrap();
        let mut routes = ReceiverRoutingTable::default();
        for child in [&origin, &destination] {
            routes.bind_local(crate::receiver_routing::LocalMailboxBinding {
                binding_id: Uuid::new_v4(),
                child_lct: child.clone(),
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
        }

        for (kind, pointer, reason_fragment) in [
            ("disposition", "shared-context/x", "local-kind-refused"),
            ("coordination", "shared-context/x\nINJECT", "local-pointer-refused"),
        ] {
            let packet = RoutePacketV1 {
                protocol: RoutePacketV1::PROTOCOL.to_string(),
                packet_id: Uuid::new_v4(),
                destination_lct: destination.clone(),
                origin_lct: origin.clone(),
                original_kind: kind.to_string(),
                pointer_uri: pointer.to_string(),
                content_hash: format!("sha256-pointer:{}", "a".repeat(64)),
                hops_remaining: 8,
                visited_routers: vec![],
                failure: None,
            };
            let (action, _outbound) =
                plan_action(&packet, &registry, &routes, router).unwrap();
            assert!(
                matches!(
                    action,
                    PersistedAction::Local {
                        kind,
                        delivery_packet_json: Some(_),
                        ..
                    } if kind == "unreachable"
                ),
                "{reason_fragment}: unsafe payload must become a local unreachable bounce"
            );
        }
    }

    #[tokio::test]
    async fn local_unreachable_notice_points_at_dereferenceable_chain_evidence() {
        let dir = tempfile::tempdir().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let inbox = SqliteInboxStore::open(dir.path().join("inbox.db"), [0x51; 32]).unwrap();
        let chain = SqliteChainStore::open(dir.path().join("witness.db"), [0x51; 32]).unwrap();
        let router = "lct:web4:mb32:router";
        let packet = RoutePacketV1 {
            protocol: RoutePacketV1::PROTOCOL.to_string(),
            packet_id: Uuid::new_v4(),
            destination_lct: "lct:web4:mb32:origin".to_string(),
            origin_lct: "lct:web4:mb32:failed-router".to_string(),
            original_kind: "unreachable".to_string(),
            pointer_uri: "hestia://route-error/original".to_string(),
            content_hash: format!("sha256-pointer:{}", "a".repeat(64)),
            hops_remaining: 7,
            visited_routers: vec!["lct:web4:mb32:previous-router".to_string()],
            failure: Some(crate::receiver_routing::RouteFailure {
                original_packet_id: Uuid::new_v4(),
                failed_destination_lct: "lct:web4:mb32:missing".to_string(),
                failed_at_router_lct: "lct:web4:mb32:failed-router".to_string(),
                reason: "no-route".to_string(),
            }),
        };
        let packet_json = serde_json::to_string(&packet).unwrap();
        let ingress = Uuid::new_v4();
        inbox.stage_router_packet(
            ingress,
            "route-test-notice",
            packet.packet_id,
            "route-test-envelope",
            &packet_json,
            &sha256_content(packet_json.as_bytes()),
        ).unwrap();

        let action = PersistedAction::Local {
            plugin_id: "origin-being".to_string(),
            child_lct: packet.destination_lct.clone(),
            from_lct: packet.origin_lct.clone(),
            kind: "unreachable".to_string(),
            pointer_uri: packet.pointer_uri.clone(),
            source: "unreachable-routed-local".to_string(),
            delivery_packet_json: Some(packet_json.clone()),
        };

        execute_action(
            &action,
            &packet,
            None,
            "stage-hash",
            Some("lct:web4:mb32:previous-router"),
            Some(Uuid::new_v4()),
            &vault,
            &ReceiverRoutingTable::default(),
            router,
            &inbox,
            &chain,
            &HubClient::new(),
        ).await.unwrap();

        let mail = inbox.drain_member("origin-being").unwrap();
        assert_eq!(mail.len(), 1);
        assert_eq!(mail[0].kind, "unreachable");
        let pointer = mail[0].pointer_uri.as_deref().unwrap();
        let hash = pointer.strip_prefix("hestia://chain/")
            .expect("unreachable notice must point at the existing chain resolver");
        let evidence = chain.read_by_hash(hash).unwrap().expect("evidence entry exists");
        assert_eq!(evidence.event_type, "router.packet.unreachable-evidence");
        assert_eq!(evidence.event_data["route_packet_json"], packet_json);

        let state = inbox.router_packet_state(packet.packet_id).unwrap().unwrap();
        assert_eq!(state.completion_kind.as_deref(), Some("delivered-local"));
        assert!(state.completion_witness_hash.is_some());
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
