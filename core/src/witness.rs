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
    Attestation, AttestationType, BIRTH_WITNESS_QUORUM, BirthCertificate, BirthContext, PublicKey,
};

/// The `OperationalKey::purpose` under which a member vouches the key it signs
/// witness attestations with. Named once here because the literal is load-bearing
/// across a repo boundary and fails SILENTLY when it drifts: `verify_quorum`'s
/// `resolve_witness_pubkey` is caller-supplied, so a resolver that looks up the
/// wrong purpose resolves `None` for every witness and the quorum reports
/// "not met" — indistinguishable from "not enough siblings answered". web4-core's
/// own doc comment and tests spell it `"witness"`; every key hestia has actually
/// published spells it `"witnessing"`. This constant is hestia's half; the
/// cross-repo fix is to export it from web4-core (the shared-derivation
/// discipline already used for `derive_lct_id` and `opkey_message`, and for the
/// same reason).
pub const WITNESS_KEY_PURPOSE: &str = "witnessing";

/// An OFFLINE, self-authenticating resolver of witness signing keys.
///
/// A witness's canonical id is a commitment to its binding key
/// (`derive_lct_id(public_key)`), so a witness LCT document authenticates
/// *itself*: no registry lookup and no network round-trip is needed to know that
/// a document belongs to the id it claims. That is what makes the witness tree
/// independently traversable (LCT spec §1.2; operational-key vouching, dp ruling
/// (b) 2026-07-18) — a relying party checks evidence rather than asking an oracle.
///
/// **Fail-closed at admission.** A document is admitted only when all three hold:
///  1. its id re-derives from its own binding key (self-authenticating),
///  2. its `binding_proof` verifies (the key actually claims this LCT), and
///  3. it carries a vouched [`WITNESS_KEY_PURPOSE`] operational key — and
///     `operational_key_for` checks that vouch against the binding key, so a
///     tampered or foreign-signed vouch does not resolve.
///
/// A document failing any of these lands in [`WitnessSet::rejected`] with its
/// reason rather than being silently dropped: an unresolvable witness is a fact
/// the operator should see, the same posture as `lct_publish::PublishSet::refused`.
#[derive(Debug, Default)]
pub struct WitnessSet {
    keys: std::collections::BTreeMap<String, PublicKey>,
    /// `(claimed id or label, why it was not admitted)` — never silently empty.
    pub rejected: Vec<(String, String)>,
}

impl WitnessSet {
    /// Admit witness LCT documents, checking each against the three rules above.
    /// `label` is only used to name a document in [`WitnessSet::rejected`] when it
    /// is too malformed to have a trustworthy id of its own.
    pub fn from_documents<I>(documents: I) -> Self
    where
        I: IntoIterator<Item = (String, web4_core::Lct)>,
    {
        let mut set = WitnessSet::default();
        for (label, lct) in documents {
            // The id is COMPUTED from the binding key, never carried, so there
            // is nothing to compare it against — a forged id is not expressible.
            // What must still be proven is that the key claims this LCT, and
            // `binding_proof` signs over exactly this derived id
            // (`Lct::binding_message`). Until that verifies the document has no
            // id we may attribute it by, so `label` names it in the refusal.
            let derived = web4_core::derive_lct_id(&lct.public_key);
            if !lct.verify_binding() {
                set.rejected.push((
                    label,
                    format!("binding_proof absent or invalid (would-be witness {derived})"),
                ));
                continue;
            }
            match lct.operational_key_for(WITNESS_KEY_PURPOSE) {
                Some(pk) => {
                    set.keys.insert(derived, pk);
                }
                None => set.rejected.push((
                    derived,
                    format!(
                        "no vouched `{WITNESS_KEY_PURPOSE}` operational key resolves \
                         (never onboarded, or the vouch does not verify against its binding key) \
                         — run `hestia witness onboard <plugin_id>` on that seat, then `hestia lct publish --send`"
                    ),
                )),
            }
        }
        set
    }

    /// The resolver to hand to [`valid_distinct_existence`] / `confer_citizenship`.
    pub fn resolver(&self) -> impl Fn(&str) -> Option<PublicKey> + '_ {
        move |witness_id: &str| self.keys.get(witness_id).cloned()
    }

    /// Canonical ids of the admitted witnesses, for reporting.
    pub fn admitted(&self) -> Vec<&str> {
        self.keys.keys().map(String::as_str).collect()
    }
}

/// Why a quorum did not form — the legible half of a fail-closed refusal.
///
/// `build_birth_certificate` returns a bare `None`, which is correct for the
/// decision and useless for the operator: "quorum not met" reads identically
/// whether three witnesses never answered, or three answered and none of their
/// keys resolved. This splits those apart so the failure names its own cause.
#[derive(Debug)]
pub struct QuorumReport {
    pub attestations_supplied: usize,
    pub wrong_type: usize,
    pub unresolved_witness: Vec<String>,
    pub bad_signature: Vec<String>,
    pub duplicate_witness: Vec<String>,
    pub distinct_valid: Vec<String>,
}

impl QuorumReport {
    /// Classify every supplied attestation against the same rules
    /// [`valid_distinct_existence`] applies — a diagnostic mirror, not a second
    /// source of truth. `distinct_valid.len()` equals that function's output length.
    pub fn assess<F>(subject_lct_id: &str, attestations: &[Attestation], resolve: F) -> Self
    where
        F: Fn(&str) -> Option<PublicKey>,
    {
        let mut r = QuorumReport {
            attestations_supplied: attestations.len(),
            wrong_type: 0,
            unresolved_witness: Vec::new(),
            bad_signature: Vec::new(),
            duplicate_witness: Vec::new(),
            distinct_valid: Vec::new(),
        };
        let mut seen = std::collections::BTreeSet::new();
        for a in attestations {
            if a.attestation_type != AttestationType::Existence {
                r.wrong_type += 1;
                continue;
            }
            let Some(pk) = resolve(&a.witness) else {
                r.unresolved_witness.push(a.witness.clone());
                continue;
            };
            if !a.verify(subject_lct_id, &pk) {
                r.bad_signature.push(a.witness.clone());
                continue;
            }
            if !seen.insert(a.witness.clone()) {
                r.duplicate_witness.push(a.witness.clone());
                continue;
            }
            r.distinct_valid.push(a.witness.clone());
        }
        r
    }

    pub fn quorum_met(&self) -> bool {
        self.distinct_valid.len() >= BIRTH_WITNESS_QUORUM
    }

    /// Operator-facing explanation, ending in the shortfall as a number.
    pub fn explain(&self) -> String {
        let mut out = format!(
            "{} attestation(s) supplied; {} distinct valid of {BIRTH_WITNESS_QUORUM} required",
            self.attestations_supplied,
            self.distinct_valid.len()
        );
        if self.wrong_type > 0 {
            out.push_str(&format!("\n  {} not of type Existence", self.wrong_type));
        }
        for w in &self.unresolved_witness {
            out.push_str(&format!("\n  witness key did not resolve: {w}"));
        }
        for w in &self.bad_signature {
            out.push_str(&format!("\n  signature did not verify: {w}"));
        }
        for w in &self.duplicate_witness {
            out.push_str(&format!(
                "\n  duplicate — a second attestation from {w} adds nothing (distinct witnesses, not distinct signatures)"
            ));
        }
        out
    }
}

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

    /// A witness seat as it exists in reality: a custodial LCT whose binding key
    /// is vault-sealed, vouching a SEPARATE operational key (the channel key a
    /// systemd service can actually reach — `e0d54a9`'s constraint).
    fn witness_seat() -> (web4_core::Lct, KeyPair, String) {
        let (mut lct, binding) = web4_core::Lct::new(web4_core::EntityType::AiSoftware, None);
        lct.sign_binding(&binding);
        let operational = KeyPair::generate();
        lct.authorize_operational_key(WITNESS_KEY_PURPOSE, operational.verifying_key(), &binding);
        let id = lct.lct_id();
        (lct, operational, id)
    }

    #[test]
    fn witness_set_resolves_the_vouched_operational_key_not_the_binding_key() {
        let (lct, operational, id) = witness_seat();
        let binding_key = lct.public_key.clone();
        let set = WitnessSet::from_documents([("w0".to_string(), lct)]);

        assert!(set.rejected.is_empty(), "{:?}", set.rejected);
        assert_eq!(set.admitted(), vec![id.as_str()]);

        let resolved = (set.resolver())(&id).expect("witness resolves");
        assert_eq!(
            resolved,
            operational.verifying_key(),
            "the OPERATIONAL key signs attestations — a resolver returning the \
             binding key rejects every autonomous witness (e0d54a9's failure, one layer up)"
        );
        assert_ne!(resolved, binding_key);
    }

    #[test]
    fn witness_set_is_fail_closed_and_says_why() {
        // (a) never onboarded — no vouched witnessing key at all.
        let (mut bare, binding) = web4_core::Lct::new(web4_core::EntityType::AiSoftware, None);
        bare.sign_binding(&binding);

        // (b) onboarded under the WRONG purpose string. This is the silent
        // cross-repo drift the constant exists to prevent: the document looks
        // complete and resolves to nothing.
        let (mut wrong, wbinding) = web4_core::Lct::new(web4_core::EntityType::AiSoftware, None);
        wrong.sign_binding(&wbinding);
        let op = KeyPair::generate();
        wrong.authorize_operational_key("witness", op.verifying_key(), &wbinding);

        // (c) unproven binding — the key never claimed this LCT.
        let (unbound, _) = web4_core::Lct::new(web4_core::EntityType::AiSoftware, None);

        let set = WitnessSet::from_documents([
            ("bare".to_string(), bare),
            ("wrong-purpose".to_string(), wrong),
            ("unbound".to_string(), unbound),
        ]);
        assert!(set.admitted().is_empty(), "none of these may witness");
        assert_eq!(
            set.rejected.len(),
            3,
            "every refusal is reported, none dropped"
        );
        assert!(
            set.rejected.iter().any(|(who, _)| who == "unbound"),
            "an unbindable document is named by its label, not by an id we cannot attribute"
        );
    }

    #[test]
    fn quorum_report_separates_no_answer_from_no_resolution() {
        let subject = "lct:web4:mb32:bsubject";
        let seats: Vec<_> = (0..3).map(|_| witness_seat()).collect();
        let atts: Vec<_> = seats
            .iter()
            .map(|(_, op, id)| attest(subject, id, now(), op))
            .collect();

        // Three real attestations, but NO witness documents supplied: every key
        // fails to resolve. `build_birth_certificate` would report a bare None,
        // identical to "nobody answered". The report distinguishes them.
        let empty = WitnessSet::default();
        let r = QuorumReport::assess(subject, &atts, empty.resolver());
        assert!(!r.quorum_met());
        assert_eq!(r.attestations_supplied, 3);
        assert_eq!(r.unresolved_witness.len(), 3);
        assert!(r.distinct_valid.is_empty());
        assert!(r.explain().contains("did not resolve"));

        // Same attestations, witnesses now resolvable → quorum, and the report
        // agrees with the authority it mirrors.
        let set =
            WitnessSet::from_documents(seats.iter().map(|(l, _, id)| (id.clone(), l.clone())));
        let r = QuorumReport::assess(subject, &atts, set.resolver());
        assert!(r.quorum_met());
        assert_eq!(r.distinct_valid.len(), BIRTH_WITNESS_QUORUM);
        assert_eq!(
            valid_distinct_existence(subject, &atts, set.resolver()).len(),
            r.distinct_valid.len(),
            "the diagnostic must never disagree with the decision it explains"
        );
    }

    #[test]
    fn quorum_report_names_duplicates_and_bad_signatures() {
        let subject = "lct:web4:mb32:bsubject";
        let seats: Vec<_> = (0..2).map(|_| witness_seat()).collect();
        let set =
            WitnessSet::from_documents(seats.iter().map(|(l, _, id)| (id.clone(), l.clone())));

        let mut atts = vec![
            attest(subject, &seats[0].2, now(), &seats[0].1),
            // a SECOND signature from seat 0 — not a second witness
            attest(
                subject,
                &seats[0].2,
                now() + chrono::Duration::seconds(5),
                &seats[0].1,
            ),
        ];
        // seat 1 attests a DIFFERENT subject, then claims it covers this one
        atts.push(attest(
            "lct:web4:mb32:bother",
            &seats[1].2,
            now(),
            &seats[1].1,
        ));

        let r = QuorumReport::assess(subject, &atts, set.resolver());
        assert_eq!(r.distinct_valid.len(), 1);
        assert_eq!(r.duplicate_witness.len(), 1);
        assert_eq!(
            r.bad_signature.len(),
            1,
            "an attestation over another subject does not transfer"
        );
        assert!(!r.quorum_met());
    }

    #[test]
    fn attest_produces_a_verifiable_existence_attestation() {
        let kp = KeyPair::generate();
        let a = attest(
            "lct:web4:mb32:bsubject",
            "lct:web4:member:legion",
            now(),
            &kp,
        );
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
            attest(
                subject,
                &wid[0],
                now() + chrono::Duration::seconds(5),
                &w[0],
            ),
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
        let two = vec![
            attest(subject, &wid[0], now(), &w[0]),
            attest(subject, &wid[1], now(), &w[1]),
        ];
        assert!(
            build_birth_certificate(
                subject,
                "lct:web4:role:citizen",
                "lct:web4:society:hestia",
                None,
                &two,
                now(),
                &resolver
            )
            .is_none()
        );
        // Three distinct → Some(cert) naming exactly those witnesses.
        let three: Vec<_> = (0..3)
            .map(|i| attest(subject, &wid[i], now(), &w[i]))
            .collect();
        let (cert, evidence) = build_birth_certificate(
            subject,
            "lct:web4:role:citizen",
            "lct:web4:society:hestia",
            None,
            &three,
            now(),
            &resolver,
        )
        .unwrap();
        assert_eq!(cert.birth_witnesses.len(), 3);
        assert_eq!(cert.issuing_society, "lct:web4:society:hestia");
        assert_eq!(cert.citizen_role, "lct:web4:role:citizen");
        assert_eq!(
            evidence.len(),
            3,
            "the backing attestations travel with the cert"
        );
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
            Attestation::sign(
                subject,
                "lct:web4:member:good2",
                AttestationType::Existence,
                now(),
                &forger,
            ),
        ];
        // resolver returns good's key for :good, and nothing for :good2 (unknown)
        let resolver = |id: &str| (id == "lct:web4:member:good").then(|| good.verifying_key());
        let vd = valid_distinct_existence(subject, &atts, resolver);
        assert_eq!(vd.len(), 1, "unresolvable witness is dropped");
        assert!(!quorum_reached(&vd));
    }
}
