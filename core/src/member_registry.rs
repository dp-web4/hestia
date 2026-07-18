//! Custodial member LCTs — the third registry consumer (after the sovereign and
//! the constellation roles).
//!
//! A fleet *member* (`claude-code`, a mesh watcher, a timer) has been a mere
//! **label** all along: `member_lct(plugin_id)` = a hashed string, no keypair, no
//! presence. This mints each member a real [`web4_core::Lct`] — an `AiSoftware`
//! entity, custodial (hestia holds the sealed keypair; the member never sees it,
//! the S3 delegated posture from the Kimi concord), vault-persisted and stable
//! across restarts exactly like [`crate::sovereign`] and [`crate::role_registry`].
//!
//! **The label is not thrown away — it is carried as a verifiable legacy alias.**
//! The member LCT records a [`web4_core::LegacyAlias`] whose
//! [`web4_core::LegacyDerivation::HestiaMember`] re-derives the old
//! `lct:web4:member:<hex>` label byte-for-byte (the registry ingest checks this,
//! it does not trust it — HUB's §2 check 4). So (instance, role) trust grains
//! keyed on the label stay continuous: the same member, now with presence, no
//! re-key (the third-consumer migration ruling, 2026-07-10).
//!
//! **Minted on first observation, never per-connect.** A member that connects is
//! a real member; its LCT is minted once, then it is a cheap in-memory lookup.
//! This honors the connect-path guidance (no per-connect chain/vault side effects)
//! while still giving every real member durable presence. Fail-OPEN: a mint that
//! can't persist logs and retries next sighting — a member without an LCT yet is
//! simply not-yet-publishable, never a refused connect (unlike the fail-CLOSED
//! synthetic exclusion, which is a safety gate).

use std::collections::HashMap;
use web4_core::{EntityType, LegacyAlias, LegacyDerivation, Lct, MrhEdge};

const MEMBERS_NAMESPACE: &str = "members";
const MEMBERS_DOC: &str = "registry";
const MEMBERS_LEGACY_FILE: &str = "members.json";

/// One persisted member: `plugin_id` (the durable member identity the fleet keys
/// on), its custodial LCT, and the sealed keypair secret (hex) — the vault
/// doctrine, same as `PersistedRole`. The secret lets hestia sign AS the member
/// (custodial delegation), and re-sign its binding after a schema change.
#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedMember {
    plugin_id: String,
    lct: Lct,
    keypair_secret_hex: String,
}

/// In-memory member registry: `plugin_id → LCT`, rebuilt from the vault each boot.
#[derive(Default)]
pub struct MemberRegistry {
    members: HashMap<String, Lct>,
}

impl MemberRegistry {
    pub fn get(&self, plugin_id: &str) -> Option<&Lct> {
        self.members.get(plugin_id)
    }
    pub fn len(&self) -> usize {
        self.members.len()
    }
    pub fn is_empty(&self) -> bool {
        self.members.is_empty()
    }
    /// Every (plugin_id, LCT) pair, for the publish set. Sorted by plugin_id so
    /// dry-runs and publishes are reproducible.
    pub fn iter_sorted(&self) -> Vec<(&String, &Lct)> {
        let mut v: Vec<_> = self.members.iter().collect();
        v.sort_by(|a, b| a.0.cmp(b.0));
        v
    }
}

/// Load the persisted member registry from the vault. Additive: never mints here
/// (minting is [`ensure_member`], driven by real connects) — a fresh vault yields
/// an empty registry, populated as members appear.
pub fn load_members(vault: &crate::vault::Vault) -> MemberRegistry {
    let persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    let mut members = HashMap::new();
    for p in persisted {
        members.insert(p.plugin_id, p.lct);
    }
    MemberRegistry { members }
}

/// Attach a citizenship reference to a member's LCT and re-persist, so the member
/// now *carries* proof-of-citizenship (a tamper-evident pointer to the ledger
/// record — the authoritative home stays the ledger). Located by `plugin_id`, not
/// by lct_id, since that's the durable member key. Idempotent: a reference already
/// present (same society + entry) is not duplicated. Returns `true` if the member
/// exists and the reference is now attached (added or already present).
///
/// The subject's `citizenships` is plural (one per society), so this appends —
/// it never overwrites another society's citizenship (the plurality reshape).
pub fn attach_citizenship(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    plugin_id: &str,
    citizenship: web4_core::BirthCertificateRef,
) -> bool {
    let Some(lct) = registry.members.get_mut(plugin_id) else {
        return false;
    };
    if !lct.citizenships.contains(&citizenship) {
        lct.citizenships.push(citizenship);
    }
    // Re-persist the whole roster (the member's keypair secret is reloaded from
    // the existing doc so the persisted record stays complete).
    let mut persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    if let Some(p) = persisted.iter_mut().find(|p| p.plugin_id == plugin_id) {
        p.lct = lct.clone();
        if let Err(e) = crate::vault::save_doc(
            vault,
            MEMBERS_NAMESPACE,
            MEMBERS_DOC,
            MEMBERS_LEGACY_FILE,
            &persisted,
        ) {
            eprintln!("[members] WARNING: persisting citizenship for '{plugin_id}' failed ({e})");
        }
    }
    true
}

/// Build the verifiable legacy alias tying a member LCT to its pre-LCT label.
/// `sovereign_anchor` MUST be the exact string `member_lct` hashes over, so the
/// alias re-derives to the label the trust grains already use.
fn member_legacy_alias(plugin_id: &str, sovereign_anchor: &str) -> LegacyAlias {
    let derivation = LegacyDerivation::HestiaMember {
        plugin_id: plugin_id.to_string(),
        sovereign: sovereign_anchor.to_string(),
    };
    LegacyAlias {
        legacy_id: derivation.derive(),
        derivation,
    }
}

/// Ensure `plugin_id` has a custodial member LCT, minting + persisting on first
/// sight. Idempotent: an in-memory hit returns immediately (the hot path). Returns
/// the member's canonical `lct_id` when present/minted, `None` when it should not
/// have one (empty/synthetic — the same fail-closed domain as `member_lct`).
///
/// `sovereign_lct` is the LCT-anchor string (for the legacy alias + `created_by`
/// lineage); `sovereign_lct_id` is the sovereign's canonical id (the `mrh.bound`
/// parent target). Persist failure is logged and swallowed — the member simply
/// isn't published yet (fail-open; presence is not a safety gate).
pub fn ensure_member(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    plugin_id: &str,
    is_synthetic: bool,
    sovereign_lct_id: &str,
    sovereign_anchor: &str,
) -> Option<String> {
    let id = plugin_id.trim();
    if id.is_empty() || is_synthetic {
        return None; // mirror member_lct's fail-closed domain exactly
    }
    if let Some(lct) = registry.members.get(id) {
        return Some(lct.lct_id()); // hot path: already present
    }

    // First sight: mint an AiSoftware LCT with a custodial keypair.
    let (mut lct, keypair) = Lct::new(EntityType::AiSoftware, None);
    lct.sign_binding(&keypair); // self-issued §3.2 bootstrap, custodial key proves the binding
    lct.legacy_alias = Some(member_legacy_alias(id, sovereign_anchor));
    if !sovereign_lct_id.is_empty() {
        lct.mrh.bound = vec![MrhEdge {
            lct_id: sovereign_lct_id.to_string(),
            edge_type: "parent".to_string(),
            ts: lct.created_at,
        }];
    }

    // Persist: reload the doc, append, save (append-only; other members untouched).
    let mut persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    persisted.push(PersistedMember {
        plugin_id: id.to_string(),
        lct: lct.clone(),
        keypair_secret_hex: hex::encode(keypair.secret_key_bytes()),
    });
    if let Err(e) = crate::vault::save_doc(
        vault,
        MEMBERS_NAMESPACE,
        MEMBERS_DOC,
        MEMBERS_LEGACY_FILE,
        &persisted,
    ) {
        eprintln!(
            "[members] WARNING: persisting member LCT for '{id}' failed ({e}) — \
             not published this boot; re-mints on next sighting"
        );
        return None; // not durable → don't advertise presence we can't reproduce
    }
    let lct_id = lct.lct_id();
    registry.members.insert(id.to_string(), lct);
    Some(lct_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh_vault() -> (tempfile::TempDir, crate::vault::Vault) {
        let dir = tempfile::TempDir::new().unwrap();
        let vault = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        (dir, vault)
    }

    #[test]
    fn ensure_member_mints_persists_and_is_idempotent() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        let a1 = ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let a2 = ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        assert_eq!(a1, a2, "second call returns the same LCT (no re-mint)");
        assert_eq!(reg.len(), 1);
        assert!(a1.starts_with("lct:web4:mb32:b"));
        // distinct members get distinct LCTs
        let b = ensure_member(&mut vault, &mut reg, "alice", false, "sid", "anchor").unwrap();
        assert_ne!(a1, b);
        assert_eq!(reg.len(), 2);
    }

    #[test]
    fn member_lct_carries_a_verifiable_alias_to_its_label() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let lct = reg.get("claude-code").unwrap();
        let alias = lct.legacy_alias.as_ref().expect("member carries a legacy alias");
        assert!(alias.verify(), "the alias re-derives (registry ingest check 4)");
        // and it targets the SAME label the trust grains key on
        let expected = LegacyDerivation::HestiaMember {
            plugin_id: "claude-code".into(),
            sovereign: "anchor".into(),
        }
        .derive();
        assert_eq!(alias.legacy_id, expected);
        // it's a proven, sovereign-bound, AiSoftware entity
        assert!(lct.verify_binding());
        assert_eq!(lct.entity_type, EntityType::AiSoftware);
        assert_eq!(lct.mrh.bound[0].lct_id, "sid");
    }

    #[test]
    fn synthetic_and_empty_get_no_lct() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        assert!(ensure_member(&mut vault, &mut reg, "runner", true, "sid", "anchor").is_none());
        assert!(ensure_member(&mut vault, &mut reg, "   ", false, "sid", "anchor").is_none());
        assert_eq!(reg.len(), 0);
    }

    #[test]
    fn attach_citizenship_makes_the_member_carry_the_reference_and_persists() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let cref = web4_core::BirthCertificateRef {
            issuing_society: "lct:web4:society:hestia".into(),
            entry_id: "42".into(),
            entry_hash: "deadbeef".into(),
        };
        assert!(attach_citizenship(&mut vault, &mut reg, "claude-code", cref.clone()));
        assert_eq!(reg.get("claude-code").unwrap().citizenships, vec![cref.clone()]);
        // idempotent: attaching the same ref again does not duplicate
        attach_citizenship(&mut vault, &mut reg, "claude-code", cref.clone());
        assert_eq!(reg.get("claude-code").unwrap().citizenships.len(), 1);
        // a SECOND society's citizenship appends (plurality), never overwrites
        let cref2 = web4_core::BirthCertificateRef {
            issuing_society: "lct:web4:society:hub".into(),
            entry_id: "7".into(),
            entry_hash: "cafe".into(),
        };
        attach_citizenship(&mut vault, &mut reg, "claude-code", cref2.clone());
        assert_eq!(reg.get("claude-code").unwrap().citizenships.len(), 2);
        // persisted: a reload sees both citizenships
        let reloaded = load_members(&vault);
        assert_eq!(reloaded.get("claude-code").unwrap().citizenships.len(), 2);
        // an unknown member → false, no panic
        assert!(!attach_citizenship(&mut vault, &mut reg, "ghost", cref));
    }

    #[test]
    fn members_survive_a_reload() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        let minted = ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        // Reload from the vault (a restart).
        let reloaded = load_members(&vault);
        assert_eq!(reloaded.len(), 1);
        assert_eq!(reloaded.get("claude-code").unwrap().lct_id(), minted);
    }
}
