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
///
/// `sovereign_lct_id` is the sovereign's canonical (key-derived) LCT id; each
/// role's `mrh.bound` gets a **derived** parent edge to it — the reachability
/// statement "this role was issued under this sovereign" (canon §5). The edge is
/// recomputed every boot (ts = the role's own `created_at`, so it is deterministic
/// and never churns) and is NOT persisted: it is a projection of the issuance fact,
/// not stored state. Empty `sovereign_lct_id` ⇒ no bound edge (fail-quiet).
pub fn load_or_mint_registry(
    vault: &mut crate::vault::Vault,
    sovereign_lct: &str,
    sovereign_lct_id: &str,
) -> RoleRegistry {
    let sovereign = sovereign_uuid(sovereign_lct);
    let mut persisted: Vec<PersistedRole> =
        crate::vault::load_doc(vault, ROLES_NAMESPACE, ROLES_DOC, ROLES_LEGACY_FILE)
            .unwrap_or_default();

    // HEAL: roles persisted before binding signatures existed (pre web4 #499)
    // carry no `binding_proof` — the publish path's ingest mirror would rightly
    // refuse them. Their keypairs are sealed right here, so re-sign in place and
    // persist. Idempotent (only fires on absent proofs); a sealed secret that no
    // longer answers for its LCT is logged and left unsigned — an unpublishable
    // role is a visible fact, never a forged signature.
    let mut healed = false;
    for p in &mut persisted {
        if p.lct.binding_proof.is_none() {
            match hex::decode(&p.keypair_secret_hex)
                .ok()
                .and_then(|b| <[u8; 32]>::try_from(b).ok())
            {
                Some(bytes) => {
                    let kp = web4_core::crypto::KeyPair::from_secret_bytes(&bytes);
                    if kp.verifying_key() == p.lct.public_key {
                        p.lct.sign_binding(&kp);
                        healed = true;
                    } else {
                        eprintln!(
                            "[roles] WARNING: sealed secret for {} does not answer for its LCT — leaving binding unproven",
                            p.label
                        );
                    }
                }
                None => eprintln!(
                    "[roles] WARNING: sealed secret for {} is malformed — leaving binding unproven",
                    p.label
                ),
            }
        }
    }
    if healed {
        if let Err(e) = crate::vault::save_doc(vault, ROLES_NAMESPACE, ROLES_DOC, ROLES_LEGACY_FILE, &persisted) {
            eprintln!("[roles] WARNING: persisting healed binding proofs failed ({e}) — re-heals next boot");
        }
    }

    // Populate a role's MRH `bound` parent edge to the sovereign (canon §5:
    // reachability is the edge, not metadata). Derived, deterministic (ts = the
    // role's own created_at → never churns), applied before registration. Empty
    // `sovereign_lct_id` ⇒ no edge (fail-quiet).
    let with_bound_edge = |mut entity: RoleEntity| -> RoleEntity {
        if !sovereign_lct_id.is_empty() {
            let ts = entity.lct.created_at;
            entity.lct.mrh.bound = vec![web4_core::MrhEdge {
                lct_id: sovereign_lct_id.to_string(),
                edge_type: "parent".to_string(),
                ts,
            }];
        }
        entity
    };

    let mut registry = RoleRegistry::new();
    for p in &persisted {
        registry.register(with_bound_edge(RoleEntity {
            lct: p.lct.clone(),
            label: p.label.clone(),
            extension: p.extension.clone(),
        }));
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
        registry.register(with_bound_edge(entity));
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
        let first = load_or_mint_registry(&mut vault, "sov", "lct:web4:mb32:btestsovereign");
        let ids1: Vec<_> = first
            .labels()
            .iter()
            .map(|l| first.get(l).unwrap().lct.id)
            .collect();
        drop(vault);
        // Reopen (the restart) and load again.
        let mut vault2 = crate::vault::Vault::open(path, "p".into()).unwrap();
        let second = load_or_mint_registry(&mut vault2, "sov", "lct:web4:mb32:btestsovereign");
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
        let reg = load_or_mint_registry(&mut vault, "sov", "lct:web4:mb32:btestsovereign");
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
    fn unsigned_persisted_roles_are_healed_with_their_sealed_keypairs() {
        // Roles persisted pre-#499 have no binding_proof. On load, the sealed
        // secret re-signs the binding in place and persists — so the publish
        // path's ingest mirror accepts them without re-minting identity.
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        let mut vault = crate::vault::Vault::init(path.clone(), "p".into()).unwrap();
        let _ = load_or_mint_registry(&mut vault, "sov", "sid");
        // Simulate the pre-#499 vault state: strip every proof and re-persist.
        let mut persisted: Vec<super::PersistedRole> =
            crate::vault::load_doc(&vault, super::ROLES_NAMESPACE, super::ROLES_DOC, super::ROLES_LEGACY_FILE).unwrap();
        for p in &mut persisted { p.lct.binding_proof = None; }
        crate::vault::save_doc(&mut vault, super::ROLES_NAMESPACE, super::ROLES_DOC, super::ROLES_LEGACY_FILE, &persisted).unwrap();
        drop(vault);
        // Reload (the healing boot): every role verifies again…
        let mut vault2 = crate::vault::Vault::open(path.clone(), "p".into()).unwrap();
        let reg = load_or_mint_registry(&mut vault2, "sov", "sid");
        for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
            assert!(reg.get(label).unwrap().lct.verify_binding(), "{label} healed");
        }
        // …and the heal PERSISTED (a third load starts from signed documents).
        let healed: Vec<super::PersistedRole> =
            crate::vault::load_doc(&vault2, super::ROLES_NAMESPACE, super::ROLES_DOC, super::ROLES_LEGACY_FILE).unwrap();
        assert!(healed.iter().all(|p| p.lct.binding_proof.is_some()), "heal written back to the vault");
    }

    #[test]
    fn roles_carry_a_bound_parent_edge_to_the_sovereign() {
        // Canon §5: reachability is the MRH edge. Every mirrored role must carry a
        // `bound` parent edge to the sovereign's canonical LCT id — the "issued
        // under this sovereign" statement, traversable.
        let dir = tempfile::TempDir::new().unwrap();
        let mut vault = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let sov_id = "lct:web4:mb32:bexamplesovereignid";
        let reg = load_or_mint_registry(&mut vault, "sov", sov_id);
        for label in crate::reputation::KNOWN_CONSTELLATION_ROLES {
            let role = reg.get(label).unwrap();
            assert_eq!(role.lct.mrh.bound.len(), 1, "{label} has exactly one bound edge");
            let edge = &role.lct.mrh.bound[0];
            assert_eq!(edge.lct_id, sov_id, "bound edge targets the sovereign");
            assert_eq!(edge.edge_type, "parent");
            // deterministic: the edge ts is the role's own created_at (never churns)
            assert_eq!(edge.ts, role.lct.created_at);
        }
    }

    #[test]
    fn empty_sovereign_id_leaves_bound_edges_absent_fail_quiet() {
        let dir = tempfile::TempDir::new().unwrap();
        let mut vault = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let reg = load_or_mint_registry(&mut vault, "sov", "");
        let mw = reg.get("role:constellation:mesh-worker").unwrap();
        assert!(mw.lct.mrh.bound.is_empty(), "no sovereign id ⇒ no bound edge");
    }

    #[test]
    fn sovereign_is_stable_but_distinct_per_sovereign_string() {
        assert_eq!(sovereign_uuid("a"), sovereign_uuid("a"));
        assert_ne!(sovereign_uuid("a"), sovereign_uuid("b"));
    }
}
