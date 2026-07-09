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
/// The role LCTs are minted fresh per call (in-memory Phase-1 visibility); stable
/// vault-persisted identities are the immediate follow-up.
pub fn build_mirror_registry(sovereign_lct: &str) -> RoleRegistry {
    let sovereign = sovereign_uuid(sovereign_lct);
    let mut registry = RoleRegistry::new();
    for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
        let (entity, _keypair) = RoleEntity::issue(*label, sovereign, mirror_extension());
        registry.register(entity);
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
    fn sovereign_is_stable_but_distinct_per_sovereign_string() {
        assert_eq!(sovereign_uuid("a"), sovereign_uuid("a"));
        assert_ne!(sovereign_uuid("a"), sovereign_uuid("b"));
    }
}
