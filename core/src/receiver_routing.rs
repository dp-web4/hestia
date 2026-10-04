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

use crate::member_registry::{LocalChildResolution, MemberRegistry};

const ROUTES_NAMESPACE: &str = "presence";
const ROUTES_DOC: &str = "receiver_routes";
const ROUTES_LEGACY_FILE: &str = "receiver-routes.json";
const DEFAULT_HOP_LIMIT: u8 = 16;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LocalMailboxBinding {
    /// Canonical local member LCT (mb32), never a plugin id or legacy label.
    pub child_lct: String,
    /// Hestia HubStore connection whose `our_lct_id` + key source are the
    /// transport credential for this child.
    pub hub_connection_id: Uuid,
    pub reason: String,
    #[serde(default)]
    pub set_by: String,
    #[serde(default)]
    pub set_at: u64,
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
pub struct ReceiverRoutingTable {
    #[serde(default)]
    pub local_mailboxes: Vec<LocalMailboxBinding>,
    #[serde(default)]
    pub routes: Vec<StaticRoute>,
    #[serde(default)]
    pub default_next_hop_lct: Option<String>,
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
            routes: Vec::new(),
            default_next_hop_lct: None,
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

    pub fn bind_local(&mut self, binding: LocalMailboxBinding) {
        self.local_mailboxes.retain(|b| b.child_lct != binding.child_lct);
        self.local_mailboxes.push(binding);
        self.local_mailboxes.sort_by(|a, b| a.child_lct.cmp(&b.child_lct));
    }

    pub fn unbind_local(&mut self, child_lct: &str) -> bool {
        let before = self.local_mailboxes.len();
        self.local_mailboxes.retain(|b| b.child_lct != child_lct);
        before != self.local_mailboxes.len()
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

    pub fn set_default(&mut self, next_hop_lct: Option<String>) {
        self.default_next_hop_lct = next_hop_lct.filter(|s| !s.trim().is_empty());
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
        hub_connection_id: Uuid,
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
                    hub_connection_id: binding.hub_connection_id,
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
        table.default_next_hop_lct.as_deref().map(|n| (n, "default"))
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
            child_lct: child.clone(), hub_connection_id: conn,
            reason: "test".into(), set_by: "test".into(), set_at: 1,
        });
        t.set_route(StaticRoute {
            destination_lct: child.clone(), next_hop_lct: "wrong-hop".into(),
            metric: 0, reason: "test".into(),
        });
        t.set_default(Some("default-hop".into()));
        assert_eq!(
            decide_route(&reg, &t, &parent, &child, &RouteTrace::fresh(&t)).unwrap(),
            RouteDecision::Local {
                plugin_id: "being".into(), child_lct: child, hub_connection_id: conn,
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
        t.set_default(Some("upstream".into()));
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
        t.set_default(Some("upstream".into()));
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
        t.set_default(Some("upstream".into()));
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
