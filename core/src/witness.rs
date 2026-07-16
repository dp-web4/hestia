//! Witnessing — hestia's half of Phase-2 birth certificates (concord W1/W4,
//! 2026-07-15). A society confers citizenship on an entity once a **quorum of ≥3
//! distinct witnesses** has each signed an `Existence` attestation over that
//! entity's LCT. hestia participates on both sides:
//!
//! - **Produce** ([`attest`]): this constellation is a pinned hub member, so it
//!   IS one of the witness pool (W1 ruling (b): pinned members on distinct
//!   machines are distinct-entity/distinct-key/distinct-control — the
//!   independence canon wants, no separate daemon). It signs Existence
//!   attestations with its **operational** key (the resolvable channel key, NOT
//!   the vault-sealed identity — W1's autonomy constraint: a witness can only
//!   attest autonomously if the registry-resolvable key is operationally
//!   available to it).
//! - **Assess** ([`valid_distinct_existence`], [`quorum_reached`]): given a
//!   subject's collected attestations and a witness-pubkey resolver (the registry
//!   is that resolver on the hub side), compute the verified quorum. Fail-closed,
//!   reusing the web4-core `Attestation::verify` + the ≥3-DISTINCT-witness rule.
//!
//! - **Confer** ([`build_birth_certificate`] + [`crate::server::state::ServerState::confer_citizenship`]):
//!   for entities born into THIS society (its members and roles), hestia records
//!   the birth certificate in its own **ledger** (the witness chain) once the
//!   quorum is met. Per dp (2026-07-16), a birth certificate is held by the ledger
//!   of the society the entity is born into, and *birth = coming to exist in that
//!   society's MRH* (an external entity joining as a citizen is birthed into this
//!   MRH — its citizenship certificate IS its birth certificate here). The
//!   sovereign's own citizenship is conferred by the HUB's ledger (the sovereign
//!   is a citizen of the hub, its parent society) — not here.
//!
//! What is NOT hestia's: the *relying party's* trust decision. A relying party
//! traverses the witness tree to whatever depth its risk appetite wants (the
//! IP-pending dev-hub traversal); web4/hestia give the tools (attestations,
//! quorum, ledger record) — the relying party uses them (LCT spec §1.2). Some
//! entities specialize as witnesses/notaries who traverse-and-cache or
//! witness-on-request; that is a service, not a gate.

use web4_core::{
    Attestation, AttestationType, BirthCertificate, BirthContext, PublicKey, BIRTH_WITNESS_QUORUM,
};

/// Sign an `Existence` attestation over `subject_lct_id` as `witness_lct_id`,
/// using this member's OPERATIONAL keypair (the channel key the registry
/// resolves — W1). `ts` is the observation time (the CLI passes `Utc::now`;
/// tests pass a fixed instant for determinism).
pub fn attest(
    subject_lct_id: &str,
    witness_lct_id: &str,
    ts: chrono::DateTime<chrono::Utc>,
    operational_keypair: &web4_core::crypto::KeyPair,
) -> Attestation {
    Attestation::sign(
        subject_lct_id,
        witness_lct_id,
        AttestationType::Existence,
        ts,
        operational_keypair,
    )
}

/// Filter `attestations` to the ones that genuinely count toward a birth quorum
/// for `subject_lct_id`: **Existence** type, **signature-valid** against the
/// witness's resolved pubkey, and **one per distinct witness** (the first valid
/// attestation from each witness; later ones from the same witness do not add to
/// the quorum — three signatures from one witness are not three witnesses).
///
/// `resolve_witness_pubkey` maps a witness LCT id → its bound key. A witness
/// whose key does not resolve is dropped (cannot verify ⇒ does not count) — the
/// same fail-closed posture as the web4-core birth-certificate validator.
pub fn valid_distinct_existence<'a, F>(
    subject_lct_id: &str,
    attestations: &'a [Attestation],
    resolve_witness_pubkey: F,
) -> Vec<&'a Attestation>
where
    F: Fn(&str) -> Option<PublicKey>,
{
    let mut seen = std::collections::BTreeSet::new();
    attestations
        .iter()
        .filter(|a| a.attestation_type == AttestationType::Existence)
        .filter(|a| {
            // distinct witness: keep only the first valid one per witness id
            resolve_witness_pubkey(&a.witness)
                .map(|pk| a.verify(subject_lct_id, &pk))
                .unwrap_or(false)
                && seen.insert(a.witness.clone())
        })
        .collect()
}

/// Whether a set of already-verified-distinct attestations meets the canon-
/// required birth quorum (≥3, [`web4_core::BIRTH_WITNESS_QUORUM`]).
pub fn quorum_reached(valid_distinct: &[&Attestation]) -> bool {
    valid_distinct.len() >= BIRTH_WITNESS_QUORUM
}

/// Assemble a [`BirthCertificate`] for `subject_lct_id` **iff** the attestations
/// meet the witness quorum. Returns the certificate paired with the exact
/// valid-distinct attestations that back it (the evidence to record alongside),
/// or `None` when the quorum is not met — **fail-closed**: a society does not
/// birth a citizen on fewer than three distinct witnesses.
///
/// Birth = *coming to exist in this society's MRH* (dp, 2026-07-16): the same act
/// whether the entity is minted here or an external entity joins as a citizen.
/// The certificate's authoritative home is the issuing society's LEDGER, not the
/// entity's LCT (see [`crate::server::state::ServerState::confer_citizenship`]).
pub fn build_birth_certificate<F>(
    subject_lct_id: &str,
    citizen_role: &str,
    issuing_society: &str,
    birth_context: Option<BirthContext>,
    attestations: &[Attestation],
    birth_timestamp: chrono::DateTime<chrono::Utc>,
    resolve_witness_pubkey: F,
) -> Option<(BirthCertificate, Vec<Attestation>)>
where
    F: Fn(&str) -> Option<PublicKey>,
{
    let valid = valid_distinct_existence(subject_lct_id, attestations, resolve_witness_pubkey);
    if !quorum_reached(&valid) {
        return None;
    }
    let cert = BirthCertificate {
        issuing_society: issuing_society.to_string(),
        citizen_role: citizen_role.to_string(),
        birth_witnesses: valid.iter().map(|a| a.witness.clone()).collect(),
        birth_timestamp,
        birth_context,
        genesis_block_hash: None,
    };
    let evidence = valid.into_iter().cloned().collect();
    Some((cert, evidence))
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::crypto::KeyPair;

    fn now() -> chrono::DateTime<chrono::Utc> {
        chrono::DateTime::UNIX_EPOCH.into()
    }

    #[test]
    fn attest_produces_a_verifiable_existence_attestation() {
        let kp = KeyPair::generate();
        let a = attest("lct:web4:mb32:bsubject", "lct:web4:member:legion", now(), &kp);
        assert_eq!(a.attestation_type, AttestationType::Existence);
        assert_eq!(a.witness, "lct:web4:member:legion");
        assert!(a.verify("lct:web4:mb32:bsubject", &kp.verifying_key()));
        // bound to THIS subject — a different subject's id does not verify
        assert!(!a.verify("lct:web4:mb32:bother", &kp.verifying_key()));
    }

    #[test]
    fn quorum_counts_distinct_valid_witnesses_only() {
        let subject = "lct:web4:mb32:bsubject";
        let w: Vec<KeyPair> = (0..3).map(|_| KeyPair::generate()).collect();
        let wid: Vec<String> = (0..3).map(|i| format!("lct:web4:member:w{i}")).collect();
        let resolver = {
            let w = w.iter().map(|k| k.verifying_key()).collect::<Vec<_>>();
            let wid = wid.clone();
            move |id: &str| wid.iter().position(|x| x == id).map(|i| w[i].clone())
        };

        // Two distinct witnesses + a DUPLICATE from w0 → still only 2 distinct.
        let mut atts = vec![
            attest(subject, &wid[0], now(), &w[0]),
            attest(subject, &wid[1], now(), &w[1]),
            attest(subject, &wid[0], now() + chrono::Duration::seconds(5), &w[0]),
        ];
        let vd = valid_distinct_existence(subject, &atts, &resolver);
        assert_eq!(vd.len(), 2, "duplicate witness does not add to the quorum");
        assert!(!quorum_reached(&vd));

        // Add the third distinct witness → quorum reached.
        atts.push(attest(subject, &wid[2], now(), &w[2]));
        let vd = valid_distinct_existence(subject, &atts, &resolver);
        assert_eq!(vd.len(), 3);
        assert!(quorum_reached(&vd));
    }

    #[test]
    fn build_birth_certificate_is_quorum_gated() {
        let subject = "lct:web4:mb32:bsubject";
        let w: Vec<KeyPair> = (0..3).map(|_| KeyPair::generate()).collect();
        let wid: Vec<String> = (0..3).map(|i| format!("lct:web4:member:w{i}")).collect();
        let resolver = {
            let ks: Vec<_> = w.iter().map(|k| k.verifying_key()).collect();
            let wid = wid.clone();
            move |id: &str| wid.iter().position(|x| x == id).map(|i| ks[i].clone())
        };
        // Two witnesses → below quorum → None (no birth on < 3 witnesses).
        let two = vec![attest(subject, &wid[0], now(), &w[0]), attest(subject, &wid[1], now(), &w[1])];
        assert!(build_birth_certificate(subject, "lct:web4:role:citizen", "lct:web4:society:hestia", None, &two, now(), &resolver).is_none());
        // Three distinct → Some(cert) naming exactly those witnesses.
        let three: Vec<_> = (0..3).map(|i| attest(subject, &wid[i], now(), &w[i])).collect();
        let (cert, evidence) = build_birth_certificate(subject, "lct:web4:role:citizen", "lct:web4:society:hestia", None, &three, now(), &resolver).unwrap();
        assert_eq!(cert.birth_witnesses.len(), 3);
        assert_eq!(cert.issuing_society, "lct:web4:society:hestia");
        assert_eq!(cert.citizen_role, "lct:web4:role:citizen");
        assert_eq!(evidence.len(), 3, "the backing attestations travel with the cert");
        assert!(cert.quorum_structurally_ok());
    }

    #[test]
    fn invalid_and_unresolvable_witnesses_do_not_count() {
        let subject = "lct:web4:mb32:bsubject";
        let good = KeyPair::generate();
        let forger = KeyPair::generate();
        // one valid, and one whose recorded witness id resolves to a DIFFERENT key
        let atts = vec![
            attest(subject, "lct:web4:member:good", now(), &good),
            // "forged": claims to be :good but signed by a different key
            Attestation::sign(subject, "lct:web4:member:good2", AttestationType::Existence, now(), &forger),
        ];
        // resolver returns good's key for :good, and nothing for :good2 (unknown)
        let resolver = |id: &str| (id == "lct:web4:member:good").then(|| good.verifying_key());
        let vd = valid_distinct_existence(subject, &atts, resolver);
        assert_eq!(vd.len(), 1, "unresolvable witness is dropped");
        assert!(!quorum_reached(&vd));
    }
}
