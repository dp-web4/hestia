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
        anyhow::ensure!(!self.destination_lct.is_empty() && self.destination_lct.len() <= 256,
            "route destination_lct must be 1..256 bytes");
        anyhow::ensure!(!self.origin_lct.is_empty() && self.origin_lct.len() <= 256,
            "route origin_lct must be 1..256 bytes");
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
        anyhow::ensure!(self.visited_routers.iter().all(|r| !r.is_empty() && r.len() <= 256),
            "route visited_routers entries must be 1..256 bytes");
        if let Some(failure) = &self.failure {
            anyhow::ensure!(self.original_kind == "unreachable",
                "route failure is only valid on original_kind=unreachable");
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

    pub fn router_ingress_by_id(&self, binding_id: Uuid) -> Option<&RouterIngressBinding> {
        self.router_ingress.iter().find(|b| b.binding_id == binding_id)
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

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RouteDecision {
    Local {
        plugin_id: String,
        child_lct: String,
        binding_id: Uuid,
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
            let child_lct = m.lct.lct_id();
            if let Some(binding) = table.local_binding(&child_lct) {
                return Ok(RouteDecision::Local {
                    plugin_id: m.plugin_id.to_string(),
                    child_lct,
                    binding_id: binding.binding_id,
                });
            }
            return Ok(RouteDecision::LocalUnavailable {
                plugin_id: m.plugin_id.to_string(),
                child_lct,
                reason: "local-child-has-no-mailbox-binding".into(),
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
    fn exact_local_route_beats_specific_and_default() {
        let (_dir, _vault, reg, parent, child) = registry_world();
        let mut t = ReceiverRoutingTable::default();
        let conn = Uuid::new_v4();
        t.bind_local(LocalMailboxBinding {
            binding_id: conn,
            child_lct: child.clone(),
            hub_url: "https://hub.test".into(),
            hub_lct_id: Uuid::new_v4(),
            rest_endpoint: "https://hub.test/v1".into(),
            hub_member_lct: Uuid::new_v4(),
            member_key_source: MemberKeySource::ChannelKeyFile { path: "/tmp/test-key".into() },
            reason: "test".into(), set_by: "test".into(), set_at: 1,
        }).unwrap();
        t.set_route(StaticRoute {
            destination_lct: child.clone(), next_hop_lct: "wrong-hop".into(),
            metric: 0, reason: "test".into(),
        });
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "default-hop".into(), reason: "test".into(),
            set_by: "test".into(), set_at: 1,
        }));
        assert_eq!(
            decide_route(&reg, &t, &parent, &child, &RouteTrace::fresh(&t)).unwrap(),
            RouteDecision::Local {
                plugin_id: "being".into(), child_lct: child, binding_id: conn,
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
    fn local_without_transport_does_not_leak_to_default() {
        let (_dir, _vault, reg, parent, child) = registry_world();
        let mut t = ReceiverRoutingTable::default();
        t.set_default(Some(DefaultRoute {
            next_hop_lct: "upstream".into(), reason: "test".into(),
            set_by: "test".into(), set_at: 1,
        }));
        assert_eq!(
            decide_route(&reg, &t, &parent, &child, &RouteTrace::fresh(&t)).unwrap(),
            RouteDecision::LocalUnavailable {
                plugin_id: "being".into(), child_lct: child,
                reason: "local-child-has-no-mailbox-binding".into(),
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
