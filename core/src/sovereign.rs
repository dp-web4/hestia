//! The constellation **Society** and its **`role:sovereign`** — the sovereign-as-role
//! restructure (dp, 2026-07-15; SAL §2.1).
//!
//! The Sovereign is not a special entity: it is a *role* in a society, occupied by
//! the genesis operator to start. This module therefore models two things that the
//! earlier bootstrap collapsed into one:
//!
//! - The **Society** (`EntityType::Society`, #516) — the constellation itself: the
//!   entity with durable presence that mints the roles, anchors the ledger, and is
//!   the `issuing_society` for citizenship. `lct_id()` is its canonical id.
//! - **`role:sovereign`** — a first-class `RoleEntity` the society mints, occupied
//!   by the operator, whose admission law is the **ratchet** (a
//!   [`web4_core::RatchetRequirement`], genesis L0 at bootstrap: single device,
//!   access-is-authority — the honest weak-`R` rung). The ratchet is provable,
//!   monotone, and belongs on the society's presence (the ratchet model doc).
//!
//! Because `lct_id` is pubkey-derived, retyping the bootstrap entity from
//! `Organization` to `Society` does NOT move its identity — the same sealed key,
//! the same id. Old persisted sovereigns are HEALED on load (retype + re-sign +
//! mint the sovereign role). The `anchor` string is unchanged, so member labels
//! and witness-chain authorship keyed on it stay byte-stable.
//!
//! The struct is named [`Society`]; [`Sovereign`] is a back-compat alias.

use sha2::{Digest, Sha256};
use uuid::Uuid;
use web4_core::{
    EntityType, ExtensionVerdict, Lct, LctBuilder, MrhEdge, RatchetRequirement, RoleEntity,
    RoleExtension, Scope,
};

const SOVEREIGN_NAMESPACE: &str = "sovereign";
const SOVEREIGN_DOC: &str = "identity";
const SOVEREIGN_LEGACY_FILE: &str = "sovereign.json";

/// The canonical label of the sovereign role (SAL §2.1's Sovereign, as a
/// `role:society:*` id — distinct from the `role:constellation:*` capacity roles).
pub const SOVEREIGN_ROLE_LABEL: &str = "role:society:sovereign";

fn society_uuid(anchor: &str) -> Uuid {
    let digest = Sha256::digest(anchor.as_bytes());
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    Uuid::from_bytes(bytes)
}

/// The `role:sovereign` extension — fail-closed like the mirror roles (grants
/// nothing by the extension; sovereign authority comes from the ratchet + a
/// witnessed occupancy, not from affordances). Folds under the constellation base.
fn sovereign_role_extension() -> RoleExtension {
    RoleExtension {
        bound_to_role_lct: Uuid::nil(), // overwritten by issue()
        affordances: Vec::new(),
        responsibilities: Vec::new(),
        scope: Scope::default(),
        default_verdict: ExtensionVerdict::Deny,
        folds_under: vec!["law:constellation".to_string()],
        authored_under: None,
        lint_verdict: None,
    }
}

/// One persisted item's secret + LCT. Used for both the society and its sovereign
/// role so each can sign as itself (vault doctrine).
#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedSociety {
    anchor: String,
    /// The Society LCT.
    lct: Lct,
    keypair_secret_hex: String,
    /// `role:sovereign` — the RoleEntity the society mints. `None` in a legacy
    /// (pre-restructure) doc; healed on load.
    #[serde(default)]
    sovereign_role: Option<PersistedRole>,
    /// The sovereign role's admission law (the ratchet). Genesis L0 by default.
    #[serde(default)]
    ratchet: Option<RatchetRequirement>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedRole {
    lct: Lct,
    label: String,
    extension: RoleExtension,
    keypair_secret_hex: String,
}

/// The constellation society + its sovereign role, loaded/minted from the vault.
pub struct Society {
    /// The Society LCT — the constellation's presence. `lct_id()` is its id.
    pub lct: Lct,
    /// The legacy anchor string (member labels + witness-chain authorship key on
    /// this verbatim; unchanged by the restructure).
    pub anchor: String,
    /// `role:sovereign` — occupied by the operator; its admission law is `ratchet`.
    pub sovereign_role: RoleEntity,
    /// The sovereign role's ratchet requirement (provable authority level).
    pub ratchet: RatchetRequirement,
}

/// Back-compat alias — the entity is a Society; sovereignty is a role within it.
pub type Sovereign = Society;

impl Society {
    /// Load the society + sovereign role from the vault, minting on first boot and
    /// HEALING a legacy (pre-restructure) sovereign: retype `Organization`→`Society`
    /// (re-signing the binding, id unchanged since it is pubkey-derived), mint the
    /// missing `role:sovereign`, and default the ratchet to genesis L0. Re-persists
    /// after a heal. Stable across restarts; the anchor is recorded verbatim.
    pub fn load_or_mint(vault: &mut crate::vault::Vault, anchor: &str) -> Self {
        let existing: Option<PersistedSociety> = crate::vault::load_doc::<Option<PersistedSociety>>(
            vault,
            SOVEREIGN_NAMESPACE,
            SOVEREIGN_DOC,
            SOVEREIGN_LEGACY_FILE,
        )
        .unwrap_or(None);

        let society_kp_uuid = society_uuid(anchor);

        if let Some(mut p) = existing {
            let mut healed = false;
            // HEAL 1: retype Organization → Society (identity unchanged; re-sign).
            if p.lct.entity_type == EntityType::Organization {
                if let Some(kp) = recover_kp(&p.keypair_secret_hex, &p.lct) {
                    p.lct.entity_type = EntityType::Society;
                    p.lct.sign_binding(&kp);
                    healed = true;
                }
            }
            // HEAL 2: mint the sovereign role if a legacy doc lacks it.
            if p.sovereign_role.is_none() {
                let (role_lct, role_kp) =
                    RoleEntity::issue(SOVEREIGN_ROLE_LABEL, society_kp_uuid, sovereign_role_extension());
                p.sovereign_role = Some(PersistedRole {
                    lct: role_lct.lct.clone(),
                    label: role_lct.label.clone(),
                    extension: role_lct.extension.clone(),
                    keypair_secret_hex: hex::encode(role_kp.secret_key_bytes()),
                });
                healed = true;
            }
            let ratchet = p.ratchet.clone().unwrap_or_else(RatchetRequirement::genesis);
            if p.ratchet.is_none() {
                p.ratchet = Some(ratchet.clone());
                healed = true;
            }
            // HEAL 3: the ratchet must ride ON role:sovereign's LCT (provable from
            // the registry). A Society persisted before `authority_ratchet` existed
            // lacks it — set it.
            {
                let role = p.sovereign_role.as_mut().unwrap();
                if role.lct.authority_ratchet.as_ref() != Some(&ratchet) {
                    role.lct.authority_ratchet = Some(ratchet.clone());
                    healed = true;
                }
            }
            // HEAL 4: the society PAIRS to its sovereign role, so a resolver can
            // traverse society → role:sovereign → authority_ratchet.
            let role_id = p.sovereign_role.as_ref().unwrap().lct.lct_id();
            if !p.lct.mrh.paired.iter().any(|e| e.edge_type == "sovereign_role") {
                let ts = p.lct.created_at;
                p.lct.mrh.paired.push(MrhEdge {
                    lct_id: role_id,
                    edge_type: "sovereign_role".to_string(),
                    ts,
                });
                healed = true;
            }
            let sovereign_role = role_entity_from(p.sovereign_role.as_ref().unwrap());
            if healed {
                let _ = crate::vault::save_doc(
                    vault, SOVEREIGN_NAMESPACE, SOVEREIGN_DOC, SOVEREIGN_LEGACY_FILE, &p,
                );
            }
            return Society { lct: p.lct, anchor: p.anchor, sovereign_role, ratchet };
        }

        // First boot: mint the Society LCT (self-issued §3.2 bootstrap) + role:sovereign.
        let (mut lct, keypair) = LctBuilder::new(EntityType::Society).build();
        let (mut role_entity, role_kp) =
            RoleEntity::issue(SOVEREIGN_ROLE_LABEL, society_kp_uuid, sovereign_role_extension());
        let ratchet = RatchetRequirement::genesis();
        // The ratchet rides ON role:sovereign's LCT (provable from the registry),
        // and the society PAIRS to its sovereign role so a resolver can traverse
        // society → role:sovereign → authority_ratchet. Both re-sign after mutation.
        role_entity.lct.authority_ratchet = Some(ratchet.clone());
        role_entity.lct.sign_binding(&role_kp);
        lct.mrh.paired.push(MrhEdge {
            lct_id: role_entity.lct.lct_id(),
            edge_type: "sovereign_role".to_string(),
            ts: lct.created_at,
        });
        lct.sign_binding(&keypair);

        let persisted = PersistedSociety {
            anchor: anchor.to_string(),
            lct: lct.clone(),
            keypair_secret_hex: hex::encode(keypair.secret_key_bytes()),
            sovereign_role: Some(PersistedRole {
                lct: role_entity.lct.clone(),
                label: role_entity.label.clone(),
                extension: role_entity.extension.clone(),
                keypair_secret_hex: hex::encode(role_kp.secret_key_bytes()),
            }),
            ratchet: Some(ratchet.clone()),
        };
        if let Err(e) = crate::vault::save_doc(
            vault, SOVEREIGN_NAMESPACE, SOVEREIGN_DOC, SOVEREIGN_LEGACY_FILE, &persisted,
        ) {
            eprintln!(
                "[society] WARNING: persisting society identity failed ({e}) — \
                 ephemeral this boot; re-mints next boot"
            );
        }
        Society { lct, anchor: anchor.to_string(), sovereign_role: role_entity, ratchet }
    }

    /// The society's canonical, key-derived LCT id (`lct:web4:mb32:…`).
    pub fn lct_id(&self) -> String {
        self.lct.lct_id()
    }

    /// The `role:sovereign` LCT's canonical id.
    pub fn sovereign_role_id(&self) -> String {
        self.sovereign_role.lct.lct_id()
    }

    /// The society's provable ratchet level (0 = genesis; monotone). A derived
    /// summary of the sovereign role's admission law — inspectable evidence, not a
    /// verdict (LCT spec §1.2).
    pub fn ratchet_level(&self) -> u8 {
        self.ratchet.level()
    }
}

fn recover_kp(secret_hex: &str, lct: &Lct) -> Option<web4_core::crypto::KeyPair> {
    let bytes: [u8; 32] = hex::decode(secret_hex).ok()?.try_into().ok()?;
    let kp = web4_core::crypto::KeyPair::from_secret_bytes(&bytes);
    (kp.verifying_key() == lct.public_key).then_some(kp)
}

fn role_entity_from(p: &PersistedRole) -> RoleEntity {
    RoleEntity { lct: p.lct.clone(), label: p.label.clone(), extension: p.extension.clone() }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh_vault() -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        (dir, path)
    }

    #[test]
    fn society_identity_is_stable_across_reopens_and_is_a_society() {
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path.clone(), "p".into()).unwrap();
        let s1 = Society::load_or_mint(&mut v, "lct:web4:hestia:sovereign:phase1-placeholder");
        let id1 = s1.lct_id();
        let role1 = s1.sovereign_role_id();
        assert_eq!(s1.lct.entity_type, EntityType::Society, "the entity is a Society");
        assert!(s1.lct.verify_binding());
        assert_eq!(s1.sovereign_role.label, SOVEREIGN_ROLE_LABEL);
        assert_eq!(s1.ratchet_level(), 0, "genesis L0 at bootstrap");
        drop(v);
        let mut v2 = crate::vault::Vault::open(path, "p".into()).unwrap();
        let s2 = Society::load_or_mint(&mut v2, "lct:web4:hestia:sovereign:phase1-placeholder");
        assert_eq!(id1, s2.lct_id(), "society id stable across restarts");
        assert_eq!(role1, s2.sovereign_role_id(), "sovereign role id stable too");
        assert!(id1.starts_with("lct:web4:mb32:b"));
    }

    #[test]
    fn sovereign_role_binding_self_verifies_and_is_distinct_from_the_society() {
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path, "p".into()).unwrap();
        let s = Society::load_or_mint(&mut v, "anchor");
        assert!(s.sovereign_role.lct.verify_binding(), "sovereign role signs its own binding");
        assert_ne!(s.lct_id(), s.sovereign_role_id(), "the role is a distinct entity from the society");
        assert_eq!(s.sovereign_role.extension.default_verdict, ExtensionVerdict::Deny, "fail-closed");
    }

    #[test]
    fn anchor_is_recorded_verbatim_for_downstream_derivations() {
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path, "p".into()).unwrap();
        let anchor = "lct:web4:hestia:sovereign:phase1-placeholder";
        let s = Society::load_or_mint(&mut v, anchor);
        assert_eq!(s.anchor, anchor);
    }

    #[test]
    fn legacy_organization_sovereign_is_healed_to_a_society_with_a_role() {
        // Simulate a pre-restructure persisted doc: an Organization LCT, no role.
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path.clone(), "p".into()).unwrap();
        // Mint via the OLD shape by hand: an Organization society, no sovereign role.
        let (mut lct, kp) = LctBuilder::new(EntityType::Organization).build();
        lct.sign_binding(&kp);
        let old_id = lct.lct_id();
        let legacy = PersistedSociety {
            anchor: "anchor".into(),
            lct,
            keypair_secret_hex: hex::encode(kp.secret_key_bytes()),
            sovereign_role: None,
            ratchet: None,
        };
        crate::vault::save_doc(&mut v, SOVEREIGN_NAMESPACE, SOVEREIGN_DOC, SOVEREIGN_LEGACY_FILE, &legacy).unwrap();

        // Load → healed: retyped to Society (SAME id, pubkey-derived), role minted, genesis ratchet.
        let s = Society::load_or_mint(&mut v, "anchor");
        assert_eq!(s.lct.entity_type, EntityType::Society, "retyped to Society");
        assert_eq!(s.lct_id(), old_id, "identity unchanged (id is pubkey-derived)");
        assert!(s.lct.verify_binding(), "re-signed binding verifies after retype");
        assert_eq!(s.sovereign_role.label, SOVEREIGN_ROLE_LABEL, "sovereign role minted on heal");
        assert_eq!(s.ratchet_level(), 0);
        // and the heal persisted (a reload sees a Society, no re-heal churn)
        let s2 = Society::load_or_mint(&mut v, "anchor");
        assert_eq!(s2.sovereign_role_id(), s.sovereign_role_id());
    }
}
