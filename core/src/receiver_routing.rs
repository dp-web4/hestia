//! F3 machine receiver routing table.
//!
//! TCP/IP-shaped, not TCP/IP-copied: an addressed Web4 LCT is the destination,
//! parent bindings define directly-connected children, explicit routes name known
//! next hops, and a default gateway is consulted only when no more-specific route
//! exists. "Unknown here" therefore means ROUTE, not REFUSE. An unreachable is
//! terminal only after the route graph is exhausted, refused, loops, or hits its
//! hop limit.
//!
//! Routing never rewrites the destination identity. Delivery and wake are separate:
//! a local route selects an inbox; local law decides whether receipt wakes anything.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::hub::MemberKeySource;
use crate::addressing::{parse_address, Address};
use crate::member_registry::{LocalChildResolution, MemberRegistry};

const ROUTES_NAMESPACE: &str = "presence";
const ROUTES_DOC: &str = "receiver_routes";
const ROUTES_LEGACY_FILE: &str = "receiver-routes.json";
const DEFAULT_HOP_LIMIT: u8 = 16;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct LocalMailboxBinding {
    /// Stable local interface id. Hub receipt custody keys to this id rather than
    /// to the legacy HubStore, so N child identities may share one Hub endpoint.
    pub binding_id: Uuid,
    /// Canonical local member LCT (mb32), never a plugin id or legacy label.
    pub child_lct: String,
    /// Hub transport identity for this child. The Hub addresses/authenticates the
    /// UUID member independently of Hestia's local canonical mb32 presence.
    pub hub_url: String,
    pub hub_lct_id: Uuid,
    pub rest_endpoint: String,
    pub hub_member_lct: Uuid,
    /// Credential HANDLE only. ChannelKeyFile stores a path, not key bytes; the
    /// key is resolved at drain time and re-verified against the Hub pin.
    pub member_key_source: MemberKeySource,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
}

/// Mailbox interface addressed to the ROUTER itself, rather than to one hosted
/// child. Router-to-router route.forward packets arrive here. Keeping this
/// separate from LocalMailboxBinding preserves the identity distinction:
/// the machine/router is not its own child.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RouterIngressBinding {
    pub binding_id: Uuid,
    pub router_lct: String,
    pub hub_url: String,
    pub hub_lct_id: Uuid,
    pub rest_endpoint: String,
    pub hub_member_lct: Uuid,
    pub member_key_source: MemberKeySource,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
}

/// Layer-2-ish neighbor resolution for a layer-3 Web4 route.
///
/// RouteDecision names a canonical next-hop LCT. This record says how THIS
/// router reaches that next hop on a Hub: which local Hub identity signs the
/// hop, and which Hub member UUID is the recipient. The end destination never
/// changes to either UUID.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RouterNeighbor {
    pub link_id: Uuid,
    pub next_hop_lct: String,
    /// Existing router ingress/egress interface whose Hub identity/key signs
    /// this hop. One interface may have many neighbors.
    pub interface_binding_id: Uuid,
    pub next_hop_hub_member_lct: Uuid,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
}

/// Structured reason carried by an unreachable bounce. The outer route packet
/// is content-bound per hop; this object makes the terminal reason inspectable
/// without encoding it into an ad-hoc pointer fragment.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RouteFailure {
    pub original_packet_id: Uuid,
    pub failed_destination_lct: String,
    pub failed_at_router_lct: String,
    pub reason: String,
}

/// The end-to-end routing packet. Intermediate routers may change ONLY the
/// trace (hops_remaining / visited_routers) and, for a new bounce, construct a
/// new packet whose failure names the original packet. Every hop content-binds
/// the exact serialized bytes on its Hub ledger.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RoutePacketV1 {
    pub protocol: String,
    pub packet_id: Uuid,
    pub destination_lct: String,
    pub origin_lct: String,
    pub original_kind: String,
    pub pointer_uri: String,
    pub content_hash: String,
    pub hops_remaining: u8,
    pub visited_routers: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<RouteFailure>,
}

impl RoutePacketV1 {
    pub const PROTOCOL: &'static str = "web4-route-v1";

    pub fn validate(&self) -> Result<()> {
        anyhow::ensure!(self.protocol == Self::PROTOCOL, "route packet protocol must be {}", Self::PROTOCOL);
        anyhow::ensure!(
            self.destination_lct.starts_with("lct:web4:") && self.destination_lct.len() <= 256,
            "route destination_lct must be a canonical lct:web4:* id of <=256 bytes"
        );
        anyhow::ensure!(
            self.origin_lct.starts_with("lct:web4:") && self.origin_lct.len() <= 256,
            "route origin_lct must be a canonical lct:web4:* id of <=256 bytes"
        );
        anyhow::ensure!(!self.original_kind.is_empty() && self.original_kind.len() <= 128,
            "route original_kind must be 1..128 bytes");
        anyhow::ensure!(!self.pointer_uri.is_empty() && self.pointer_uri.len() <= 512,
            "route pointer_uri must be 1..512 bytes");
        anyhow::ensure!(valid_content_hash(&self.content_hash),
            "route content_hash is not a supported scheme-tagged digest");
        anyhow::ensure!((1..=64).contains(&self.hops_remaining),
            "route hops_remaining must be 1..64");
        anyhow::ensure!(self.visited_routers.len() <= 64,
            "route visited_routers exceeds 64 entries");
        anyhow::ensure!(
            self.visited_routers.iter().all(|r| r.starts_with("lct:web4:") && r.len() <= 256),
            "route visited_routers entries must be canonical lct:web4:* ids of <=256 bytes"
        );
        let unique: std::collections::BTreeSet<&str> =
            self.visited_routers.iter().map(String::as_str).collect();
        anyhow::ensure!(
            unique.len() == self.visited_routers.len(),
            "route visited_routers contains a duplicate router"
        );
        anyhow::ensure!(
            (self.original_kind == "unreachable") == self.failure.is_some(),
            "route original_kind=unreachable requires exactly one failure object"
        );
        if let Some(failure) = &self.failure {
            anyhow::ensure!(
                failure.failed_destination_lct.starts_with("lct:web4:")
                    && failure.failed_destination_lct.len() <= 256,
                "route failure failed_destination_lct must be a canonical lct:web4:* id"
            );
            anyhow::ensure!(
                failure.failed_at_router_lct.starts_with("lct:web4:")
                    && failure.failed_at_router_lct.len() <= 256,
                "route failure failed_at_router_lct must be a canonical lct:web4:* id"
            );
            anyhow::ensure!(!failure.reason.is_empty() && failure.reason.len() <= 512,
                "route failure reason must be 1..512 bytes");
        }
        Ok(())
    }

    pub fn trace(&self) -> RouteTrace {
        RouteTrace {
            hops_remaining: self.hops_remaining,
            visited_routers: self.visited_routers.clone(),
        }
    }

    /// Packet presented to the next hop. This is the router equivalent of
    /// decrementing TTL and writing the outgoing interface into a trace.
    pub fn after_forward(&self, router_lct: &str) -> Result<Self> {
        self.validate()?;
        anyhow::ensure!(self.hops_remaining > 1,
            "cannot forward: hop limit would be exhausted");
        anyhow::ensure!(!self.visited_routers.iter().any(|r| r == router_lct),
            "cannot forward: router {router_lct} is already in the route trace");
        let mut out = self.clone();
        out.hops_remaining -= 1;
        out.visited_routers.push(router_lct.to_string());
        out.validate()?;
        Ok(out)
    }

    /// A terminal data-packet failure becomes a NEW packet addressed back to
    /// the original sender. An unreachable packet is never bounced again; the
    /// caller must witness its terminal failure locally if its return path dies.
    pub fn unreachable_bounce(
        &self,
        router_lct: &str,
        reason: impl Into<String>,
        hop_limit: u8,
    ) -> Result<Self> {
        self.validate()?;
        anyhow::ensure!(self.failure.is_none() && self.original_kind != "unreachable",
            "an unreachable packet must not recursively generate another unreachable");
        let reason = reason.into();
        anyhow::ensure!(!reason.is_empty() && reason.len() <= 512,
            "route failure reason must be 1..512 bytes");
        let pointer_uri = format!("hestia://route-error/{}", self.packet_id);
        let content_hash = format!(
            "sha256-pointer:{}",
            sha256_hex(pointer_uri.as_bytes())
        );
        let bounce = Self {
            protocol: Self::PROTOCOL.to_string(),
            packet_id: Uuid::new_v4(),
            destination_lct: self.origin_lct.clone(),
            origin_lct: router_lct.to_string(),
            original_kind: "unreachable".to_string(),
            pointer_uri,
            content_hash,
            hops_remaining: hop_limit.clamp(1, 64),
            visited_routers: Vec::new(),
            failure: Some(RouteFailure {
                original_packet_id: self.packet_id,
                failed_destination_lct: self.destination_lct.clone(),
                failed_at_router_lct: router_lct.to_string(),
                reason,
            }),
        };
        bounce.validate()?;
        Ok(bounce)
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    hex::encode(Sha256::digest(bytes))
}

fn valid_content_hash(value: &str) -> bool {
    let Some((scheme, digest)) = value.split_once(':') else { return false };
    match scheme {
        "git-sha" => digest.len() == 40 && digest.bytes().all(|b| b.is_ascii_hexdigit()),
        "sha256-content" | "sha256-pointer" => {
            digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_hexdigit())
        }
        _ => false,
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LegacyDeliveryAuthority {
    /// Historical peer/member queue + member-mesh drain remains authoritative.
    #[default]
    Legacy,
    /// Exact alias translates into canonical F3 origination.
    ///
    /// This is per-alias and opt-in: adding an alias never cuts traffic over.
    F3,
}

impl LegacyDeliveryAuthority {
    pub fn parse(value: &str) -> Option<Self> {
        match value.trim() {
            "legacy" => Some(Self::Legacy),
            "f3" => Some(Self::F3),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Legacy => "legacy",
            Self::F3 => "f3",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LegacyRouteAlias {
    /// Exact legacy compatibility spelling, e.g. `thor/claude-code`.
    /// This is an edge alias only; it never appears in a route packet.
    pub legacy_address: String,
    /// Canonical END MEMBER identity. Never the peer-machine/router LCT.
    pub destination_lct: String,
    /// Which delivery plane owns this exact compatibility edge.
    ///
    /// Serde-default LEGACY is load-bearing: old routing documents and newly
    /// added aliases stay observational until the operator explicitly cuts
    /// this one edge over after measured D2 evidence.
    #[serde(default)]
    pub delivery_authority: LegacyDeliveryAuthority,
    /// Why this edge changed delivery authority. None means the serde-default
    /// legacy posture has never been deliberately cut over.
    #[serde(default)]
    pub authority_reason: Option<String>,
    #[serde(default)]
    pub authority_set_by: String,
    #[serde(default)]
    pub authority_set_at: u64,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LegacyRouteShadow {
    NotRouted {
        legacy_address: String,
    },
    MissingAlias {
        legacy_address: String,
    },
    Resolved {
        legacy_address: String,
        destination_lct: String,
        decision: RouteDecision,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct StaticRoute {
    /// Exact v1 destination. A future graph route may widen this to a witnessed
    /// subtree predicate without changing RouteDecision.
    pub destination_lct: String,
    pub next_hop_lct: String,
    #[serde(default)]
    pub metric: u32,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DefaultRoute {
    pub next_hop_lct: String,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ReceiverRoutingTable {
    #[serde(default)]
    pub local_mailboxes: Vec<LocalMailboxBinding>,
    #[serde(default)]
    pub router_ingress: Vec<RouterIngressBinding>,
    #[serde(default)]
    pub neighbors: Vec<RouterNeighbor>,
    /// D2 compatibility edge: legacy peer/member spelling -> canonical END member LCT.
    /// Never inferred from peer names and never written into route packets.
    #[serde(default)]
    pub legacy_aliases: Vec<LegacyRouteAlias>,
    #[serde(default)]
    pub routes: Vec<StaticRoute>,
    #[serde(default)]
    pub default_route: Option<DefaultRoute>,
    #[serde(default = "default_hop_limit")]
    pub hop_limit: u8,
}

fn default_hop_limit() -> u8 {
    DEFAULT_HOP_LIMIT
}

impl Default for ReceiverRoutingTable {
    fn default() -> Self {
        Self {
            local_mailboxes: Vec::new(),
            router_ingress: Vec::new(),
            neighbors: Vec::new(),
            legacy_aliases: Vec::new(),
            routes: Vec::new(),
            default_route: None,
            hop_limit: DEFAULT_HOP_LIMIT,
        }
    }
}

impl ReceiverRoutingTable {
    pub fn load(vault: &crate::vault::Vault) -> Result<Self> {
        crate::vault::load_doc(vault, ROUTES_NAMESPACE, ROUTES_DOC, ROUTES_LEGACY_FILE)
    }

    pub fn save(&self, vault: &mut crate::vault::Vault) -> Result<()> {
        crate::vault::save_doc(vault, ROUTES_NAMESPACE, ROUTES_DOC, ROUTES_LEGACY_FILE, self)
    }

    /// Add one directly-connected local mailbox interface.
    ///
    /// A child binding is immutable in place: changing its Hub member/key while
    /// receipt custody is pending would strand ACK state under the old identity.
    /// Operators unbind (only when no custody remains) and then bind the new
    /// interface explicitly.
    pub fn bind_local(&mut self, binding: LocalMailboxBinding) -> Result<()> {
        anyhow::ensure!(
            !self.local_mailboxes.iter().any(|b| b.child_lct == binding.child_lct),
            "local mailbox route for {} already exists; unbind it before changing transport identity",
            binding.child_lct
        );
        anyhow::ensure!(
            !self.local_mailboxes.iter().any(|b| b.binding_id == binding.binding_id),
            "receiver binding id {} is already in use",
            binding.binding_id
        );
        self.local_mailboxes.push(binding);
        self.local_mailboxes.sort_by(|a, b| a.child_lct.cmp(&b.child_lct));
        Ok(())
    }

    pub fn unbind_local(&mut self, child_lct: &str) -> bool {
        let before = self.local_mailboxes.len();
        self.local_mailboxes.retain(|b| b.child_lct != child_lct);
        before != self.local_mailboxes.len()
    }

    pub fn bind_router_ingress(&mut self, binding: RouterIngressBinding) -> Result<()> {
        anyhow::ensure!(
            !self.router_ingress.iter().any(|b| b.binding_id == binding.binding_id),
            "router ingress binding id {} is already in use",
            binding.binding_id
        );
        anyhow::ensure!(
            !self.router_ingress.iter().any(|b| {
                b.router_lct == binding.router_lct
                    && b.hub_lct_id == binding.hub_lct_id
                    && b.hub_member_lct == binding.hub_member_lct
            }),
            "router ingress for {} on Hub member {} already exists",
            binding.router_lct, binding.hub_member_lct
        );
        self.router_ingress.push(binding);
        self.router_ingress.sort_by(|a, b| {
            a.router_lct.cmp(&b.router_lct).then(a.hub_member_lct.cmp(&b.hub_member_lct))
        });
        Ok(())
    }

    pub fn bind_neighbor(&mut self, neighbor: RouterNeighbor) -> Result<()> {
        anyhow::ensure!(!neighbor.next_hop_lct.trim().is_empty(),
            "neighbor next_hop_lct must not be empty");
        anyhow::ensure!(
            !self.neighbors.iter().any(|n| n.next_hop_lct == neighbor.next_hop_lct),
            "neighbor {} already exists; remove it only after transit custody is clear",
            neighbor.next_hop_lct
        );
        anyhow::ensure!(
            !self.neighbors.iter().any(|n| n.link_id == neighbor.link_id),
            "router neighbor link id {} is already in use",
            neighbor.link_id
        );
        anyhow::ensure!(
            !self.neighbors.iter().any(|n| {
                n.interface_binding_id == neighbor.interface_binding_id
                    && n.next_hop_hub_member_lct == neighbor.next_hop_hub_member_lct
            }),
            "Hub member {} on interface {} is already bound to another canonical neighbor",
            neighbor.next_hop_hub_member_lct,
            neighbor.interface_binding_id
        );
        self.neighbors.push(neighbor);
        self.neighbors.sort_by(|a, b| a.next_hop_lct.cmp(&b.next_hop_lct));
        Ok(())
    }

    pub fn neighbor(&self, next_hop_lct: &str) -> Option<&RouterNeighbor> {
        self.neighbors.iter().find(|n| n.next_hop_lct == next_hop_lct)
    }

    pub fn neighbor_by_link(&self, link_id: Uuid) -> Option<&RouterNeighbor> {
        self.neighbors.iter().find(|n| n.link_id == link_id)
    }

    pub fn ingress_neighbor(
        &self,
        interface_binding_id: Uuid,
        hub_member_lct: Uuid,
    ) -> Result<Option<&RouterNeighbor>> {
        let matches: Vec<&RouterNeighbor> = self
            .neighbors
            .iter()
            .filter(|n| {
                n.interface_binding_id == interface_binding_id
                    && n.next_hop_hub_member_lct == hub_member_lct
            })
            .collect();
        anyhow::ensure!(
            matches.len() <= 1,
            "Hub member {hub_member_lct} on interface {interface_binding_id} maps to more than one canonical neighbor"
        );
        Ok(matches.into_iter().next())
    }

    pub fn router_ingress_by_id(&self, binding_id: Uuid) -> Option<&RouterIngressBinding> {
        self.router_ingress.iter().find(|b| b.binding_id == binding_id)
    }

    pub fn bind_legacy_alias(&mut self, alias: LegacyRouteAlias) -> Result<()> {
        match parse_address(&alias.legacy_address) {
            Ok(Address::Routed { .. }) => {}
            Ok(Address::Local(_)) => anyhow::bail!(
                "legacy route alias '{}' is local, not peer/member",
                alias.legacy_address
            ),
            Err(e) => anyhow::bail!(
                "legacy route alias '{}' is malformed: {e:?}",
                alias.legacy_address
            ),
        }
        anyhow::ensure!(
            alias.destination_lct.starts_with("lct:web4:mb32:"),
            "legacy alias destination must be a canonical lct:web4:mb32:* member identity"
        );
        anyhow::ensure!(
            !alias.reason.trim().is_empty(),
            "legacy route alias requires a reason"
        );
        anyhow::ensure!(
            !self.legacy_aliases.iter().any(|a| a.legacy_address == alias.legacy_address),
            "legacy route alias '{}' already exists; remove it before changing identity",
            alias.legacy_address
        );
        self.legacy_aliases.push(alias);
        self.legacy_aliases.sort_by(|a, b| a.legacy_address.cmp(&b.legacy_address));
        Ok(())
    }

    pub fn unbind_legacy_alias(&mut self, legacy_address: &str) -> bool {
        let before = self.legacy_aliases.len();
        self.legacy_aliases.retain(|a| a.legacy_address != legacy_address);
        before != self.legacy_aliases.len()
    }

    pub fn legacy_alias(&self, legacy_address: &str) -> Option<&LegacyRouteAlias> {
        self.legacy_aliases.iter().find(|a| a.legacy_address == legacy_address)
    }

    pub fn set_legacy_authority(
        &mut self,
        legacy_address: &str,
        authority: LegacyDeliveryAuthority,
        reason: &str,
        set_by: &str,
        set_at: u64,
    ) -> Result<()> {
        anyhow::ensure!(
            !reason.trim().is_empty(),
            "changing legacy delivery authority requires a named migration reason"
        );
        let alias = self
            .legacy_aliases
            .iter_mut()
            .find(|a| a.legacy_address == legacy_address)
            .ok_or_else(|| anyhow::anyhow!(
                "legacy route alias '{legacy_address}' does not exist"
            ))?;
        alias.delivery_authority = authority;
        alias.authority_reason = Some(reason.trim().to_string());
        alias.authority_set_by = set_by.to_string();
        alias.authority_set_at = set_at;
        Ok(())
    }

    pub fn shadow_legacy_route(
        &self,
        registry: &MemberRegistry,
        router_lct: &str,
        legacy_address: &str,
    ) -> Result<LegacyRouteShadow> {
        match parse_address(legacy_address) {
            Ok(Address::Local(_)) => {
                return Ok(LegacyRouteShadow::NotRouted {
                    legacy_address: legacy_address.to_string(),
                });
            }
            Ok(Address::Routed { .. }) => {}
            Err(e) => anyhow::bail!(
                "legacy address '{}' is malformed: {e:?}",
                legacy_address
            ),
        }
        let Some(alias) = self.legacy_alias(legacy_address) else {
            return Ok(LegacyRouteShadow::MissingAlias {
                legacy_address: legacy_address.to_string(),
            });
        };
        let decision = decide_route(
            registry,
            self,
            router_lct,
            &alias.destination_lct,
            &RouteTrace::fresh(self),
        )?;
        Ok(LegacyRouteShadow::Resolved {
            legacy_address: legacy_address.to_string(),
            destination_lct: alias.destination_lct.clone(),
            decision,
        })
    }

    pub fn set_route(&mut self, route: StaticRoute) {
        self.routes.retain(|r| {
            !(r.destination_lct == route.destination_lct && r.next_hop_lct == route.next_hop_lct)
        });
        self.routes.push(route);
        self.routes.sort_by(|a, b| {
            a.destination_lct
                .cmp(&b.destination_lct)
                .then(a.metric.cmp(&b.metric))
                .then(a.next_hop_lct.cmp(&b.next_hop_lct))
        });
    }

    pub fn set_default(&mut self, route: Option<DefaultRoute>) {
        self.default_route = route.filter(|r| !r.next_hop_lct.trim().is_empty());
    }

    pub fn local_binding(&self, child_lct: &str) -> Option<&LocalMailboxBinding> {
        self.local_mailboxes.iter().find(|b| b.child_lct == child_lct)
    }

    fn best_static_route(&self, destination_lct: &str) -> Result<Option<&StaticRoute>> {
        let mut routes: Vec<&StaticRoute> = self
            .routes
            .iter()
            .filter(|r| r.destination_lct == destination_lct)
            .collect();
        if routes.is_empty() {
            return Ok(None);
        }
        routes.sort_by_key(|r| r.metric);
        let best_metric = routes[0].metric;
        let best: Vec<&StaticRoute> = routes
            .into_iter()
            .filter(|r| r.metric == best_metric)
            .collect();
        anyhow::ensure!(
            best.iter().map(|r| r.next_hop_lct.as_str()).collect::<std::collections::BTreeSet<_>>().len() == 1,
            "ambiguous receiver route for {destination_lct}: multiple next hops at metric {best_metric}"
        );
        Ok(best.into_iter().next())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RouteTrace {
    pub hops_remaining: u8,
    pub visited_routers: Vec<String>,
}

impl RouteTrace {
    pub fn fresh(table: &ReceiverRoutingTable) -> Self {
        Self {
            hops_remaining: table.hop_limit,
            visited_routers: Vec::new(),
        }
    }

    pub fn after_forward(&self, router_lct: &str) -> Self {
        let mut visited = self.visited_routers.clone();
        visited.push(router_lct.to_string());
        Self {
            hops_remaining: self.hops_remaining.saturating_sub(1),
            visited_routers: visited,
        }
    }
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum RouteDecision {
    Local {
        plugin_id: String,
        child_lct: String,
    },
    /// The destination remains the original addressed LCT. `next_hop_lct` is
    /// transport only, exactly like a gateway/MAC next hop does not replace an
    /// IP destination.
    Forward {
        destination_lct: String,
        next_hop_lct: String,
        via: &'static str,
    },
    /// A directly connected identity exists here but cannot presently receive.
    /// Do not default-route a local address upward and risk a loop/misdelivery.
    LocalUnavailable {
        plugin_id: String,
        child_lct: String,
        reason: String,
    },
    Unreachable {
        destination_lct: String,
        reason: String,
    },
}

/// Decide only the NEXT routing action. This function does not fetch, enqueue,
/// wake, or forward. Callers carry RouteTrace across hops.
pub fn decide_route(
    registry: &MemberRegistry,
    table: &ReceiverRoutingTable,
    router_lct: &str,
    destination_lct: &str,
    trace: &RouteTrace,
) -> Result<RouteDecision> {
    if trace.hops_remaining == 0 {
        return Ok(RouteDecision::Unreachable {
            destination_lct: destination_lct.to_string(),
            reason: "hop-limit-exhausted".into(),
        });
    }
    if trace.visited_routers.iter().any(|r| r == router_lct) {
        return Ok(RouteDecision::Unreachable {
            destination_lct: destination_lct.to_string(),
            reason: format!("routing-loop:{router_lct}"),
        });
    }

    match registry.resolve_child_of(router_lct, destination_lct)? {
        LocalChildResolution::Local(m) => {
            // Parent binding is the local-link fact for router transit. A
            // LocalMailboxBinding is a child-specific HUB INGRESS interface used
            // by Slice B; requiring it here would make a locally hosted member
            // unreachable merely because it receives routed traffic through the
            // machine router rather than through its own Hub mailbox.
            return Ok(RouteDecision::Local {
                plugin_id: m.plugin_id.to_string(),
                child_lct: m.lct.lct_id(),
            });
        }
        LocalChildResolution::KnownButNotChild(_) | LocalChildResolution::Unknown => {}
    }

    let candidate = if let Some(route) = table.best_static_route(destination_lct)? {
        Some((route.next_hop_lct.as_str(), "specific"))
    } else {
        table.default_route.as_ref().map(|r| (r.next_hop_lct.as_str(), "default"))
    };

    let Some((next_hop, via)) = candidate else {
        return Ok(RouteDecision::Unreachable {
            destination_lct: destination_lct.to_string(),
            reason: "no-route".into(),
        });
    };

    if next_hop == router_lct || trace.visited_routers.iter().any(|r| r == next_hop) {
        return Ok(RouteDecision::Unreachable {
            destination_lct: destination_lct.to_string(),
            reason: format!("routing-loop-next-hop:{next_hop}"),
        });
    }

    Ok(RouteDecision::Forward {
        destination_lct: destination_lct.to_string(),
        next_hop_lct: next_hop.to_string(),
        via,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::member_registry::{ensure_member, load_members};
    use crate::vault::Vault;

    fn registry_world() -> (tempfile::TempDir, Vault, MemberRegistry, String, String) {
        let dir = tempfile::tempdir().unwrap();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let parent = "lct:web4:mb32:parent".to_string();
        let mut reg = load_members(&vault);
        let child = ensure_member(&mut vault, &mut reg, "being", false, &parent, "parent-anchor").unwrap();
        (dir, vault, reg, parent, child)
    }

    #[test]
    fn legacy_alias_is_exact_and_targets_end_member_not_peer_machine() {
        let (_dir, _vault, reg, parent, _child) = registry_world();
        let mut t = ReceiverRoutingTable::default();
        let destination = "lct:web4:mb32:remote-child".to_string();
        t.bind_legacy_alias(LegacyRouteAlias {
            legacy_address: "thor/claude-code".into(),
            destination_lct: destination.clone(),
            reason: "explicit compatibility mapping".into(),
            set_by: "test".into(),
            set_at: 1,
        }).unwrap();
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "lct:web4:mb32:thor-router".into(),
            reason: "upstream".into(),
            set_by: "test".into(),
            set_at: 1,
        }));

        let shadow = t.shadow_legacy_route(
            &reg, &parent, "thor/claude-code"
        ).unwrap();
        assert_eq!(
            shadow,
            LegacyRouteShadow::Resolved {
                legacy_address: "thor/claude-code".into(),
                destination_lct: destination.clone(),
                decision: RouteDecision::Forward {
                    destination_lct: destination,
                    next_hop_lct: "lct:web4:mb32:thor-router".into(),
                    via: "default",
                },
            }
        );
        assert_eq!(
            t.shadow_legacy_route(&reg, &parent, "thor/kimi-code").unwrap(),
            LegacyRouteShadow::MissingAlias {
                legacy_address: "thor/kimi-code".into()
            },
            "member identity is never inferred from the peer/machine alias"
        );
    }

    #[test]
    fn legacy_alias_refuses_local_source_route_and_legacy_identity_targets() {
        let mut t = ReceiverRoutingTable::default();
        let mk = |addr: &str, dest: &str| LegacyRouteAlias {
            legacy_address: addr.into(),
            destination_lct: dest.into(),
            reason: "test".into(),
            set_by: "test".into(),
            set_at: 1,
        };
        assert!(t.bind_legacy_alias(mk(
            "claude-code", "lct:web4:mb32:remote"
        )).unwrap_err().to_string().contains("local"));
        assert!(t.bind_legacy_alias(mk(
            "fleet/thor/claude-code", "lct:web4:mb32:remote"
        )).is_err());
        assert!(t.bind_legacy_alias(mk(
            "thor/claude-code", "lct:web4:member:legacy"
        )).unwrap_err().to_string().contains("canonical"));
    }

    #[test]
    fn parent_bound_child_is_local_without_a_direct_hub_mailbox() {
        let (_dir, _vault, reg, parent, child) = registry_world();
        let mut t = ReceiverRoutingTable::default();
        // Even an explicit remote/default route may not steal a child whose
        // canonical LCT says this router is its parent.
        t.set_route(StaticRoute {
            destination_lct: child.clone(), next_hop_lct: "wrong-hop".into(),
            metric: 0, reason: "test".into(),
        });
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "default-hop".into(), reason: "test".into(),
            set_by: "test".into(), set_at: 1,
        }));
        assert!(t.local_mailboxes.is_empty());
        assert_eq!(
            decide_route(&reg, &t, &parent, &child, &RouteTrace::fresh(&t)).unwrap(),
            RouteDecision::Local {
                plugin_id: "being".into(), child_lct: child,
            }
        );
    }

    #[test]
    fn known_nonlocal_and_unknown_route_instead_of_refusing() {
        let (_dir, _vault, mut reg, parent, _child) = registry_world();
        let remote_dir = tempfile::tempdir().unwrap();
        let mut vault2 = Vault::init(remote_dir.path().join("v.enc"), "p".into()).unwrap();
        let remote_parent = "lct:web4:mb32:remote-parent";
        let remote = ensure_member(&mut vault2, &mut reg, "remote", false, remote_parent, "remote-anchor").unwrap();
        let mut t = ReceiverRoutingTable::default();
        t.set_route(StaticRoute {
            destination_lct: remote.clone(), next_hop_lct: "specific-hop".into(),
            metric: 5, reason: "known route".into(),
        });
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "upstream".into(), reason: "test".into(),
            set_by: "test".into(), set_at: 1,
        }));
        let trace = RouteTrace::fresh(&t);
        assert_eq!(
            decide_route(&reg, &t, &parent, &remote, &trace).unwrap(),
            RouteDecision::Forward {
                destination_lct: remote, next_hop_lct: "specific-hop".into(), via: "specific",
            }
        );
        assert_eq!(
            decide_route(&reg, &t, &parent, "lct:web4:mb32:unknown", &trace).unwrap(),
            RouteDecision::Forward {
                destination_lct: "lct:web4:mb32:unknown".into(),
                next_hop_lct: "upstream".into(), via: "default",
            }
        );
    }

    #[test]
    fn no_route_loop_and_hop_limit_are_terminal() {
        let (_dir, _vault, reg, parent, _child) = registry_world();
        let t = ReceiverRoutingTable::default();
        assert!(matches!(
            decide_route(&reg, &t, &parent, "unknown", &RouteTrace::fresh(&t)).unwrap(),
            RouteDecision::Unreachable { reason, .. } if reason == "no-route"
        ));
        let mut t = ReceiverRoutingTable::default();
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "upstream".into(), reason: "test".into(),
            set_by: "test".into(), set_at: 1,
        }));
        assert!(matches!(
            decide_route(
                &reg, &t, &parent, "unknown",
                &RouteTrace { hops_remaining: 0, visited_routers: vec![] }
            ).unwrap(),
            RouteDecision::Unreachable { reason, .. } if reason == "hop-limit-exhausted"
        ));
        assert!(matches!(
            decide_route(
                &reg, &t, &parent, "unknown",
                &RouteTrace { hops_remaining: 5, visited_routers: vec!["upstream".into()] }
            ).unwrap(),
            RouteDecision::Unreachable { reason, .. } if reason.starts_with("routing-loop-next-hop:")
        ));
    }
}
