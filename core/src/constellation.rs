//! Constellation manager — Hestia as a mini-hub for a person's devices.
//!
//! A constellation is a set of LCTs (devices, agents, identities) that belong
//! to the same person. The manager:
//! - Tracks paired devices with their capabilities and liveness
//! - Responds to witness requests by polling constellation members
//! - Provides constellation proofs (single-LCT vs verifiable multi-LCT)
//!   for the hub's assurance tiers
//!
//! The key insight: a person's device-constellation manager and a society hub
//! are the same thing at different scale. Both manage paired LCTs and answer
//! witness queries. This is the Web4 fractal/synthon at work.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use uuid::Uuid;
use web4_core::crypto::KeyPair;

use crate::plugin::{self, LctId, PluginCtx, PluginError, ToolPlugin, ToolScope};

/// A device/LCT in the constellation.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConstellationMember {
    pub lct_id: Uuid,
    pub name: String,
    pub device_type: DeviceType,
    pub pubkey_hex: String,
    pub added_at: DateTime<Utc>,
    pub last_seen: Option<DateTime<Utc>>,
    pub capabilities: Vec<String>,
    pub reachable: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceType {
    Desktop,
    Mobile,
    Server,
    Agent,
    Hardware,
}

/// Constellation proof — attestation that multiple LCTs belong to the same person.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConstellationProof {
    pub owner_lct_id: Uuid,
    pub members: Vec<Uuid>,
    pub member_count: usize,
    pub assurance_level: AssuranceLevel,
    pub issued_at: DateTime<Utc>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssuranceLevel {
    SingleDevice,
    MultiDevice,
    HardwareBacked,
}

/// Persistent constellation state.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct ConstellationStore {
    pub owner_lct_id: Option<Uuid>,
    pub members: Vec<ConstellationMember>,
}

impl ConstellationStore {
    pub fn path(hestia_home: &Path) -> PathBuf {
        hestia_home.join("constellation.json")
    }

    pub fn load(hestia_home: &Path) -> anyhow::Result<Self> {
        let path = Self::path(hestia_home);
        if !path.exists() {
            return Ok(Self::default());
        }
        let data = std::fs::read_to_string(&path)?;
        Ok(serde_json::from_str(&data)?)
    }

    pub fn save(&self, hestia_home: &Path) -> anyhow::Result<()> {
        let path = Self::path(hestia_home);
        let data = serde_json::to_string_pretty(self)?;
        std::fs::write(&path, data)?;
        Ok(())
    }

    pub fn add_device(
        &mut self,
        name: &str,
        device_type: DeviceType,
        pubkey_hex: &str,
        capabilities: Vec<String>,
    ) -> &ConstellationMember {
        let member = ConstellationMember {
            lct_id: Uuid::new_v4(),
            name: name.to_string(),
            device_type,
            pubkey_hex: pubkey_hex.to_string(),
            added_at: Utc::now(),
            last_seen: None,
            capabilities,
            reachable: false,
        };
        self.members.push(member);
        self.members.last().unwrap()
    }

    pub fn remove_device(&mut self, lct_id: Uuid) -> bool {
        let len_before = self.members.len();
        self.members.retain(|m| m.lct_id != lct_id);
        self.members.len() < len_before
    }

    pub fn proof(&self) -> ConstellationProof {
        let member_ids: Vec<Uuid> = self.members.iter().map(|m| m.lct_id).collect();
        let has_hardware = self.members.iter().any(|m| m.device_type == DeviceType::Hardware);
        let assurance = if has_hardware {
            AssuranceLevel::HardwareBacked
        } else if self.members.len() > 1 {
            AssuranceLevel::MultiDevice
        } else {
            AssuranceLevel::SingleDevice
        };

        ConstellationProof {
            owner_lct_id: self.owner_lct_id.unwrap_or(Uuid::nil()),
            members: member_ids.clone(),
            member_count: member_ids.len(),
            assurance_level: assurance,
            issued_at: Utc::now(),
        }
    }

    pub fn reachable_count(&self) -> usize {
        self.members.iter().filter(|m| m.reachable).count()
    }
}

/// The constellation plugin — registers as a tool in Hestia's plugin registry.
/// Responds to `constellation_proof` and `constellation_status` queries.
pub struct ConstellationPlugin {
    home: PathBuf,
}

impl ConstellationPlugin {
    pub fn new(home: PathBuf) -> Self {
        Self { home }
    }
}

#[async_trait::async_trait]
impl ToolPlugin for ConstellationPlugin {
    fn name(&self) -> &str {
        "constellation"
    }

    fn scope(&self) -> ToolScope {
        ToolScope::Unbounded
    }

    async fn handle(
        &self,
        _ctx: &dyn PluginCtx,
        args: &serde_json::Value,
    ) -> Result<serde_json::Value, PluginError> {
        let action = args.get("action").and_then(|v| v.as_str()).unwrap_or("status");

        let store = ConstellationStore::load(&self.home)
            .map_err(|e| PluginError::Internal(e.to_string()))?;

        match action {
            "proof" => {
                let proof = store.proof();
                serde_json::to_value(&proof)
                    .map_err(|e| PluginError::Internal(e.to_string()))
            }
            "status" => {
                Ok(serde_json::json!({
                    "owner_lct_id": store.owner_lct_id,
                    "member_count": store.members.len(),
                    "reachable": store.reachable_count(),
                    "devices": store.members.iter().map(|m| serde_json::json!({
                        "lct_id": m.lct_id,
                        "name": m.name,
                        "type": m.device_type,
                        "reachable": m.reachable,
                        "last_seen": m.last_seen,
                    })).collect::<Vec<_>>(),
                }))
            }
            other => Err(PluginError::BadRequest(format!("unknown action: {other}"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add_and_remove_device() {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());

        let kp = KeyPair::generate();
        store.add_device("Legion Desktop", DeviceType::Desktop, &kp.verifying_key().to_hex(), vec!["sign".into()]);
        store.add_device("Phone", DeviceType::Mobile, &kp.verifying_key().to_hex(), vec!["approve".into()]);

        assert_eq!(store.members.len(), 2);

        let proof = store.proof();
        assert_eq!(proof.member_count, 2);
        assert_eq!(proof.assurance_level, AssuranceLevel::MultiDevice);

        let phone_id = store.members[1].lct_id;
        assert!(store.remove_device(phone_id));
        assert_eq!(store.members.len(), 1);
        assert_eq!(store.proof().assurance_level, AssuranceLevel::SingleDevice);
    }

    #[test]
    fn test_hardware_assurance() {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());

        let kp = KeyPair::generate();
        store.add_device("Desktop", DeviceType::Desktop, &kp.verifying_key().to_hex(), vec![]);
        store.add_device("YubiKey", DeviceType::Hardware, &kp.verifying_key().to_hex(), vec!["attest".into()]);

        assert_eq!(store.proof().assurance_level, AssuranceLevel::HardwareBacked);
    }

    #[test]
    fn test_serialization_roundtrip() {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());
        let kp = KeyPair::generate();
        store.add_device("Test", DeviceType::Server, &kp.verifying_key().to_hex(), vec!["api".into()]);

        let json = serde_json::to_string(&store).unwrap();
        let recovered: ConstellationStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.members.len(), 1);
        assert_eq!(recovered.members[0].name, "Test");
    }

    #[test]
    fn test_empty_constellation() {
        let store = ConstellationStore::default();
        let proof = store.proof();
        assert_eq!(proof.member_count, 0);
        assert_eq!(proof.assurance_level, AssuranceLevel::SingleDevice);
    }
}
