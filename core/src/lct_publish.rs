//! The LCT publish emitter — hestia's half of the registry seam (HUB's
//! `LctPublished` contract, `hub-to-legion-lct-published-event-spec-registry-
//! projection-2026-07-10.md` §1–2).
//!
//! Canon genesis step 7: the society publishes its LCTs to the registry so
//! presence becomes *witnessed* presence. This module builds the publish
//! payloads for everything this constellation can currently answer for —
//! the sovereign and the constellation roles (member LCTs follow once the
//! custodial minting build lands; today members are labels, and a label is
//! not publishable presence).
//!
//! **Producer-side fail-closed:** [`self_check`] mirrors the hub's five-check
//! ingest (§2, checks 2–5 — check 1, the envelope signature, is transport and
//! happens at send time). We refuse to *emit* anything the ingest would
//! reject: a publish that fails locally is a bug here, not a negotiation with
//! the registry. Same discipline as [`web4_core::LegacyAlias::verify`] —
//! checked facts, not asserted ones.
//!
//! **Ordering (HUB's coordination note):** the sovereign publishes FIRST, so
//! role `mrh.bound` edges pointing at it resolve on arrival instead of
//! dangling 404 ("honest dangling" is legal but avoidable here).
//!
//! The payload struct mirrors HUB's field names verbatim. When the hub side
//! lands its `HubEvent::LctPublished`, this struct is the candidate to lift
//! into a shared crate (the LegacyDerivation argument: one shape, no consumer
//! drift) — flagged, not done unilaterally, since `HubEvent` is HUB's lane.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use web4_core::Lct;

/// Presence-only provenance (spec §1). `SelfIssued` = §3.2 bootstrap;
/// `SocietyConferred` = birth-certificate-class, **rejected at ingest until
/// Phase 2's ≥3 Witness-daemon quorum exists** — so this emitter refuses to
/// construct it (see [`self_check`]).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LctProvenance {
    SelfIssued,
    SocietyConferred,
}

/// One `LctPublished` payload — field names exactly per HUB's §1 contract.
/// The signed envelope (spec check 1) wraps this at send time via the existing
/// `hub::SignedEnvelope` machinery.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LctPublishPayload {
    /// Canonical reachable id — re-derived and checked by ingest (check 3).
    pub lct_id: String,
    /// The LCT document, verbatim (producer and witnesses serialize
    /// byte-identical — the ReferencedAct convergence discipline).
    pub document: Lct,
    /// The pinned hub member relaying the publish (this constellation's hub
    /// identity). Authorship of the LCT itself is in `document`.
    pub published_by: Uuid,
    pub provenance: LctProvenance,
    pub published_at: DateTime<Utc>,
}

/// Producer-side mirror of the hub's fail-closed ingest (spec §2, checks 2–5).
/// An `Err` here means the payload would be 4xx-rejected — so it never leaves
/// this process. Returns the failed check by name for honest diagnostics.
pub fn self_check(payload: &LctPublishPayload) -> Result<(), String> {
    // §2 check 2 — binding proven, from the document alone.
    if !payload.document.verify_binding() {
        return Err(format!(
            "check 2 (binding): binding_proof absent or invalid for {}",
            payload.lct_id
        ));
    }
    // §2 check 3 — the claimed canonical id re-derives from the pubkey.
    let derived = web4_core::derive_lct_id(&payload.document.public_key);
    if derived != payload.lct_id {
        return Err(format!(
            "check 3 (id): claimed {} but pubkey derives {derived}",
            payload.lct_id
        ));
    }
    // §2 check 4 — a claimed legacy alias must re-derive byte-identical.
    if let Some(alias) = &payload.document.legacy_alias {
        if !alias.verify() {
            return Err(format!(
                "check 4 (alias): legacy_id {} does not re-derive from recorded inputs",
                alias.legacy_id
            ));
        }
    }
    // §2 check 5 — Phase 1 admits self_issued only.
    if payload.provenance != LctProvenance::SelfIssued {
        return Err(
            "check 5 (provenance): society_conferred requires the Phase-2 witness quorum"
                .to_string(),
        );
    }
    Ok(())
}

/// Collect the constellation's publishable set, **sovereign first** (so role
/// `bound` edges resolve on arrival), then roles in stable label order. Every
/// payload has passed [`self_check`]; anything that fails is returned in
/// `refused` with its reason rather than silently dropped — a role we cannot
/// publish is a fact the operator should see, not an absence.
pub struct PublishSet {
    pub payloads: Vec<LctPublishPayload>,
    pub refused: Vec<(String, String)>, // (lct label/id, reason)
}

pub fn collect_publish_set(
    sovereign: &crate::sovereign::Sovereign,
    registry: &web4_core::RoleRegistry,
    published_by: Uuid,
    published_at: DateTime<Utc>,
) -> PublishSet {
    let mut payloads = Vec::new();
    let mut refused = Vec::new();

    let mut push_checked = |label: &str, document: Lct| {
        let payload = LctPublishPayload {
            lct_id: document.lct_id(),
            document,
            published_by,
            provenance: LctProvenance::SelfIssued,
            published_at,
        };
        match self_check(&payload) {
            Ok(()) => payloads.push(payload),
            Err(reason) => refused.push((label.to_string(), reason)),
        }
    };

    // Sovereign FIRST (HUB's ordering note — bound edges resolve on arrival).
    push_checked("sovereign", sovereign.lct.clone());

    // Then the constellation roles, stable order for reproducible dry-runs.
    let mut labels = registry.labels();
    labels.sort_unstable();
    for label in labels {
        if let Some(role) = registry.get(label) {
            push_checked(label, role.lct.clone());
        }
    }

    PublishSet { payloads, refused }
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::{EntityType, LegacyAlias, LegacyDerivation};

    fn test_sovereign_and_registry() -> (crate::sovereign::Sovereign, web4_core::RoleRegistry, tempfile::TempDir) {
        let dir = tempfile::TempDir::new().unwrap();
        let mut vault = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let sovereign = crate::sovereign::Sovereign::load_or_mint(&mut vault, "anchor");
        let registry =
            crate::role_registry::load_or_mint_registry(&mut vault, "anchor", &sovereign.lct_id());
        (sovereign, registry, dir)
    }

    #[test]
    fn publish_set_is_sovereign_first_then_all_roles_all_checked() {
        let (sovereign, registry, _dir) = test_sovereign_and_registry();
        let set = collect_publish_set(&sovereign, &registry, Uuid::new_v4(), Utc::now());
        assert!(
            set.refused.is_empty(),
            "freshly minted set must fully pass its own ingest mirror: {:?}",
            set.refused
        );
        assert_eq!(
            set.payloads.len(),
            1 + crate::reputation::KNOWN_CONSTELLATION_ROLES.len(),
            "sovereign + every published role"
        );
        // sovereign first — the ordering the bound edges depend on
        assert_eq!(set.payloads[0].lct_id, sovereign.lct_id());
        // every payload independently re-verifies (what ingest will do)
        for p in &set.payloads {
            assert!(self_check(p).is_ok());
            assert_eq!(p.provenance, LctProvenance::SelfIssued);
        }
    }

    #[test]
    fn self_check_refuses_unproven_binding() {
        // A document with no binding_proof would be 4xx-rejected (check 2) —
        // the emitter must refuse it locally.
        let (lct, _kp) = Lct::new(EntityType::Role, None); // unsigned
        let payload = LctPublishPayload {
            lct_id: lct.lct_id(),
            document: lct,
            published_by: Uuid::new_v4(),
            provenance: LctProvenance::SelfIssued,
            published_at: Utc::now(),
        };
        let err = self_check(&payload).unwrap_err();
        assert!(err.contains("check 2"), "named check in the refusal: {err}");
    }

    #[test]
    fn self_check_refuses_mismatched_id_and_forged_alias_and_conferred() {
        let (mut lct, kp) = Lct::new(EntityType::AiSoftware, None);
        lct.sign_binding(&kp);
        // check 3: claimed id ≠ derived
        let mut p = LctPublishPayload {
            lct_id: "lct:web4:mb32:bwrong".into(),
            document: lct.clone(),
            published_by: Uuid::new_v4(),
            provenance: LctProvenance::SelfIssued,
            published_at: Utc::now(),
        };
        assert!(self_check(&p).unwrap_err().contains("check 3"));
        // check 4: forged alias
        p.lct_id = lct.lct_id();
        p.document.legacy_alias = Some(LegacyAlias {
            legacy_id: "lct:web4:member:deadbeefdeadbeefdeadbeef".into(),
            derivation: LegacyDerivation::HestiaMember {
                plugin_id: "claude-code".into(),
                sovereign: "s".into(),
            },
        });
        // re-sign: legacy_alias isn't in the binding message, but keep the doc honest
        assert!(self_check(&p).unwrap_err().contains("check 4"));
        // check 5: society_conferred refused in Phase 1
        p.document.legacy_alias = None;
        p.provenance = LctProvenance::SocietyConferred;
        assert!(self_check(&p).unwrap_err().contains("check 5"));
    }

    #[test]
    fn payload_wire_shape_matches_the_spec_field_names() {
        // The contract is the FIELD NAMES (HUB builds ingest against these).
        // Lock them so a rename here is a test failure, not a silent seam break.
        let (sovereign, _reg, _dir) = test_sovereign_and_registry();
        let payload = LctPublishPayload {
            lct_id: sovereign.lct_id(),
            document: sovereign.lct.clone(),
            published_by: Uuid::nil(),
            provenance: LctProvenance::SelfIssued,
            published_at: Utc::now(),
        };
        let v: serde_json::Value = serde_json::to_value(&payload).unwrap();
        for key in ["lct_id", "document", "published_by", "provenance", "published_at"] {
            assert!(v.get(key).is_some(), "spec field `{key}` present on the wire");
        }
        assert_eq!(v["provenance"], "self_issued", "snake_case provenance tag");
    }
}
