//! Constellation manager — a person's set of paired device LCTs.
//!
//! A constellation is a set of LCTs (devices, agents, identities) that belong
//! to the same person. The manager:
//! - Tracks paired devices with their capabilities and liveness
//! - Produces a `ConstellationProof` (single-device / multi-device /
//!   hardware-backed) summarizing the set
//! - Produces a challenge-bound `ConstellationAttestation` — a standard
//!   challenge-response multi-factor proof (owner + per-device co-signatures
//!   over a verifier-supplied nonce) for assurance-tier resolution at a hub.

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

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssuranceLevel {
    SingleDevice,
    MultiDevice,
    HardwareBacked,
}

/// A challenge-bound, signed constellation attestation — what gets presented
/// to a hub at channel establishment for assurance-tier resolution (MFA).
///
/// Unlike `ConstellationProof` (an unsigned local snapshot), an attestation
/// is bound to a hub-supplied challenge nonce and carries signatures proving
/// key possession *at challenge time*:
/// - The **owner** signs the member list + nonce (binds the roster).
/// - Each reachable **device** co-signs the same payload (proves possession).
///
/// The verifier MUST recompute the assurance level from verified co-signatures
/// rather than trusting `claimed_assurance`:
/// - 0–1 verified device sigs → `SingleDevice`
/// - 2+ verified device sigs → `MultiDevice`
/// - any verified co-sign from a `hardware` device → `HardwareBacked`
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConstellationAttestation {
    pub owner_lct_id: Uuid,
    pub owner_pubkey_hex: String,
    pub member_lcts: Vec<Uuid>,
    pub challenge_nonce: String,
    pub issued_at: DateTime<Utc>,
    pub claimed_assurance: AssuranceLevel,
    /// Owner's Ed25519 signature over `signing_payload()`, hex.
    pub owner_signature: String,
    /// Co-signatures from devices that demonstrated key possession.
    pub device_signatures: Vec<DeviceSignature>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DeviceSignature {
    pub lct_id: Uuid,
    pub device_type: DeviceType,
    pub pubkey_hex: String,
    /// Ed25519 signature over the same `signing_payload()`, hex.
    pub signature: String,
}

impl ConstellationAttestation {
    /// Deterministic signing payload — version-prefixed, SHA-256.
    /// Both owner and device signatures cover this same payload, so a
    /// device co-sign also binds the roster + nonce it vouched for.
    pub fn signing_payload(
        owner: Uuid,
        members: &[Uuid],
        nonce: &str,
        issued_at: &DateTime<Utc>,
    ) -> Vec<u8> {
        let mut buf = Vec::with_capacity(128);
        buf.extend_from_slice(b"web4:constellation-attest:v1:");
        buf.extend_from_slice(owner.as_bytes());
        buf.extend_from_slice(nonce.as_bytes());
        buf.extend_from_slice(issued_at.to_rfc3339().as_bytes());
        for m in members {
            buf.extend_from_slice(m.as_bytes());
        }
        web4_core::crypto::sha256(&buf).to_vec()
    }

    /// Create and sign an attestation. `device_keys` supplies keypairs for
    /// devices able to co-sign right now (loaded from the vault — secrets
    /// never live in constellation.json). Devices without keys are listed
    /// in the roster but add no assurance.
    pub fn create(
        store: &ConstellationStore,
        owner_keypair: &KeyPair,
        challenge_nonce: &str,
        device_keys: &[(Uuid, KeyPair)],
    ) -> anyhow::Result<Self> {
        let owner = store.owner_lct_id
            .ok_or_else(|| anyhow::anyhow!("constellation has no owner LCT — add a device first"))?;
        let members: Vec<Uuid> = store.members.iter().map(|m| m.lct_id).collect();
        let issued_at = Utc::now();

        let payload = Self::signing_payload(owner, &members, challenge_nonce, &issued_at);
        let owner_signature = owner_keypair.sign(&payload).to_hex();

        let mut device_signatures = Vec::new();
        for (lct_id, kp) in device_keys {
            let Some(member) = store.members.iter().find(|m| m.lct_id == *lct_id) else {
                anyhow::bail!("device {lct_id} not in constellation");
            };
            // The co-signing key must be the key registered for this device.
            if kp.verifying_key().to_hex() != member.pubkey_hex {
                anyhow::bail!("key for device {lct_id} does not match registered pubkey");
            }
            device_signatures.push(DeviceSignature {
                lct_id: *lct_id,
                device_type: member.device_type.clone(),
                pubkey_hex: member.pubkey_hex.clone(),
                signature: kp.sign(&payload).to_hex(),
            });
        }

        let claimed_assurance = Self::derive_assurance(&device_signatures);

        Ok(Self {
            owner_lct_id: owner,
            owner_pubkey_hex: owner_keypair.verifying_key().to_hex(),
            member_lcts: members,
            challenge_nonce: challenge_nonce.to_string(),
            issued_at,
            claimed_assurance,
            owner_signature,
            device_signatures,
        })
    }

    /// Verify the attestation against an expected nonce and max age.
    /// Returns the assurance level **derived from verified signatures** —
    /// the verifier never trusts `claimed_assurance`.
    pub fn verify(
        &self,
        expected_nonce: &str,
        max_age: chrono::Duration,
    ) -> anyhow::Result<AssuranceLevel> {
        if self.challenge_nonce != expected_nonce {
            anyhow::bail!("nonce mismatch — possible replay");
        }
        if Utc::now() - self.issued_at > max_age {
            anyhow::bail!("attestation expired");
        }

        let payload = Self::signing_payload(
            self.owner_lct_id,
            &self.member_lcts,
            &self.challenge_nonce,
            &self.issued_at,
        );

        let owner_pk = pubkey_from_hex(&self.owner_pubkey_hex)?;
        let owner_sig = sig_from_hex(&self.owner_signature)?;
        owner_pk.verify(&payload, &owner_sig)
            .map_err(|_| anyhow::anyhow!("owner signature invalid"))?;

        let mut verified = Vec::new();
        for ds in &self.device_signatures {
            if !self.member_lcts.contains(&ds.lct_id) {
                continue; // co-sign from a non-roster device adds nothing
            }
            let pk = pubkey_from_hex(&ds.pubkey_hex)?;
            let sig = sig_from_hex(&ds.signature)?;
            if pk.verify(&payload, &sig).is_ok() {
                verified.push(ds);
            }
        }

        Ok(Self::derive_assurance_refs(&verified))
    }

    fn derive_assurance(sigs: &[DeviceSignature]) -> AssuranceLevel {
        let refs: Vec<&DeviceSignature> = sigs.iter().collect();
        Self::derive_assurance_refs(&refs)
    }

    fn derive_assurance_refs(verified: &[&DeviceSignature]) -> AssuranceLevel {
        if verified.iter().any(|s| s.device_type == DeviceType::Hardware) {
            AssuranceLevel::HardwareBacked
        } else if verified.len() >= 2 {
            AssuranceLevel::MultiDevice
        } else {
            AssuranceLevel::SingleDevice
        }
    }
}

fn pubkey_from_hex(hex_str: &str) -> anyhow::Result<web4_core::crypto::PublicKey> {
    let bytes = hex::decode(hex_str)?;
    let arr: [u8; 32] = bytes.as_slice().try_into()
        .map_err(|_| anyhow::anyhow!("pubkey must be 32 bytes"))?;
    Ok(web4_core::crypto::PublicKey::from_bytes(&arr)?)
}

fn sig_from_hex(hex_str: &str) -> anyhow::Result<web4_core::crypto::SignatureBytes> {
    let bytes = hex::decode(hex_str)?;
    let arr: [u8; 64] = bytes.as_slice().try_into()
        .map_err(|_| anyhow::anyhow!("signature must be 64 bytes"))?;
    Ok(web4_core::crypto::SignatureBytes::from_bytes(arr))
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

    fn store_with_keys(types: &[(&str, DeviceType)]) -> (ConstellationStore, Vec<(Uuid, KeyPair)>) {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());
        let mut keys = Vec::new();
        for (name, dt) in types {
            let kp = KeyPair::generate();
            let id = store.add_device(name, dt.clone(), &kp.verifying_key().to_hex(), vec![]).lct_id;
            keys.push((id, kp));
        }
        (store, keys)
    }

    #[test]
    fn test_attestation_multi_device_verifies() {
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();

        let att = ConstellationAttestation::create(&store, &owner_kp, "hub-nonce-123", &keys).unwrap();
        assert_eq!(att.claimed_assurance, AssuranceLevel::MultiDevice);

        let level = att.verify("hub-nonce-123", chrono::Duration::minutes(5)).unwrap();
        assert_eq!(level, AssuranceLevel::MultiDevice);
    }

    #[test]
    fn test_attestation_hardware_backed() {
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("YubiKey", DeviceType::Hardware),
        ]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        let level = att.verify("n", chrono::Duration::minutes(5)).unwrap();
        assert_eq!(level, AssuranceLevel::HardwareBacked);
    }

    #[test]
    fn test_attestation_wrong_nonce_rejected() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "nonce-a", &keys).unwrap();
        assert!(att.verify("nonce-b", chrono::Duration::minutes(5)).is_err());
    }

    #[test]
    fn test_attestation_tampered_roster_rejected() {
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        att.member_lcts.push(Uuid::new_v4()); // inject a phantom device
        assert!(att.verify("n", chrono::Duration::minutes(5)).is_err());
    }

    #[test]
    fn test_verifier_ignores_claimed_assurance() {
        // Roster has 2 devices but only 1 co-signs → verifier must derive
        // SingleDevice even if the claim were inflated.
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();
        let one_key = vec![(keys[0].0, KeyPair::from_secret_bytes(&keys[0].1.secret_key_bytes()))];
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &one_key).unwrap();
        att.claimed_assurance = AssuranceLevel::HardwareBacked; // lie

        let level = att.verify("n", chrono::Duration::minutes(5)).unwrap();
        assert_eq!(level, AssuranceLevel::SingleDevice);
    }

    #[test]
    fn test_attestation_wrong_device_key_rejected_at_create() {
        let (store, _) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let wrong_kp = KeyPair::generate();
        let device_id = store.members[0].lct_id;
        let result = ConstellationAttestation::create(
            &store, &owner_kp, "n", &[(device_id, wrong_kp)],
        );
        assert!(result.is_err());
    }
}
