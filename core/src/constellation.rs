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
use std::path::PathBuf;
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
    /// Transient liveness — MUST NOT determine whether a key is authorized
    /// (that's `status`). Excluded from the canonical roster hash.
    pub reachable: bool,
    /// Enrollment status — the authoritative gate on whether this device may
    /// contribute assurance. A `Revoked`/`Suspended` device contributes NONE
    /// even if it can still sign (GPT constellation-assurance report, 2026-07-18).
    /// `#[serde(default)]` migrates pre-status `constellation.json` to `Active`.
    #[serde(default)]
    pub status: DeviceStatus,
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

/// Whether an enrolled device's key is currently authorized to contribute
/// assurance. Distinct from `reachable` (liveness): a revoked device may still
/// be reachable and able to sign, but must never count.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceStatus {
    #[default]
    Active,
    Suspended,
    Revoked,
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
/// **Trust model (GPT constellation-assurance report, 2026-07-18):** the fields
/// this attestation carries — `owner_pubkey_hex`, each `DeviceSignature`'s
/// `pubkey_hex` and `device_type` — are the PRESENTER'S CLAIMS, never authority.
/// A relying party MUST resolve every device fact (key, class, enrollment status)
/// from committed state and recompute the tier via [`Self::verify_against_store`].
/// (The old presented-key verifier is retired to `#[cfg(test)]` — a production
/// caller can't even name it.) Otherwise the owner-key holder can mint fresh keys,
/// label them `Hardware`, and self-authenticate an inflated tier.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConstellationAttestation {
    pub owner_lct_id: Uuid,
    /// PRESENTER'S CLAIM — never trusted for authorization. `verify_against_store`
    /// checks the owner signature against the caller-supplied trusted key instead.
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
        let owner = store.owner_lct_id.ok_or_else(|| {
            anyhow::anyhow!("constellation has no owner LCT — add a device first")
        })?;
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

    /// **Internal-consistency check only — establishes NO identity or assurance.**
    ///
    /// This proves *only* that the keys carried INSIDE the attestation signed the
    /// payload for the given nonce. It resolves nothing from trusted state, so it
    /// MUST NOT be used as an authentication or assurance verifier — an attacker
    /// who controls the owner key can mint fresh keypairs, label them `Hardware`,
    /// sign, and self-authenticate (GPT constellation-assurance report, 2026-07-18,
    /// findings #1/#2/#4). Use [`Self::verify_against_store`] for any decision.
    /// Kept for the create/self-test path and to detect a malformed attestation.
    ///
    /// Returns the consistency-derived tier purely as a diagnostic; treat it as
    /// "the presenter's claim", never as a resolved fact.
    ///
    /// **RETIRED from the API (2026-07-21): `#[cfg(test)]`-only.** It exists solely
    /// to validate that `create()` produces well-formed, self-consistent
    /// attestations. Every decision path uses [`Self::verify_against_store`]; a
    /// production caller literally cannot compile against this, so it can never be
    /// mistaken for authentication.
    #[cfg(test)]
    pub fn verify_internal_consistency(
        &self,
        expected_nonce: &str,
        max_age: chrono::Duration,
    ) -> anyhow::Result<AssuranceLevel> {
        if self.challenge_nonce != expected_nonce {
            anyhow::bail!("nonce mismatch — possible replay");
        }
        Self::check_freshness(self.issued_at, max_age, chrono::Duration::minutes(2))?;

        let payload = Self::signing_payload(
            self.owner_lct_id,
            &self.member_lcts,
            &self.challenge_nonce,
            &self.issued_at,
        );

        let owner_pk = pubkey_from_hex(&self.owner_pubkey_hex)?;
        let owner_sig = sig_from_hex(&self.owner_signature)?;
        owner_pk
            .verify(&payload, &owner_sig)
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

    /// **The authoritative verifier.** Resolves every device fact — public key,
    /// device class, enrollment status — from `store` (committed BEFORE the
    /// challenge), NOT from the presented attestation. The presenter may identify
    /// a device and prove key possession; it is never authoritative for that
    /// device's key or classification. Closes GPT's findings #1–#4:
    ///
    /// - owner key must equal the caller-supplied trusted key (not `owner_pubkey_hex`);
    /// - each device signature is checked against the STORED pubkey;
    /// - device class (`Hardware`) comes from the STORED record;
    /// - only `Active` enrolled devices count; duplicates are collapsed by lct_id;
    /// - `issued_at` must be fresh AND not future-dated beyond `future_skew`.
    #[allow(clippy::too_many_arguments)]
    pub fn verify_against_store(
        &self,
        expected_owner_lct: Uuid,
        expected_owner_pubkey: &web4_core::crypto::PublicKey,
        expected_nonce: &str,
        store: &ConstellationStore,
        max_age: chrono::Duration,
        future_skew: chrono::Duration,
    ) -> anyhow::Result<AssuranceLevel> {
        if self.challenge_nonce != expected_nonce {
            anyhow::bail!("nonce mismatch — possible replay");
        }
        if self.owner_lct_id != expected_owner_lct {
            anyhow::bail!("owner LCT does not match the expected identity");
        }
        Self::check_freshness(self.issued_at, max_age, future_skew)?;

        let payload = Self::signing_payload(
            self.owner_lct_id,
            &self.member_lcts,
            &self.challenge_nonce,
            &self.issued_at,
        );

        // Owner: verify against the TRUSTED key, not the presented one.
        let owner_sig = sig_from_hex(&self.owner_signature)?;
        expected_owner_pubkey
            .verify(&payload, &owner_sig)
            .map_err(|_| {
                anyhow::anyhow!("owner signature invalid against the trusted owner key")
            })?;

        // Devices: resolve each fact from the store; collapse duplicate lct_ids.
        let mut seen = std::collections::HashSet::new();
        let mut verified: Vec<DeviceType> = Vec::new();
        for ds in &self.device_signatures {
            if !seen.insert(ds.lct_id) {
                continue; // duplicate signature entry — never inflates the count
            }
            let Some(member) = store.members.iter().find(|m| m.lct_id == ds.lct_id) else {
                continue; // not an enrolled device — presenter can't invent one
            };
            if member.status != DeviceStatus::Active {
                continue; // revoked/suspended keys contribute no assurance
            }
            // STORED key — the presented ds.pubkey_hex is ignored entirely.
            let pk = pubkey_from_hex(&member.pubkey_hex)?;
            let sig = sig_from_hex(&ds.signature)?;
            if pk.verify(&payload, &sig).is_ok() {
                // STORED class — the presented ds.device_type is ignored entirely.
                verified.push(member.device_type.clone());
            }
        }

        Ok(Self::derive_assurance_from_types(&verified))
    }

    /// Freshness gate closing GPT finding #5: reject stale AND future-dated
    /// attestations (a future `issued_at` yields a negative age that would slip a
    /// naive `age > max_age` test).
    fn check_freshness(
        issued_at: DateTime<Utc>,
        max_age: chrono::Duration,
        future_skew: chrono::Duration,
    ) -> anyhow::Result<()> {
        let age = Utc::now() - issued_at;
        if age > max_age {
            anyhow::bail!("attestation expired");
        }
        if age < -future_skew {
            anyhow::bail!("attestation is future-dated beyond allowed skew — rejected");
        }
        Ok(())
    }

    fn derive_assurance_from_types(types: &[DeviceType]) -> AssuranceLevel {
        if types.iter().any(|t| *t == DeviceType::Hardware) {
            AssuranceLevel::HardwareBacked
        } else if types.len() >= 2 {
            AssuranceLevel::MultiDevice
        } else {
            AssuranceLevel::SingleDevice
        }
    }

    fn derive_assurance(sigs: &[DeviceSignature]) -> AssuranceLevel {
        let refs: Vec<&DeviceSignature> = sigs.iter().collect();
        Self::derive_assurance_refs(&refs)
    }

    fn derive_assurance_refs(verified: &[&DeviceSignature]) -> AssuranceLevel {
        if verified
            .iter()
            .any(|s| s.device_type == DeviceType::Hardware)
        {
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
    let arr: [u8; 32] = bytes
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("pubkey must be 32 bytes"))?;
    Ok(web4_core::crypto::PublicKey::from_bytes(&arr)?)
}

fn sig_from_hex(hex_str: &str) -> anyhow::Result<web4_core::crypto::SignatureBytes> {
    let bytes = hex::decode(hex_str)?;
    let arr: [u8; 64] = bytes
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("signature must be 64 bytes"))?;
    Ok(web4_core::crypto::SignatureBytes::from_bytes(arr))
}

/// Persistent constellation state.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct ConstellationStore {
    pub owner_lct_id: Option<Uuid>,
    pub members: Vec<ConstellationMember>,
    /// Owners this machine is willing to be an MFA factor FOR — the device-side
    /// inverse of `members`. `cosign` refuses any owner not listed here, so the
    /// list must be populated by an explicit local act (`constellation
    /// serve-owner`). Deliberately NOT derived from a confirmed pairing: a pair
    /// is a transport agreement, and today confirming one silently also means "I
    /// consent to be your second factor". `add-remote` makes naming an arbitrary
    /// confirmed peer a one-liner, which is what turns that conflation into a
    /// real gap. `#[serde(default)]` so existing vault documents load; an empty
    /// list means serve nobody, which is the fail-closed default we want.
    #[serde(default)]
    pub serve_owners: Vec<Uuid>,
}

impl ConstellationStore {
    /// Load the device constellation from the vault (migrating a legacy
    /// `constellation.json` for older installs).
    pub fn load(vault: &crate::vault::Vault) -> anyhow::Result<Self> {
        crate::vault::load_doc(vault, "presence", "constellation", "constellation.json")
    }

    /// Persist the constellation as an encrypted vault document.
    pub fn save(&self, vault: &mut crate::vault::Vault) -> anyhow::Result<()> {
        crate::vault::save_doc(
            vault,
            "presence",
            "constellation",
            "constellation.json",
            self,
        )
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
            status: DeviceStatus::Active,
        };
        self.members.push(member);
        self.members.last().unwrap()
    }

    /// Add a device whose key lives on ANOTHER machine, under the LCT that
    /// machine already answers as. Distinct from `add_device`, which mints a
    /// fresh `lct_id` and (at the CLI) a locally-custodied private key — both of
    /// which make `present --remote` take its local-signing branch and never
    /// reach the device. The remote co-sign path requires a member that carries
    /// the peer's REAL lct_id and has no local key, so the id is caller-supplied
    /// here rather than generated.
    ///
    /// Rejects a duplicate id: unlike a minted UUID, `lct_id` is caller-supplied
    /// and a second entry for one device would put it in the roster twice, which
    /// changes the canonical roster hash every peer signs over.
    pub fn add_remote_device(
        &mut self,
        lct_id: Uuid,
        name: &str,
        device_type: DeviceType,
        pubkey_hex: &str,
        capabilities: Vec<String>,
    ) -> anyhow::Result<&ConstellationMember> {
        if let Some(existing) = self.members.iter().find(|m| m.lct_id == lct_id) {
            anyhow::bail!(
                "device {lct_id} is already in the constellation as {:?} — \
                 `constellation remove {lct_id}` first if you mean to re-add it",
                existing.name
            );
        }
        let member = ConstellationMember {
            lct_id,
            name: name.to_string(),
            device_type,
            pubkey_hex: pubkey_hex.to_string(),
            added_at: Utc::now(),
            last_seen: None,
            capabilities,
            reachable: false,
            status: DeviceStatus::Active,
        };
        self.members.push(member);
        Ok(self.members.last().unwrap())
    }

    /// Consent to act as an MFA factor for `owner`. Returns false if already
    /// listed (idempotent, not an error — re-running the command is harmless).
    pub fn allow_owner(&mut self, owner: Uuid) -> bool {
        if self.serve_owners.contains(&owner) {
            return false;
        }
        self.serve_owners.push(owner);
        true
    }

    /// Withdraw consent for `owner`. Returns false if they weren't listed.
    /// Withdrawal takes effect at the next `cosign` — a running `cosign-serve`
    /// reloads the store each pass, so it does not need restarting.
    pub fn disallow_owner(&mut self, owner: Uuid) -> bool {
        let before = self.serve_owners.len();
        self.serve_owners.retain(|o| *o != owner);
        self.serve_owners.len() != before
    }

    /// Set a device's enrollment status. Revoking is the authoritative way to
    /// stop a device contributing assurance (a revoked key that can still sign
    /// must never count). Returns false if the device isn't in the roster.
    pub fn set_device_status(&mut self, lct_id: Uuid, status: DeviceStatus) -> bool {
        match self.members.iter_mut().find(|m| m.lct_id == lct_id) {
            Some(m) => {
                m.status = status;
                true
            }
            None => false,
        }
    }

    /// Canonical roster hash — a stable, cross-implementation digest of the
    /// *authoritative* enrollment (lct + pubkey + type + status), used to bind
    /// an attestation to a committed roster. Dedup + sort by lct bytes + pinned
    /// encoding; EXCLUDES mutable presentation fields (`last_seen`, `reachable`,
    /// `name`, `capabilities`) so liveness churn doesn't change identity.
    pub fn canonical_roster_hash(&self) -> [u8; 32] {
        let mut rows: Vec<&ConstellationMember> = self.members.iter().collect();
        rows.sort_by(|a, b| a.lct_id.as_bytes().cmp(b.lct_id.as_bytes()));
        rows.dedup_by(|a, b| a.lct_id == b.lct_id);
        let mut buf = Vec::with_capacity(64 + rows.len() * 96);
        buf.extend_from_slice(b"web4:constellation-roster:v2:");
        if let Some(owner) = self.owner_lct_id {
            buf.extend_from_slice(owner.as_bytes());
        }
        for m in rows {
            buf.extend_from_slice(m.lct_id.as_bytes());
            buf.extend_from_slice(m.pubkey_hex.as_bytes());
            // device_type + status via their serde tags (stable snake_case).
            buf.extend_from_slice(format!("{:?}", m.device_type).as_bytes());
            buf.extend_from_slice(format!("{:?}", m.status).as_bytes());
        }
        web4_core::crypto::sha256(&buf)
    }

    pub fn remove_device(&mut self, lct_id: Uuid) -> bool {
        let len_before = self.members.len();
        self.members.retain(|m| m.lct_id != lct_id);
        self.members.len() < len_before
    }

    pub fn proof(&self) -> ConstellationProof {
        let member_ids: Vec<Uuid> = self.members.iter().map(|m| m.lct_id).collect();
        let has_hardware = self
            .members
            .iter()
            .any(|m| m.device_type == DeviceType::Hardware);
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
        let action = args
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("status");

        let vault = crate::vault::open_with_env(&self.home)
            .map_err(|e| PluginError::Internal(e.to_string()))?;
        let store =
            ConstellationStore::load(&vault).map_err(|e| PluginError::Internal(e.to_string()))?;

        match action {
            "proof" => {
                let proof = store.proof();
                serde_json::to_value(&proof).map_err(|e| PluginError::Internal(e.to_string()))
            }
            "status" => Ok(serde_json::json!({
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
            })),
            other => Err(PluginError::BadRequest(format!("unknown action: {other}"))),
        }
    }
}

// ===========================================================================
// Cross-device co-signing (real multi-device MFA, 2026-07-24).
//
// A device in a person's constellation is a SEPARATE machine holding its OWN
// key. To present a multi-device attestation the owner must collect a signature
// over the challenge payload from each remote device. This is the device side:
// asked to co-sign, a device signs EXACTLY the constellation-challenge payload
// (never arbitrary bytes) with its member key and returns the signature. The
// owner assembles these into the attestation it presents.
// ===========================================================================

/// A request the owner sends a remote device: "co-sign this constellation
/// challenge." Carries exactly the inputs to `signing_payload` so the device can
/// reconstruct the SAME bytes the owner will present — it never receives raw
/// bytes to sign, only the structured challenge, which bounds what it will sign.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CosignRequest {
    pub kind: String, // always "constellation_cosign_request"
    /// The constellation owner (who is presenting). The device verifies it is a
    /// device of THIS owner before signing.
    pub owner_lct_id: Uuid,
    /// The full device roster the owner will present (binds the co-sign to it).
    pub roster: Vec<Uuid>,
    /// The hub-issued challenge nonce this attestation answers.
    pub challenge_nonce: String,
    /// The attestation's `issued_at` — the device checks freshness before signing.
    pub issued_at: DateTime<Utc>,
    /// This device's own LCT id (so the device confirms it's being asked as itself).
    pub device_lct_id: Uuid,
}

/// A device's answer: its signature over the challenge payload. The owner drops
/// it into the attestation's `device_signatures`; the hub verifies it against the
/// device's ENROLLED key (so a forged sig or unenrolled device still counts for
/// nothing — the enrollment fix does the real gating).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CosignResponse {
    pub kind: String, // always "constellation_cosign_response"
    pub device_lct_id: Uuid,
    /// The device's Ed25519 signature over `signing_payload(...)`, hex.
    pub signature: String,
    /// The device's public key (hex). The HUB resolves the real key from enrollment
    /// and ignores this; the OWNER checks it against the roster pin before assembling
    /// the attestation — see [`CosignResponse::check_device_pubkey`].
    pub device_pubkey_hex: String,
}

impl CosignRequest {
    pub const KIND: &'static str = "constellation_cosign_request";

    pub fn new(owner_lct_id: Uuid, roster: Vec<Uuid>, challenge_nonce: String, issued_at: DateTime<Utc>, device_lct_id: Uuid) -> Self {
        Self { kind: Self::KIND.to_string(), owner_lct_id, roster, challenge_nonce, issued_at, device_lct_id }
    }

    /// The device co-signs. Verifies the request comes from an owner this machine
    /// has CONSENTED to serve, is a well-formed constellation challenge addressed
    /// to THIS device, and is fresh (never sign a stale or future-dated challenge),
    /// then signs EXACTLY the `signing_payload` bytes with `device_key`. Returns
    /// the response the owner assembles. Bounded surface: the device only ever
    /// signs the deterministic challenge payload, not caller bytes.
    ///
    /// `allowed_owners` is [`ConstellationStore::serve_owners`]. It is a parameter
    /// rather than a check in `cosign-serve`'s drain loop on purpose: this is where
    /// the other guards live, so a second caller of `cosign` cannot acquire the
    /// signing power without also passing the consent list. An empty slice refuses
    /// everything — fail closed.
    pub fn cosign(
        &self,
        device_lct_id: Uuid,
        device_key: &KeyPair,
        allowed_owners: &[Uuid],
        max_age: chrono::Duration,
        future_skew: chrono::Duration,
        now: DateTime<Utc>,
    ) -> anyhow::Result<CosignResponse> {
        if self.kind != Self::KIND {
            anyhow::bail!("not a cosign request (kind '{}')", self.kind);
        }
        if !allowed_owners.contains(&self.owner_lct_id) {
            anyhow::bail!(
                "owner {} is not on this device's serve-owners list — refusing to be \
                 their MFA factor. A confirmed pairing is transport, not consent; run \
                 `hestia constellation serve-owner {}` here to opt in",
                self.owner_lct_id, self.owner_lct_id,
            );
        }
        if self.device_lct_id != device_lct_id {
            anyhow::bail!("cosign request addressed to {}, not this device {}", self.device_lct_id, device_lct_id);
        }
        if !self.roster.contains(&device_lct_id) {
            anyhow::bail!("this device is not in the presented roster — refusing to co-sign");
        }
        let age = now - self.issued_at;
        if age > max_age {
            anyhow::bail!("challenge is stale (age exceeds max_age) — refusing to co-sign");
        }
        if age < -future_skew {
            anyhow::bail!("challenge is future-dated beyond skew — refusing to co-sign");
        }
        let payload = ConstellationAttestation::signing_payload(
            self.owner_lct_id, &self.roster, &self.challenge_nonce, &self.issued_at,
        );
        Ok(CosignResponse {
            kind: CosignResponse::KIND.to_string(),
            device_lct_id,
            signature: device_key.sign(&payload).to_hex(),
            device_pubkey_hex: device_key.verifying_key().to_hex(),
        })
    }
}

impl CosignResponse {
    pub const KIND: &'static str = "constellation_cosign_response";

    /// The owner-side sanity check the field's doc comment promises. The key the
    /// responder signed with must be the key the roster entry pins — for a remote
    /// member, the one `add-remote` resolved from the hub. They are equal by
    /// construction (`cosign-serve` signs with the member key the hub pinned), so a
    /// mismatch means the peer's local `member_key_source` has drifted from the pin
    /// — `hub set-member-key --channel-key` re-points the local signer without
    /// re-pinning anything at the hub. Hub-side that surfaces as an opaque
    /// verification reject; caught here it names the cause.
    pub fn check_device_pubkey(&self, expected_hex: &str) -> anyhow::Result<()> {
        if !self.device_pubkey_hex.eq_ignore_ascii_case(expected_hex) {
            anyhow::bail!(
                "device {} co-signed with pubkey {} but the roster pins {} — the peer's \
                 member key no longer matches the hub's pin (see `hub set-member-key`); \
                 refusing to submit a signature the hub will reject",
                self.device_lct_id, self.device_pubkey_hex, expected_hex,
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The whole point of `add_remote_device`: the roster entry must carry the
    /// PEER's id verbatim. `present --remote` addresses the co-sign request to
    /// `m.lct_id` and the peer bails unless it equals its own member LCT, so a
    /// minted id (what `add_device` does) can never reach another machine.
    #[test]
    fn test_add_remote_device_preserves_peer_lct() {
        let mut store = ConstellationStore::default();
        let peer = Uuid::new_v4();
        let kp = KeyPair::generate();

        let m = store
            .add_remote_device(peer, "Thor", DeviceType::Server, &kp.verifying_key().to_hex(), vec![])
            .expect("first add of a peer succeeds");
        assert_eq!(m.lct_id, peer, "remote member must keep the peer's own LCT");

        // add_device mints instead — the contrast this command exists to fix.
        store.add_device("Local", DeviceType::Desktop, &kp.verifying_key().to_hex(), vec![]);
        assert_ne!(store.members[1].lct_id, peer);
    }

    /// A caller-supplied id can collide; a minted one cannot. Two entries for one
    /// device would change the canonical roster hash every peer signs over.
    #[test]
    fn test_add_remote_device_rejects_duplicate() {
        let mut store = ConstellationStore::default();
        let peer = Uuid::new_v4();
        let kp = KeyPair::generate();
        let pk = kp.verifying_key().to_hex();

        store.add_remote_device(peer, "Thor", DeviceType::Server, &pk, vec![]).unwrap();
        let again = store.add_remote_device(peer, "Thor again", DeviceType::Server, &pk, vec![]);

        assert!(again.is_err(), "re-adding the same peer must be refused");
        assert_eq!(store.members.len(), 1, "roster must not grow on a refused add");
    }

    #[test]
    fn test_add_and_remove_device() {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());

        let kp = KeyPair::generate();
        store.add_device(
            "Legion Desktop",
            DeviceType::Desktop,
            &kp.verifying_key().to_hex(),
            vec!["sign".into()],
        );
        store.add_device(
            "Phone",
            DeviceType::Mobile,
            &kp.verifying_key().to_hex(),
            vec!["approve".into()],
        );

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
        store.add_device(
            "Desktop",
            DeviceType::Desktop,
            &kp.verifying_key().to_hex(),
            vec![],
        );
        store.add_device(
            "YubiKey",
            DeviceType::Hardware,
            &kp.verifying_key().to_hex(),
            vec!["attest".into()],
        );

        assert_eq!(
            store.proof().assurance_level,
            AssuranceLevel::HardwareBacked
        );
    }

    #[test]
    fn test_serialization_roundtrip() {
        let mut store = ConstellationStore::default();
        store.owner_lct_id = Some(Uuid::new_v4());
        let kp = KeyPair::generate();
        store.add_device(
            "Test",
            DeviceType::Server,
            &kp.verifying_key().to_hex(),
            vec!["api".into()],
        );

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
            let id = store
                .add_device(name, dt.clone(), &kp.verifying_key().to_hex(), vec![])
                .lct_id;
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

        let att =
            ConstellationAttestation::create(&store, &owner_kp, "hub-nonce-123", &keys).unwrap();
        assert_eq!(att.claimed_assurance, AssuranceLevel::MultiDevice);

        let level = att
            .verify_internal_consistency("hub-nonce-123", chrono::Duration::minutes(5))
            .unwrap();
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
        let level = att
            .verify_internal_consistency("n", chrono::Duration::minutes(5))
            .unwrap();
        assert_eq!(level, AssuranceLevel::HardwareBacked);
    }

    #[test]
    fn test_attestation_wrong_nonce_rejected() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "nonce-a", &keys).unwrap();
        assert!(
            att.verify_internal_consistency("nonce-b", chrono::Duration::minutes(5))
                .is_err()
        );
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
        assert!(
            att.verify_internal_consistency("n", chrono::Duration::minutes(5))
                .is_err()
        );
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
        let one_key = vec![(
            keys[0].0,
            KeyPair::from_secret_bytes(&keys[0].1.secret_key_bytes()),
        )];
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &one_key).unwrap();
        att.claimed_assurance = AssuranceLevel::HardwareBacked; // lie

        let level = att
            .verify_internal_consistency("n", chrono::Duration::minutes(5))
            .unwrap();
        assert_eq!(level, AssuranceLevel::SingleDevice);
    }

    #[test]
    fn test_attestation_wrong_device_key_rejected_at_create() {
        let (store, _) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let wrong_kp = KeyPair::generate();
        let device_id = store.members[0].lct_id;
        let result =
            ConstellationAttestation::create(&store, &owner_kp, "n", &[(device_id, wrong_kp)]);
        assert!(result.is_err());
    }

    // ---- verify_against_store: GPT's exploit scenarios must now FAIL ----

    const SKEW: chrono::Duration = chrono::Duration::minutes(2);
    fn max_age() -> chrono::Duration {
        chrono::Duration::minutes(5)
    }

    /// Baseline: a legit attestation verifies against the store, deriving the
    /// tier from STORED facts.
    #[test]
    fn store_verifier_accepts_a_legit_attestation() {
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(level, AssuranceLevel::MultiDevice);
    }

    /// GPT #1: forged hardware. The store device is Desktop; the attacker mints a
    /// fresh key, invents a device id, labels it Hardware, and co-signs. The store
    /// verifier resolves type+key from the store, so the phantom is ignored and
    /// the tier is NOT HardwareBacked.
    #[test]
    fn store_verifier_rejects_forged_hardware() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        // Attacker appends a phantom "Hardware" device signed by a brand-new key.
        let phantom_id = Uuid::new_v4();
        let phantom_kp = KeyPair::generate();
        let payload = ConstellationAttestation::signing_payload(
            att.owner_lct_id,
            &att.member_lcts,
            &att.challenge_nonce,
            &att.issued_at,
        );
        att.member_lcts.push(phantom_id);
        att.device_signatures.push(DeviceSignature {
            lct_id: phantom_id,
            device_type: DeviceType::Hardware,
            pubkey_hex: phantom_kp.verifying_key().to_hex(),
            signature: phantom_kp.sign(&payload).to_hex(),
        });
        // Re-sign the owner over the tampered roster so the owner check passes —
        // proving the DEFENSE is the store resolution, not the owner sig.
        att.owner_signature = owner_kp
            .sign(&ConstellationAttestation::signing_payload(
                att.owner_lct_id,
                &att.member_lcts,
                &att.challenge_nonce,
                &att.issued_at,
            ))
            .to_hex();
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(
            level,
            AssuranceLevel::SingleDevice,
            "phantom Hardware must not count"
        );
    }

    /// GPT #2: forged multi-device via a device id that isn't enrolled — ignored.
    #[test]
    fn store_verifier_rejects_unenrolled_device() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        let ghost = Uuid::new_v4();
        let ghost_kp = KeyPair::generate();
        let payload = ConstellationAttestation::signing_payload(
            att.owner_lct_id,
            &att.member_lcts,
            &att.challenge_nonce,
            &att.issued_at,
        );
        att.device_signatures.push(DeviceSignature {
            lct_id: ghost,
            device_type: DeviceType::Desktop,
            pubkey_hex: ghost_kp.verifying_key().to_hex(),
            signature: ghost_kp.sign(&payload).to_hex(),
        });
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(
            level,
            AssuranceLevel::SingleDevice,
            "unenrolled device adds nothing"
        );
    }

    /// A revoked device contributes no assurance even though its key still signs.
    #[test]
    fn store_verifier_excludes_revoked_device() {
        let (mut store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        // Revoke the phone AFTER it co-signed — must drop to SingleDevice.
        assert!(store.set_device_status(keys[1].0, DeviceStatus::Revoked));
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(level, AssuranceLevel::SingleDevice);
    }

    /// A device signed with a key OTHER than its enrolled key is not counted.
    #[test]
    fn store_verifier_rejects_foreign_device_key() {
        let (store, keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        // Re-sign the phone's entry with a foreign key (its lct stays enrolled).
        let foreign = KeyPair::generate();
        let payload = ConstellationAttestation::signing_payload(
            att.owner_lct_id,
            &att.member_lcts,
            &att.challenge_nonce,
            &att.issued_at,
        );
        let phone = att
            .device_signatures
            .iter_mut()
            .find(|d| d.lct_id == keys[1].0)
            .unwrap();
        phone.signature = foreign.sign(&payload).to_hex();
        phone.pubkey_hex = foreign.verifying_key().to_hex(); // even lying about the key
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(
            level,
            AssuranceLevel::SingleDevice,
            "foreign key fails against the stored key"
        );
    }

    /// GPT #3: duplicate signature entries never inflate the count.
    #[test]
    fn store_verifier_collapses_duplicate_signatures() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        let dup = att.device_signatures[0].clone();
        att.device_signatures.push(dup); // same lct_id twice
        let level = att
            .verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .unwrap();
        assert_eq!(
            level,
            AssuranceLevel::SingleDevice,
            "one device, duplicated, is still one"
        );
    }

    /// GPT #4: the owner key must match the TRUSTED key, not the presented one.
    #[test]
    fn store_verifier_rejects_wrong_owner_key() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        let attacker = KeyPair::generate();
        assert!(
            att.verify_against_store(
                store.owner_lct_id.unwrap(),
                &attacker.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .is_err(),
            "a non-owner trusted key must reject"
        );
    }

    /// GPT #5: a future-dated attestation (negative age) is rejected.
    #[test]
    fn store_verifier_rejects_future_dated() {
        let (store, keys) = store_with_keys(&[("Desktop", DeviceType::Desktop)]);
        let owner_kp = KeyPair::generate();
        let mut att = ConstellationAttestation::create(&store, &owner_kp, "n", &keys).unwrap();
        att.issued_at = Utc::now() + chrono::Duration::hours(1);
        // Re-sign owner over the new issued_at so only the freshness gate can fire.
        att.owner_signature = owner_kp
            .sign(&ConstellationAttestation::signing_payload(
                att.owner_lct_id,
                &att.member_lcts,
                &att.challenge_nonce,
                &att.issued_at,
            ))
            .to_hex();
        assert!(
            att.verify_against_store(
                store.owner_lct_id.unwrap(),
                &owner_kp.verifying_key(),
                "n",
                &store,
                max_age(),
                SKEW,
            )
            .is_err(),
            "future-dated beyond skew must reject"
        );
    }

    #[test]
    fn canonical_roster_hash_is_stable_and_excludes_liveness() {
        let (mut store, _keys) = store_with_keys(&[
            ("Desktop", DeviceType::Desktop),
            ("Phone", DeviceType::Mobile),
        ]);
        let h1 = store.canonical_roster_hash();
        // Mutating transient liveness must NOT change the roster identity.
        store.members[0].reachable = true;
        store.members[0].last_seen = Some(Utc::now());
        assert_eq!(
            h1,
            store.canonical_roster_hash(),
            "liveness churn is excluded"
        );
        // Revoking a device (authoritative status) MUST change it.
        store.members[0].status = DeviceStatus::Revoked;
        assert_ne!(
            h1,
            store.canonical_roster_hash(),
            "status is part of identity"
        );
    }

    // ---- cross-device co-signing ----

    #[test]
    fn remote_device_cosign_produces_a_valid_bound_signature() {
        // The device side of cross-device MFA: a REMOTE device, asked to co-sign,
        // signs EXACTLY the challenge payload with its own key. The signature
        // verifies over that payload — and NOT over a different one (it's bound to
        // the owner+roster+nonce). The owner drops it into device_signatures; the
        // hub then resolves the key from enrollment (verify_enrolled, hub side).
        let owner = Uuid::new_v4();
        let remote_dev = Uuid::new_v4();
        let remote_key = KeyPair::generate(); // lives on the remote machine
        let nonce = "hub-nonce".to_string();
        let issued_at = Utc::now();
        let roster = vec![remote_dev, Uuid::new_v4()];

        let req = CosignRequest::new(owner, roster.clone(), nonce.clone(), issued_at, remote_dev);
        let resp = req.cosign(remote_dev, &remote_key, &[owner], chrono::Duration::minutes(5), chrono::Duration::minutes(2), issued_at).unwrap();
        assert_eq!(resp.kind, CosignResponse::KIND);
        assert_eq!(resp.device_lct_id, remote_dev);

        let payload = ConstellationAttestation::signing_payload(owner, &roster, &nonce, &issued_at);
        let pk = pubkey_from_hex(&resp.device_pubkey_hex).unwrap();
        let sig = sig_from_hex(&resp.signature).unwrap();
        assert!(pk.verify(&payload, &sig).is_ok(), "co-sign is a valid signature over the challenge");
        // Bound: a tampered roster produces a different payload the sig won't cover.
        let tampered = ConstellationAttestation::signing_payload(owner, &[Uuid::new_v4()], &nonce, &issued_at);
        assert!(pk.verify(&tampered, &sig).is_err(), "the co-sign is bound to the exact roster+nonce");
    }

    #[test]
    fn owner_binds_remote_cosign_to_the_roster_pin() {
        // The remote branch of `present --remote` used to carry the responder's
        // self-reported pubkey into the attestation unchecked, while the local branch
        // used the roster's. Not a forgery vector (the hub resolves the key from the
        // ENROLLED set) but it turned a key-source drift into an opaque hub-side
        // reject. The owner now compares, so the mismatch is named where it happens.
        let owner = Uuid::new_v4();
        let dev = Uuid::new_v4();
        let key = KeyPair::generate();
        let roster = vec![dev];
        let issued_at = Utc::now();
        let req = CosignRequest::new(owner, roster, "n".to_string(), issued_at, dev);
        let resp = req.cosign(dev, &key, &[owner], chrono::Duration::minutes(5), chrono::Duration::minutes(2), issued_at).unwrap();

        // Equal by construction: cosign-serve signs with the member key the hub pinned,
        // which is what add-remote wrote into the roster entry.
        assert!(resp.check_device_pubkey(&key.verifying_key().to_hex()).is_ok());
        // Hex case is not identity.
        assert!(resp.check_device_pubkey(&key.verifying_key().to_hex().to_uppercase()).is_ok());
        // A peer whose local member_key_source drifted from the hub pin is refused.
        let err = resp.check_device_pubkey(&KeyPair::generate().verifying_key().to_hex()).unwrap_err().to_string();
        assert!(err.contains("roster pins"), "the error names the cause: {err}");
    }

    #[test]
    fn device_refuses_to_cosign_wrong_target_or_stale() {
        let dev = Uuid::new_v4();
        let owner = Uuid::new_v4();
        let key = KeyPair::generate();
        let now = Utc::now();
        let mk = |device_lct: Uuid, issued: DateTime<Utc>| CosignRequest::new(
            owner, vec![dev], "n".into(), issued, device_lct);
        let ma = chrono::Duration::minutes(5); let sk = chrono::Duration::minutes(2);
        let ok = [owner];
        // addressed to a different device
        assert!(mk(Uuid::new_v4(), now).cosign(dev, &key, &ok, ma, sk, now).is_err());
        // stale challenge
        assert!(mk(dev, now - chrono::Duration::minutes(6)).cosign(dev, &key, &ok, ma, sk, now).is_err());
        // future-dated
        assert!(mk(dev, now + chrono::Duration::minutes(5)).cosign(dev, &key, &ok, ma, sk, now).is_err());
        // valid
        assert!(mk(dev, now).cosign(dev, &key, &ok, ma, sk, now).is_ok());
    }

    #[test]
    fn device_refuses_to_cosign_for_an_unconsented_owner() {
        // Finding (b): being someone's MFA factor is a grant distinct from having a
        // confirmed pairing with them. `add-remote` makes naming an arbitrary
        // confirmed peer a one-liner, so without this the peer's assurance tier
        // becomes a function of the OWNER's roster edits alone.
        let dev = Uuid::new_v4();
        let owner = Uuid::new_v4();
        let key = KeyPair::generate();
        let now = Utc::now();
        let req = CosignRequest::new(owner, vec![dev], "n".into(), now, dev);
        let ma = chrono::Duration::minutes(5); let sk = chrono::Duration::minutes(2);

        // Fail closed: an empty list serves nobody, which is the default state.
        let err = req.cosign(dev, &key, &[], ma, sk, now).unwrap_err().to_string();
        assert!(err.contains("serve-owners list"), "the error names the fix: {err}");
        // A DIFFERENT consented owner does not transfer.
        assert!(req.cosign(dev, &key, &[Uuid::new_v4()], ma, sk, now).is_err());
        // Consent granted — and every other guard still applies afterwards.
        assert!(req.cosign(dev, &key, &[owner], ma, sk, now).is_ok());
    }

    #[test]
    fn serve_owner_consent_is_idempotent_and_withdrawable() {
        let mut store = ConstellationStore::default();
        let owner = Uuid::new_v4();
        assert!(store.serve_owners.is_empty(), "default is serve nobody");

        assert!(store.allow_owner(owner), "first grant takes effect");
        assert!(!store.allow_owner(owner), "re-granting is a no-op, not a duplicate");
        assert_eq!(store.serve_owners, vec![owner]);

        assert!(store.disallow_owner(owner), "withdrawal takes effect");
        assert!(!store.disallow_owner(owner), "withdrawing twice is a no-op");
        assert!(store.serve_owners.is_empty());
    }

    #[test]
    fn serve_owners_defaults_when_absent_from_a_stored_document() {
        // Vault documents written before this field existed must still load —
        // and must load as "serve nobody", never as "serve everybody".
        let store: ConstellationStore =
            serde_json::from_str(r#"{"owner_lct_id":null,"members":[]}"#).unwrap();
        assert!(store.serve_owners.is_empty());
    }
}
