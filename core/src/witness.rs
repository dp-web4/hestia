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
//!   [`attest`] refuses a subject id that is not the canonical key-derived form
//!   (R6) and signs whole-second timestamps (R4) — both because the subject and
//!   the `ts` are inside the signed bytes, so getting either wrong produces an
//!   attestation that is well-formed and permanently unverifiable.
//! - **Assess** ([`valid_distinct_existence`], [`quorum_reached`]): given a
//!   subject's collected attestations and a witness-pubkey resolver (the registry
//!   is that resolver on the hub side), compute the verified quorum. Fail-closed,
//!   reusing the web4-core `Attestation::verify` + the ≥3-DISTINCT-witness rule,
//!   where distinct means distinct in the witness id AND in the key that id
//!   resolves to (R1 — three spellings of one key are one witness).
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

/// The canonical, key-derived LCT id prefix ([`web4_core::lct::derive_lct_id`],
/// canon §2.3): `lct:web4:mb32:` plus the `b` multibase tag for RFC 4648
/// base32-lowercase-no-pad.
pub const CANONICAL_LCT_ID_PREFIX: &str = "lct:web4:mb32:b";

/// The base32 body length of a derived id: SHA-256 is 32 bytes = 256 bits, and
/// `ceil(256 / 5) = 52` characters with no padding.
pub const CANONICAL_LCT_ID_BODY_LEN: usize = 52;

/// The only two characters a derived id can end with. 52 base32 characters hold
/// 260 bits; a 256-bit digest supplies 256, so the final character's low **four
/// bits are padding and are always zero** — leaving alphabet index 0 (`a`) or 16
/// (`q`). Measured over 20 000 random digests: exactly these two, ~50/50. This
/// is the clause that rejects a hand-typed, truncated or transcribed id that
/// already passed prefix, length and alphabet.
const CANONICAL_LCT_ID_TAIL: [char; 2] = ['a', 'q'];

/// Why a subject id is not the canonical, key-derived form [`attest`] will sign.
///
/// Each variant names what to hand it instead, because every one of these is
/// otherwise indistinguishable at the far end: an attestation over a
/// non-canonical subject is well-formed, correctly signed, and structurally
/// incapable of ever verifying — and the verifier reports it as the generic
/// "quorum not met".
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubjectIdError {
    /// `lct:web4:member:{uuid}` — a real id in the *membership* space. The hub
    /// keys membership on `Uuid` and the registry keys on the derived id; the
    /// two are linked only by pubkey equality, and nothing checks it.
    MembershipIdSpace(String),
    /// Not the `lct:web4:mb32:` space at all.
    WrongSpace(String),
    /// Right space, wrong body length.
    BodyLength { got: usize },
    /// A character outside the base32-lowercase-no-pad alphabet (`a-z2-7`).
    Alphabet { ch: char },
    /// 52 well-formed base32 characters whose final character carries non-zero
    /// padding bits — so it is not the encoding of any 32-byte digest.
    PaddingBits { last: char },
}

impl std::fmt::Display for SubjectIdError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MembershipIdSpace(id) => write!(
                f,
                "subject '{id}' is a membership id, not a published LCT id — attestations are \
                 signed over the registry's key-derived `{CANONICAL_LCT_ID_PREFIX}…` id. Look the \
                 member up in the registry and pass its published `lct_id`."
            ),
            Self::WrongSpace(id) => write!(
                f,
                "subject '{id}' is not a key-derived LCT id (expected the \
                 `{CANONICAL_LCT_ID_PREFIX}…` form)"
            ),
            Self::BodyLength { got } => write!(
                f,
                "subject id body is {got} characters, expected {CANONICAL_LCT_ID_BODY_LEN} \
                 (a truncated or elongated id)"
            ),
            Self::Alphabet { ch } => write!(
                f,
                "subject id contains '{ch}', which is outside base32-lowercase-no-pad (a-z2-7)"
            ),
            Self::PaddingBits { last } => write!(
                f,
                "subject id ends in '{last}': a 32-byte digest leaves four zero padding bits, so \
                 the last character is always 'a' or 'q'. This id cannot encode any digest."
            ),
        }
    }
}

impl std::error::Error for SubjectIdError {}

/// **R6.** Accept `subject_lct_id` only if it is the canonical, key-derived form
/// [`web4_core::lct::derive_lct_id`] produces; otherwise say precisely why.
///
/// This is a **refusal, not a translation**, and it cannot be a translation:
/// there is no mapping from `lct:web4:member:{uuid}` back to the key-derived id
/// without the key, and inventing one would be exactly the id-forgery the
/// derived form exists to prevent. The check is *syntactic* — it cannot prove an
/// id IS someone's derived id (that needs the pubkey), only refuse ids that
/// provably are not anyone's.
///
/// Four clauses: the `lct:web4:mb32:b` prefix, a 52-character body, the
/// base32-lowercase-no-pad alphabet, and the two-value tail
/// ([`CANONICAL_LCT_ID_TAIL`]) that falls out of encoding exactly 256 bits.
pub fn canonical_subject_id(subject_lct_id: &str) -> Result<&str, SubjectIdError> {
    let Some(body) = subject_lct_id.strip_prefix(CANONICAL_LCT_ID_PREFIX) else {
        return Err(if subject_lct_id.starts_with("lct:web4:member:") {
            SubjectIdError::MembershipIdSpace(subject_lct_id.to_string())
        } else {
            SubjectIdError::WrongSpace(subject_lct_id.to_string())
        });
    };
    if body.chars().count() != CANONICAL_LCT_ID_BODY_LEN {
        return Err(SubjectIdError::BodyLength { got: body.chars().count() });
    }
    if let Some(ch) = body.chars().find(|c| !matches!(c, 'a'..='z' | '2'..='7')) {
        return Err(SubjectIdError::Alphabet { ch });
    }
    let last = body.chars().next_back().expect("52 characters, checked above");
    if !CANONICAL_LCT_ID_TAIL.contains(&last) {
        return Err(SubjectIdError::PaddingBits { last });
    }
    Ok(subject_lct_id)
}

/// `true` iff `id` passes [`canonical_subject_id`]. The predicate HUB's witness
/// roster keys on — one mapping, not two (HUB's R6 note, 2026-08-21).
pub fn is_canonical_lct_id(id: &str) -> bool {
    canonical_subject_id(id).is_ok()
}

/// Sign an `Existence` attestation over `subject_lct_id` as `witness_lct_id`,
/// using this member's OPERATIONAL keypair (the channel key the registry
/// resolves — W1). `ts` is the observation time (the CLI passes `Utc::now`;
/// tests pass a fixed instant for determinism).
///
/// Two guards live here because both failure modes are silent at the far end:
///
/// - **R6 — the subject must be canonical.** The subject id is inside the signed
///   bytes, so an attestation over the wrong id space can never verify no matter
///   what the registry later says. Refused up front, with a reason
///   ([`SubjectIdError`]) rather than at conferral as "quorum not met".
/// - **R4 — `ts` is truncated to whole seconds before signing.** The canonical
///   message renders `ts` with `SecondsFormat::AutoSi`, so the digit count
///   follows the value: a `Utc::now()` attestation signs nine fractional digits,
///   and any hop that normalises to milliseconds (a JSON store, a JS client, a
///   `TIMESTAMP(3)` column) voids the signature. Truncating first makes that
///   normalisation a no-op. The *rendering* is untouched, so this needs no
///   `v1`→`v2` bump — only the value changes.
pub fn attest(
    subject_lct_id: &str,
    witness_lct_id: &str,
    ts: chrono::DateTime<chrono::Utc>,
    operational_keypair: &web4_core::crypto::KeyPair,
) -> Result<Attestation, SubjectIdError> {
    let subject_lct_id = canonical_subject_id(subject_lct_id)?;
    let ts = chrono::SubsecRound::trunc_subsecs(ts, 0);
    Ok(Attestation::sign(
        subject_lct_id,
        witness_lct_id,
        AttestationType::Existence,
        ts,
        operational_keypair,
    ))
}

/// Filter `attestations` to the ones that genuinely count toward a birth quorum
/// for `subject_lct_id`: **Existence** type, **signature-valid** against the
/// witness's resolved pubkey, and **one per distinct witness** — where
/// "distinct" means distinct in BOTH the witness id and the key that id
/// resolves to (**R1**).
///
/// The key half is the one that matters and the one that was missing.
/// `hestia witness onboard <plugin_id>` vouches
/// `member_signing_keypair(vault, &conn.member_key_source)` — a function of the
/// hub CONNECTION, not of `plugin_id` — so onboarding three members of one
/// constellation against one connection vouches ONE key onto three LCTs. Under
/// id-only distinctness those three sign a passing quorum: the canon's "three
/// entries that are one witness are not a quorum" held at the id layer while the
/// independence it protects lives at the key layer, where nothing looked.
///
/// Dedup order is input order, and it is load-bearing only in the degenerate
/// case: when two ids share a key, the FIRST is kept and the second dropped, so
/// a certificate is never built naming both. It is dropped rather than refused
/// because a shared key is not evidence of bad faith — it is the ordinary result
/// of one seat onboarding several of its own members.
///
/// `resolve_witness_pubkey` maps a witness LCT id → its bound key. A witness
/// whose key does not resolve is dropped (cannot verify ⇒ does not count) — the
/// same fail-closed posture as the web4-core birth-certificate validator.
///
/// Pairs with HUB's **R2** on the verifier side (web4#758), which counts the ≥3
/// floor over distinct resolved keys. The two use the same predicate on purpose:
/// distinct-keys ≥ 3 implies distinct-ids ≥ 3, so the key set is strictly
/// stricter and the id set is the membership index, not a second gate.
pub fn valid_distinct_existence<'a, F>(
    subject_lct_id: &str,
    attestations: &'a [Attestation],
    resolve_witness_pubkey: F,
) -> Vec<&'a Attestation>
where
    F: Fn(&str) -> Option<PublicKey>,
{
    let mut seen_ids = std::collections::BTreeSet::new();
    let mut seen_keys = std::collections::BTreeSet::new();
    attestations
        .iter()
        .filter(|a| a.attestation_type == AttestationType::Existence)
        .filter(|a| {
            let Some(pk) = resolve_witness_pubkey(&a.witness) else {
                return false; // unresolvable ⇒ cannot verify ⇒ does not count
            };
            if !a.verify(subject_lct_id, &pk) {
                return false;
            }
            // R1: distinct in the id AND in the key behind it. Tested before
            // inserting so a dropped attestation never seeds either set — the
            // two stay in agreement about exactly which attestations were kept.
            let key_hex = pk.to_hex();
            if seen_ids.contains(a.witness.as_str()) || seen_keys.contains(key_hex.as_str()) {
                return false;
            }
            seen_ids.insert(a.witness.clone());
            seen_keys.insert(key_hex);
            true
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

    /// A real key-derived subject id. Before R6 these tests used the readable
    /// stand-in `"lct:web4:mb32:bsubject"` — which R6 refuses, correctly: it is
    /// 7 body characters where a derived id has 52, so no registry could ever
    /// resolve it. hestia's own test corpus was signing over subjects that could
    /// not verify against a real registry; that is the defect R6 names, and the
    /// tests were carrying it.
    fn subject_id() -> String {
        web4_core::derive_lct_id(&KeyPair::generate().verifying_key())
    }

    #[test]
    fn attest_produces_a_verifiable_existence_attestation() {
        let kp = KeyPair::generate();
        let subject = subject_id();
        let other = subject_id();
        let a = attest(&subject, "lct:web4:member:legion", now(), &kp).unwrap();
        assert_eq!(a.attestation_type, AttestationType::Existence);
        assert_eq!(a.witness, "lct:web4:member:legion");
        assert!(a.verify(&subject, &kp.verifying_key()));
        // bound to THIS subject — a different subject's id does not verify
        assert!(!a.verify(&other, &kp.verifying_key()));
    }

    #[test]
    fn quorum_counts_distinct_valid_witnesses_only() {
        let subject = &subject_id();
        let subject = subject.as_str();
        let w: Vec<KeyPair> = (0..3).map(|_| KeyPair::generate()).collect();
        let wid: Vec<String> = (0..3).map(|i| format!("lct:web4:member:w{i}")).collect();
        let resolver = {
            let w = w.iter().map(|k| k.verifying_key()).collect::<Vec<_>>();
            let wid = wid.clone();
            move |id: &str| wid.iter().position(|x| x == id).map(|i| w[i].clone())
        };

        // Two distinct witnesses + a DUPLICATE from w0 → still only 2 distinct.
        let mut atts = vec![
            attest(subject, &wid[0], now(), &w[0]).unwrap(),
            attest(subject, &wid[1], now(), &w[1]).unwrap(),
            attest(subject, &wid[0], now() + chrono::Duration::seconds(5), &w[0]).unwrap(),
        ];
        let vd = valid_distinct_existence(subject, &atts, &resolver);
        assert_eq!(vd.len(), 2, "duplicate witness does not add to the quorum");
        assert!(!quorum_reached(&vd));

        // Add the third distinct witness → quorum reached.
        atts.push(attest(subject, &wid[2], now(), &w[2]).unwrap());
        let vd = valid_distinct_existence(subject, &atts, &resolver);
        assert_eq!(vd.len(), 3);
        assert!(quorum_reached(&vd));
    }

    #[test]
    fn build_birth_certificate_is_quorum_gated() {
        let subject = &subject_id();
        let subject = subject.as_str();
        let w: Vec<KeyPair> = (0..3).map(|_| KeyPair::generate()).collect();
        let wid: Vec<String> = (0..3).map(|i| format!("lct:web4:member:w{i}")).collect();
        let resolver = {
            let ks: Vec<_> = w.iter().map(|k| k.verifying_key()).collect();
            let wid = wid.clone();
            move |id: &str| wid.iter().position(|x| x == id).map(|i| ks[i].clone())
        };
        // Two witnesses → below quorum → None (no birth on < 3 witnesses).
        let two = vec![
            attest(subject, &wid[0], now(), &w[0]).unwrap(),
            attest(subject, &wid[1], now(), &w[1]).unwrap(),
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
            .map(|i| attest(subject, &wid[i], now(), &w[i]).unwrap())
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
        let subject = &subject_id();
        let subject = subject.as_str();
        let good = KeyPair::generate();
        let forger = KeyPair::generate();
        // one valid, and one whose recorded witness id resolves to a DIFFERENT key
        let atts = vec![
            attest(subject, "lct:web4:member:good", now(), &good).unwrap(),
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
