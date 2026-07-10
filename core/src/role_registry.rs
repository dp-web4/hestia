//! Hestia's consumption of web4-core role entities — the Phase-1 audit-first
//! mirror, executable. Turns the constellation-role *strings* the daemon keys law
//! on ([`crate::reputation::KNOWN_CONSTELLATION_ROLES`]) into first-class
//! `web4_core::RoleEntity` LCT entities held in a [`web4_core::RoleRegistry`], so
//! the roles are visible AS entities — the PRD's "make the existing fleet visible
//! through the new lens before anything changes behavior."
//!
//! **Additive + read-only (Phase 1).** This does NOT change how law is evaluated —
//! that stays the deployed string-keyed strictest-wins fold (`fold_strictest`).
//! The registry is a parallel, entity-shaped view. Rewiring law evaluation to read
//! from Role entities is Phase 2 (behavior-changing).
//!
//! **Mirrored roles are honestly `drift:unattributed`.** A migrated string-role
//! has no write-time authoring witness (`authored_under`/`lint_verdict` = None), so
//! its `drift_mark()` is `DriftUnattributed` — exactly the §2.3 pre-migration case.
//! Authoring (lifting each launcher primer into a signed extension with a lint
//! witness) is the follow-up that moves them to attributed.
//!
//! KNOWN GAP surfaced by this mirror (flagged to the concord): the ontology models
//! affordances as GRANTS (extension grants ⊆ parent), while hestia models role law
//! as DENY OVERLAYS (extension adds denies). They are dual monotone-tightening
//! representations; the lift from overlay-denies to affordance-grants needs the
//! parent's full grant set, so mirrored extensions carry no affordances yet.

use sha2::{Digest, Sha256};
use uuid::Uuid;
use web4_core::{RoleEntity, RoleExtension, RoleRegistry, Scope};

/// Derive a stable sovereign `Uuid` from hestia's sovereign LCT string, so role
/// issuance is anchored to this constellation's sovereign. (hestia's sovereign is
/// a `phase1-placeholder` string today; this binds roles to it deterministically
/// until the TPM sovereign lands.)
fn sovereign_uuid(sovereign_lct: &str) -> Uuid {
    let digest = Sha256::digest(sovereign_lct.as_bytes());
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    Uuid::from_bytes(bytes)
}

/// The mirror extension for a migrated string-role: unattributed (no authoring
/// witness → `drift:unattributed` on any eval-time deny), folding under the
/// constellation base. `default_verdict: Deny` — fail-closed: an unattributed role
/// with no affordances grants nothing (CBP F1, 2026-07-08), which also accurately
/// mirrors the DEPLOYED launchers (all HST-004 fail-closed). No affordances yet
/// (see the module-level grant-vs-deny gap). `Scope::default()` = zero ATP budget.
fn mirror_extension() -> RoleExtension {
    RoleExtension {
        bound_to_role_lct: Uuid::nil(), // overwritten authoritatively by issue()
        affordances: Vec::new(),
        responsibilities: Vec::new(),
        scope: Scope::default(), // ranges_over: [], atp_budget: Limited(0.0) — fail-closed
        default_verdict: web4_core::ExtensionVerdict::Deny,
        folds_under: vec!["law:constellation".to_string()],
        authored_under: None, // pre-migration string-role → unattributed
        lint_verdict: None,
    }
}

/// Build the Phase-1 audit-mirror registry: one `RoleEntity` per published
/// constellation role, minted under this sovereign, each honestly unattributed.
/// The role LCTs are minted fresh per call — in-memory only; production uses
/// [`load_or_mint_registry`] for vault-stable identities.
pub fn build_mirror_registry(sovereign_lct: &str) -> RoleRegistry {
    let sovereign = sovereign_uuid(sovereign_lct);
    let mut registry = RoleRegistry::new();
    for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
        let (entity, _keypair) = RoleEntity::issue(*label, sovereign, mirror_extension());
        registry.register(entity);
    }
    registry
}

/// One persisted role: the LCT (durable identity), its label, its law extension,
/// and the role's OWN keypair secret (hex). The secret lives here — inside the
/// sealed vault, per the vault doctrine — so the role can later sign as itself
/// (Phase 2: signed law extensions, launch acts). Without it a "stable" LCT would
/// be hollow: a public key no one can ever answer for.
#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedRole {
    label: String,
    lct: web4_core::Lct,
    extension: RoleExtension,
    keypair_secret_hex: String,
}

const ROLES_NAMESPACE: &str = "roles";
const ROLES_DOC: &str = "registry";
const ROLES_LEGACY_FILE: &str = "roles.json";

/// Load the role registry from the vault, minting (and persisting) any published
/// constellation role not yet present. Role LCTs are therefore STABLE across
/// daemon restarts — "the role has presence" requires a durable identity, not a
/// fresh Uuid per boot. Additive: existing persisted roles are never re-minted or
/// mutated here; a newly-published role is minted once and persists thereafter.
/// Persistence failures degrade to the in-memory mirror (daemon must still start;
/// the instability is logged, not hidden).
pub fn load_or_mint_registry(vault: &mut crate::vault::Vault, sovereign_lct: &str) -> RoleRegistry {
    let sovereign = sovereign_uuid(sovereign_lct);
    let mut persisted: Vec<PersistedRole> =
        crate::vault::load_doc(vault, ROLES_NAMESPACE, ROLES_DOC, ROLES_LEGACY_FILE)
            .unwrap_or_default();

    let mut registry = RoleRegistry::new();
    for p in &persisted {
        registry.register(RoleEntity {
            lct: p.lct.clone(),
            label: p.label.clone(),
            extension: p.extension.clone(),
        });
    }

    // Mint any published role not yet persisted (first boot, or a set upgrade).
    let mut minted = false;
    for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
        if registry.get(label).is_some() {
            continue;
        }
        let (entity, keypair) = RoleEntity::issue(*label, sovereign, mirror_extension());
        persisted.push(PersistedRole {
            label: entity.label.clone(),
            lct: entity.lct.clone(),
            extension: entity.extension.clone(),
            keypair_secret_hex: hex::encode(keypair.secret_key_bytes()),
        });
        registry.register(entity);
        minted = true;
    }
    if minted {
        if let Err(e) = crate::vault::save_doc(vault, ROLES_NAMESPACE, ROLES_DOC, ROLES_LEGACY_FILE, &persisted) {
            // Degrade honestly: the daemon runs with in-memory identities this
            // boot; the next boot re-mints. Logged, never silently swallowed.
            eprintln!("[roles] WARNING: persisting role registry failed ({e}) — role LCTs are unstable this boot");
        }
    }
    registry
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::{DriftMark, EntityType};

    #[test]
    fn mirror_registry_holds_every_published_role_as_an_entity() {
        let reg = build_mirror_registry("lct:web4:hestia:sovereign:phase1-placeholder");
        assert_eq!(reg.len(), crate::reputation::KNOWN_CONSTELLATION_ROLES.len());
        for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
            let role = reg.get(label).expect("every published role is mirrored");
            // it's a real Role LCT entity, bound authoritatively
            assert_eq!(role.lct.entity_type, EntityType::Role);
            assert_eq!(role.extension.bound_to_role_lct, role.lct.id);
        }
    }

    #[test]
    fn mirrored_roles_are_honestly_unattributed() {
        // The §2.3 posture: a migrated string-role has no authoring witness, so an
        // eval-time deny against it is drift:unattributed — cause-unknown, not
        // mislabeled as author-error or parent-drift.
        let reg = build_mirror_registry("s");
        let mw = reg.get("role:constellation:mesh-worker").unwrap();
        assert_eq!(mw.extension.drift_mark(), DriftMark::DriftUnattributed);
        assert!(mw.extension.authored_under.is_none());
        // fail-closed: unattributed + no affordances → default deny, zero budget
        assert_eq!(mw.extension.default_verdict, web4_core::ExtensionVerdict::Deny);
        assert!(mw.extension.affordances.is_empty());
        assert_eq!(mw.extension.scope.atp_budget, web4_core::AtpBudget::Limited(0.0));
    }

    #[test]
    fn role_lcts_are_stable_across_vault_reopens() {
        // "The role has presence" — its LCT must survive a daemon restart, not be
        // a fresh Uuid per boot. Two loads against the SAME vault = same identities.
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        let mut vault = crate::vault::Vault::init(path.clone(), "p".into()).unwrap();
        let first = load_or_mint_registry(&mut vault, "sov");
        let ids1: Vec<_> = first
            .labels()
            .iter()
            .map(|l| first.get(l).unwrap().lct.id)
            .collect();
        drop(vault);
        // Reopen (the restart) and load again.
        let mut vault2 = crate::vault::Vault::open(path, "p".into()).unwrap();
        let second = load_or_mint_registry(&mut vault2, "sov");
        let ids2: Vec<_> = second
            .labels()
            .iter()
            .map(|l| second.get(l).unwrap().lct.id)
            .collect();
        assert_eq!(first.len(), crate::reputation::KNOWN_CONSTELLATION_ROLES.len());
        assert_eq!(ids1, ids2, "role LCTs must be identical across restarts");
    }

    #[test]
    fn persisted_keypair_answers_for_the_persisted_lct() {
        // The sealed secret must reconstruct a keypair whose public key IS the
        // persisted LCT's — otherwise the stable identity is hollow (a public key
        // no one can sign for).
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        let mut vault = crate::vault::Vault::init(path, "p".into()).unwrap();
        let reg = load_or_mint_registry(&mut vault, "sov");
        let persisted: Vec<super::PersistedRole> =
            crate::vault::load_doc(&vault, super::ROLES_NAMESPACE, super::ROLES_DOC, super::ROLES_LEGACY_FILE)
                .unwrap();
        assert_eq!(persisted.len(), reg.len());
        for p in &persisted {
            let bytes: [u8; 32] = hex::decode(&p.keypair_secret_hex).unwrap().try_into().unwrap();
            let kp = web4_core::crypto::KeyPair::from_secret_bytes(&bytes);
            assert_eq!(
                kp.verifying_key(), p.lct.public_key,
                "role {}: sealed secret must answer for the persisted LCT", p.label
            );
        }
    }

    #[test]
    fn sovereign_is_stable_but_distinct_per_sovereign_string() {
        assert_eq!(sovereign_uuid("a"), sovereign_uuid("a"));
        assert_ne!(sovereign_uuid("a"), sovereign_uuid("b"));
    }
}
