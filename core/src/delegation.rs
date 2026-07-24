//! Delegation management — vault-backed storage for DelegatedAuthority grants.
//!
//! Wraps web4-core's `DelegatedAuthority` with local persistence (JSON file
//! alongside the vault) and CLI surface for creating, listing, and revoking
//! delegations.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use web4_core::crypto::KeyPair;
use web4_core::delegation::{DelegatedAuthority, DelegationScope};
use web4_core::role::SocietyRole;

/// On-disk delegation store — a JSON array of DelegatedAuthority.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct DelegationStore {
    pub delegations: Vec<DelegatedAuthority>,
}

impl DelegationStore {
    /// Load delegations from the vault (migrating a legacy `delegations.json`).
    pub fn load(vault: &crate::vault::Vault) -> Result<Self> {
        crate::vault::load_doc(vault, "presence", "delegations", "delegations.json")
    }

    /// Persist delegations as an encrypted vault document.
    pub fn save(&self, vault: &mut crate::vault::Vault) -> Result<()> {
        crate::vault::save_doc(vault, "presence", "delegations", "delegations.json", self)
    }

    pub fn create_delegation(
        &mut self,
        delegator_lct_id: Uuid,
        agent_lct_id: Uuid,
        roles: Vec<SocietyRole>,
        actions: Vec<String>,
        expires_hours: Option<u64>,
        delegator_keypair: &KeyPair,
    ) -> &DelegatedAuthority {
        let scope = if roles.is_empty() && actions.is_empty() {
            DelegationScope::unrestricted()
        } else {
            DelegationScope {
                roles,
                actions,
                society_lct_id: None,
            }
        };

        let expires_at =
            expires_hours.map(|h| chrono::Utc::now() + chrono::Duration::hours(h as i64));

        let deleg = DelegatedAuthority::create(
            delegator_lct_id,
            agent_lct_id,
            scope,
            expires_at,
            delegator_keypair,
        );

        self.delegations.push(deleg);
        self.delegations.last().unwrap()
    }

    pub fn revoke(&mut self, delegation_id: Uuid) -> Result<()> {
        let deleg = self
            .delegations
            .iter_mut()
            .find(|d| d.id == delegation_id)
            .ok_or_else(|| anyhow::anyhow!("delegation {} not found", delegation_id))?;
        deleg.revoke();
        Ok(())
    }

    pub fn active(&self) -> Vec<&DelegatedAuthority> {
        self.delegations.iter().filter(|d| d.is_active()).collect()
    }

    pub fn for_agent(&self, agent_lct_id: Uuid) -> Vec<&DelegatedAuthority> {
        self.delegations
            .iter()
            .filter(|d| d.agent_lct_id == agent_lct_id && d.is_active())
            .collect()
    }
}

/// Parse a role name string into a SocietyRole.
pub fn parse_role(s: &str) -> Result<SocietyRole> {
    match s.to_lowercase().as_str() {
        "sovereign" => Ok(SocietyRole::Sovereign),
        "laworacle" | "law_oracle" | "law-oracle" => Ok(SocietyRole::LawOracle),
        "policyentity" | "policy_entity" | "policy-entity" => Ok(SocietyRole::PolicyEntity),
        "treasurer" => Ok(SocietyRole::Treasurer),
        "administrator" | "admin" => Ok(SocietyRole::Administrator),
        "archivist" => Ok(SocietyRole::Archivist),
        "citizen" => Ok(SocietyRole::Citizen),
        "witness" => Ok(SocietyRole::Witness),
        "auditor" => Ok(SocietyRole::Auditor),
        other => Ok(SocietyRole::Custom(other.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_and_list() {
        let kp = KeyPair::generate();
        let delegator = Uuid::new_v4();
        let agent = Uuid::new_v4();

        let mut store = DelegationStore::default();
        store.create_delegation(
            delegator,
            agent,
            vec![SocietyRole::Administrator],
            vec![],
            None,
            &kp,
        );

        assert_eq!(store.delegations.len(), 1);
        assert_eq!(store.active().len(), 1);
        assert_eq!(store.for_agent(agent).len(), 1);
        assert_eq!(store.for_agent(Uuid::new_v4()).len(), 0);
    }

    #[test]
    fn test_revoke() {
        let kp = KeyPair::generate();
        let mut store = DelegationStore::default();
        store.create_delegation(Uuid::new_v4(), Uuid::new_v4(), vec![], vec![], None, &kp);

        let id = store.delegations[0].id;
        assert_eq!(store.active().len(), 1);

        store.revoke(id).unwrap();
        assert_eq!(store.active().len(), 0);
    }

    #[test]
    fn test_persistence_roundtrip() {
        let kp = KeyPair::generate();
        let mut store = DelegationStore::default();
        store.create_delegation(
            Uuid::new_v4(),
            Uuid::new_v4(),
            vec![SocietyRole::Witness],
            vec!["attest".into()],
            Some(24),
            &kp,
        );

        let json = serde_json::to_string(&store).unwrap();
        let recovered: DelegationStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.delegations.len(), 1);
        assert!(recovered.delegations[0].is_active());
    }
}
