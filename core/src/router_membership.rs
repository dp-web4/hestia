//! D3 dedicated Hub memberships for the F3 machine router.
//!
//! Receipt-mode enrollment is one-way and makes the legacy destructive
//! `notifications` consumer refuse that mailbox. Therefore a first-edge F3
//! pilot must not reuse a seat/machine membership that legacy hub-watch still
//! drains. A router membership is a separate transport identity.
//!
//! The request record is persisted BEFORE the join network call. A retry after
//! a lost response or pending Sovereign admission reuses the same UUID/key
//! instead of minting a second router membership.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::vault::Vault;

const NAMESPACE: &str = "presence";
const DOC: &str = "router_memberships";
const LEGACY_FILE: &str = "router-memberships.json";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RouterMembership {
    /// Canonical machine/router identity. This is the routed Web4 identity,
    /// not the Hub membership UUID below.
    pub router_lct: String,
    /// Society/Hub this transport membership belongs to.
    pub hub_lct_id: Uuid,
    pub hub_url: String,
    pub rest_endpoint: String,

    /// Dedicated Hub membership used only by the F3 router plane.
    pub hub_member_lct: Uuid,
    /// Raw 32-byte Ed25519 seed handle for unattended receipt/forwarding.
    /// The encrypted vault stores the path, never a copy of the raw key bytes.
    pub channel_key_path: String,
    pub name: String,

    pub reason: String,
    #[serde(default)]
    pub requested_at: u64,
    #[serde(default)]
    pub admitted_at: Option<u64>,
    /// Set after Hestia binds this admitted membership as a router interface.
    #[serde(default)]
    pub interface_binding_id: Option<Uuid>,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default, PartialEq, Eq)]
pub struct RouterMembershipStore {
    #[serde(default)]
    pub memberships: Vec<RouterMembership>,
}

impl RouterMembershipStore {
    pub fn load(vault: &Vault) -> Result<Self> {
        crate::vault::load_doc(vault, NAMESPACE, DOC, LEGACY_FILE)
    }

    pub fn save(&self, vault: &mut Vault) -> Result<()> {
        crate::vault::save_doc(vault, NAMESPACE, DOC, LEGACY_FILE, self)
    }

    pub fn find(
        &self,
        hub_lct_id: Uuid,
        router_lct: &str,
    ) -> Option<&RouterMembership> {
        self.memberships.iter().find(|m| {
            m.hub_lct_id == hub_lct_id && m.router_lct == router_lct
        })
    }

    pub fn find_mut(
        &mut self,
        hub_lct_id: Uuid,
        router_lct: &str,
    ) -> Option<&mut RouterMembership> {
        self.memberships.iter_mut().find(|m| {
            m.hub_lct_id == hub_lct_id && m.router_lct == router_lct
        })
    }

    /// One router has at most one dedicated membership on one Hub. An operator
    /// may retry or advance its state, but changing UUID/key means explicitly
    /// deleting/retiring the old identity through a future governed path.
    pub fn insert_new(&mut self, membership: RouterMembership) -> Result<()> {
        anyhow::ensure!(
            self.find(membership.hub_lct_id, &membership.router_lct).is_none(),
            "router {} already has a dedicated membership on Hub {}",
            membership.router_lct,
            membership.hub_lct_id
        );
        anyhow::ensure!(
            !self.memberships.iter().any(|m| m.hub_member_lct == membership.hub_member_lct),
            "router Hub member UUID {} is already recorded",
            membership.hub_member_lct
        );
        anyhow::ensure!(
            !membership.name.trim().is_empty(),
            "router membership requires a non-empty Hub display name"
        );
        anyhow::ensure!(
            !membership.reason.trim().is_empty(),
            "router membership requires a reason"
        );
        self.memberships.push(membership);
        self.memberships.sort_by(|a, b| {
            a.hub_lct_id
                .cmp(&b.hub_lct_id)
                .then(a.router_lct.cmp(&b.router_lct))
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn member(hub: Uuid, router: &str, member: Uuid) -> RouterMembership {
        RouterMembership {
            router_lct: router.into(),
            hub_lct_id: hub,
            hub_url: "https://hub.example".into(),
            rest_endpoint: "https://hub.example/v1".into(),
            hub_member_lct: member,
            channel_key_path: "/tmp/router.key".into(),
            name: "test-router".into(),
            reason: "test".into(),
            requested_at: 1,
            admitted_at: None,
            interface_binding_id: None,
        }
    }

    #[test]
    fn one_router_one_membership_per_hub_and_uuid_is_unique() {
        let hub = Uuid::new_v4();
        let mut s = RouterMembershipStore::default();
        let m = Uuid::new_v4();
        s.insert_new(member(hub, "lct:web4:mb32:router-a", m)).unwrap();

        assert!(s
            .insert_new(member(hub, "lct:web4:mb32:router-a", Uuid::new_v4()))
            .unwrap_err()
            .to_string()
            .contains("already has"));

        assert!(s
            .insert_new(member(hub, "lct:web4:mb32:router-b", m))
            .unwrap_err()
            .to_string()
            .contains("already recorded"));
    }

    #[test]
    fn store_round_trips_in_vault() {
        let dir = tempfile::tempdir().unwrap();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let hub = Uuid::new_v4();
        let mut s = RouterMembershipStore::default();
        s.insert_new(member(
            hub,
            "lct:web4:mb32:router",
            Uuid::new_v4(),
        ))
        .unwrap();
        s.save(&mut vault).unwrap();

        let loaded = RouterMembershipStore::load(&vault).unwrap();
        assert_eq!(loaded, s);
    }
}
