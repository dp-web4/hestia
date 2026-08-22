//! What `CitizenshipRecord::verify_quorum` ACTUALLY accepts, measured against
//! what hestia's producer (`witness::attest` / `build_birth_certificate` /
//! `ServerState::confer_citizenship`) actually emits.
//!
//! M-CIT-3 turns on the producer and the verifier agreeing byte for byte. They
//! are in different repos, so nothing compiles the agreement — the contract is
//! prose in two doc comments. These are **characterization tests**: they assert
//! today's behaviour, including the parts that are wrong, so that the wrongness
//! is reproducible instead of remembered. Each one names which way it should
//! move. Written before the fix, deliberately: a spec delta whose measurements
//! nobody can re-run is a claim, not evidence.
//!
//! The five clauses `verify_quorum` enforces (web4-core `attestation.rs`):
//!   1. only `Existence` attestations count
//!   2. `resolve_witness_pubkey(a.witness)` must return a key (else dropped)
//!   3. the signature must verify over `(subject_lct_id, type, ts)`
//!   4. ≥3 **distinct** witnesses — distinct by the `witness` STRING (C1 below)
//!   5. every DECLARED birth witness must be currently verifiable (C2 below)
//!
//! ## Status after the R2/R3/R5 ruling (HUB, 2026-08-21; web4#758)
//!
//! Three of these have moved from "measured wrong" to "fixed on the producer
//! side", and the assertions below moved with them — which is the entire point
//! of having written them first:
//!
//! - **C1 → R1.** `valid_distinct_existence` now dedups on the resolved KEY as
//!   well as the id, so the three-spellings-of-one-key certificate is no longer
//!   built. HUB's R2 makes the verifier count the same way (web4-core, theirs).
//! - **C3 → R4.** `witness::attest` truncates `ts` to whole seconds before
//!   signing, so a millisecond hop is a no-op.
//! - **C5 → R6.** `witness::attest` refuses a subject id that is not the
//!   canonical key-derived form, with a reason.
//!
//! **C2 and C4 are unchanged and still measure today's behaviour**, because both
//! land in web4-core and neither is hestia's to fix: C2 is R3′ (HUB's ruling
//! adopted the intent and revised the spelling; the canon call is dp's) and C4
//! is R5 (`WITNESS_KEY_PURPOSE`, HUB's to export). They stay red-in-prose on
//! purpose — when those ship, these two assertions are the ones that flip.

use chrono::{TimeZone, Utc};
use web4_core::crypto::KeyPair;
use web4_core::lct::{EntityType, Lct};
use web4_core::{Attestation, CitizenshipRecord, PublicKey};

/// The purpose string hestia vouches under (`member_registry::vouch_witnessing_key`).
/// Test-local on purpose: it is a bare literal in both repos today, which is the
/// whole of C4. When `WITNESS_KEY_PURPOSE` is exported, this becomes an import.
const HESTIA_WITNESS_PURPOSE: &str = "witnessing";

fn subject() -> String {
    Lct::new(EntityType::AiSoftware, None).0.lct_id()
}

fn fixed_ts() -> chrono::DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 8, 21, 12, 0, 0).unwrap()
}

/// A member LCT with `op` vouched as its operational witnessing key — the state
/// `hestia witness onboard <plugin_id>` leaves behind.
fn onboarded(op: &KeyPair) -> (Lct, KeyPair) {
    let (mut lct, binding) = Lct::new(EntityType::AiSoftware, None);
    lct.authorize_operational_key(HESTIA_WITNESS_PURPOSE, op.verifying_key(), &binding);
    (lct, binding)
}

/// Resolve a witness id against a registry snapshot, exactly as a hub-side
/// resolver would: id → LCT → vouched operational key.
fn resolver(registry: &[Lct]) -> impl Fn(&str) -> Option<PublicKey> + '_ {
    move |wid: &str| {
        registry
            .iter()
            .find(|m| m.lct_id() == wid)
            .and_then(|m| m.operational_key_for(HESTIA_WITNESS_PURPOSE))
    }
}

/// **C1 — distinctness is over the witness ID STRING, not the signing KEY.**
///
/// `hestia witness onboard <plugin_id>` vouches
/// `member_signing_keypair(vault, &conn.member_key_source)` — a function of the
/// hub CONNECTION, not of `plugin_id`. Onboarding three members of one
/// constellation against one connection therefore vouches ONE key onto three
/// LCTs, and `witness attest --as` signs all three with it. Three witness ids,
/// one signer, quorum met: the canon's "three entries that are one witness are
/// not a quorum" holds at the id layer and not at the key layer, where the
/// independence it is protecting actually lives.
///
/// **FIXED — R1** (this commit). `valid_distinct_existence` keeps two sets, an
/// id set and a resolved-key set, and drops an attestation whose key has already
/// counted. The producer no longer builds this certificate at all: the assertion
/// below is now that `build_birth_certificate` returns `None`. HUB's R2
/// (web4#758) makes the verifier count the ≥3 floor over distinct keys, so an
/// already-issued certificate of this shape is caught too.
///
/// There is no installed base to invalidate — 1 of 23 registry LCTs carries a
/// vouched witnessing key and the quorum needs 3, so zero conferred records
/// exist. The hazard converts from "verifies as theatre" to "fails at conferral".
#[test]
fn c1_three_witness_ids_backed_by_one_key_are_no_longer_a_quorum() {
    let sid = subject();
    let ts = fixed_ts();
    let shared_op = KeyPair::generate();
    let registry: Vec<Lct> = (0..3).map(|_| onboarded(&shared_op).0).collect();
    let atts: Vec<Attestation> = registry
        .iter()
        .map(|m| hestia::witness::attest(&sid, &m.lct_id(), ts, &shared_op).unwrap())
        .collect();

    // Each attestation is individually valid: right type, resolvable witness,
    // signature verifies. Only their independence is fictional.
    let distinct_ids: std::collections::BTreeSet<&str> =
        atts.iter().map(|a| a.witness.as_str()).collect();
    let distinct_keys: std::collections::BTreeSet<String> = atts
        .iter()
        .filter_map(|a| resolver(&registry)(&a.witness).map(|k| k.to_hex()))
        .collect();
    assert_eq!(distinct_ids.len(), 3, "three distinct witness ids");
    assert_eq!(distinct_keys.len(), 1, "backed by exactly one signing key");
    assert!(
        atts.iter().all(|a| resolver(&registry)(&a.witness)
            .map(|k| a.verify(&sid, &k))
            .unwrap_or(false)),
        "every attestation verifies on its own"
    );

    let counted = hestia::witness::valid_distinct_existence(&sid, &atts, resolver(&registry));
    assert_eq!(counted.len(), 1, "R1: one key counts once, whatever it is called");

    assert!(
        hestia::witness::build_birth_certificate(
            &sid,
            "lct:web4:role:citizen",
            "lct:web4:society:test",
            None,
            &atts,
            ts,
            resolver(&registry),
        )
        .is_none(),
        "R1: the producer refuses to birth a citizen on three spellings of one key"
    );
}

/// **R1, the non-degenerate half.** The fix must not cost a real quorum. Three
/// genuinely independent witnesses still confer, and a fourth attestation that
/// duplicates one of their KEYS under a fresh id is the only thing dropped.
#[test]
fn r1_independent_witnesses_still_confer_and_only_the_twin_is_dropped() {
    let sid = subject();
    let ts = fixed_ts();
    let ops: Vec<KeyPair> = (0..3).map(|_| KeyPair::generate()).collect();
    let mut registry: Vec<Lct> = ops.iter().map(|op| onboarded(op).0).collect();
    let mut atts: Vec<Attestation> = registry
        .iter()
        .zip(&ops)
        .map(|(m, op)| hestia::witness::attest(&sid, &m.lct_id(), ts, op).unwrap())
        .collect();

    // A fourth member of the same seat as ops[0] — a second `witness onboard`
    // against one hub connection vouches the SAME key onto a new LCT.
    let twin = onboarded(&ops[0]).0;
    let twin_id = twin.lct_id();
    registry.push(twin);
    atts.push(hestia::witness::attest(&sid, &twin_id, ts, &ops[0]).unwrap());

    let (certificate, attestations) = hestia::witness::build_birth_certificate(
        &sid,
        "lct:web4:role:citizen",
        "lct:web4:society:test",
        None,
        &atts,
        ts,
        resolver(&registry),
    )
    .expect("three independent witnesses are still a quorum");

    assert_eq!(certificate.birth_witnesses.len(), 3, "the twin did not inflate the count");
    assert!(
        !certificate.birth_witnesses.contains(&twin_id),
        "the twin is dropped, and the first id holding that key is the one kept"
    );
    let record = CitizenshipRecord { certificate, attestations };
    assert!(
        record.verify_quorum(&sid, resolver(&registry)),
        "and it still verifies under today's verifier, before R2 lands"
    );
}

/// **C2 — declared-witness coverage is checked against a LIVE resolver, so more
/// witnesses makes a certificate WEAKER, and a conferred citizenship can be
/// voided after the fact.**
///
/// Clause 5 exists to stop a certificate naming witnesses it isn't backed by —
/// a property of the record at ISSUANCE, and the record is immutable and
/// content-hashed. But it is evaluated at VERIFY time against whatever the
/// registry says now. So a certificate with four witnesses, three of which
/// still verify — a quorum by every other measure — returns `false` outright
/// once the fourth's key stops resolving (a re-vouch via `witness onboard`
/// replaces the key: `authorize_operational_key` keeps one key per purpose;
/// `hub set-member-key` does the same; so does removal from the registry).
/// Redundancy inverts into fragility: the certificate is only as durable as its
/// least stable witness, and every witness added is another way to lose it.
///
/// Should move to: split the two times. `declared ⊆ present-and-matching` is
/// static, in-record and tamper-evident (keep it, evaluate it over the record's
/// own attestations); `≥3 currently verifiable` is the live check. Anti-forgery
/// is preserved; retroactive invalidation is not.
#[test]
fn c2_one_witness_rotating_voids_a_four_witness_certificate() {
    let sid = subject();
    let ts = fixed_ts();
    let ops: Vec<KeyPair> = (0..4).map(|_| KeyPair::generate()).collect();
    let (mut registry, bindings): (Vec<Lct>, Vec<KeyPair>) =
        ops.iter().map(onboarded).unzip();
    let atts: Vec<Attestation> = registry
        .iter()
        .zip(&ops)
        .map(|(m, op)| hestia::witness::attest(&sid, &m.lct_id(), ts, op).unwrap())
        .collect();

    let (certificate, attestations) = hestia::witness::build_birth_certificate(
        &sid,
        "lct:web4:role:citizen",
        "lct:web4:society:test",
        None,
        &atts,
        ts,
        resolver(&registry),
    )
    .expect("four independent witnesses");
    let record = CitizenshipRecord { certificate, attestations };
    assert_eq!(record.certificate.birth_witnesses.len(), 4);
    assert!(record.verify_quorum(&sid, resolver(&registry)), "valid when conferred");

    // ONE witness re-vouches a new operational key, with its own binding key —
    // exactly what a second `hestia witness onboard` after `hub set-member-key`
    // does. `authorize_operational_key` keeps one key per purpose, so the key
    // that signed the attestation is simply gone. Nothing about the record —
    // content-hashed, referenced from the subject's LCT — changed. Its witness
    // id did not change either; only what that id now resolves to.
    let old_id = registry[0].lct_id();
    registry[0].authorize_operational_key(
        HESTIA_WITNESS_PURPOSE,
        KeyPair::generate().verifying_key(),
        &bindings[0],
    );
    assert_eq!(registry[0].lct_id(), old_id, "same witness id, different key behind it");
    assert!(
        registry[0].operational_key_for(HESTIA_WITNESS_PURPOSE).is_some(),
        "the witness is still a perfectly good witness — for anything signed from now on"
    );

    let still_verifiable = record
        .attestations
        .iter()
        .filter(|a| {
            resolver(&registry)(&a.witness)
                .map(|k| a.verify(&sid, &k))
                .unwrap_or(false)
        })
        .count();

    assert_eq!(still_verifiable, 3, "three attestations still verify — the floor is met");
    assert!(
        !record.verify_quorum(&sid, resolver(&registry)),
        "MEASURED (to be fixed): hard-false anyway, because clause 5 wants ALL of them"
    );
}

/// **C3 — sub-second precision is inside the signed bytes, and `Utc::now()`
/// supplies nanoseconds.**
///
/// `Attestation::message` renders `ts` with `SecondsFormat::AutoSi`, so the
/// digit count varies with the value: a `Utc::now()` attestation signs nine
/// fractional digits. Any hop that normalises timestamps to milliseconds — a
/// JSON store, a JS client, a `TIMESTAMP(3)` column — silently invalidates the
/// signature, and the verifier reports the generic "quorum not met".
///
/// **FIXED — R4** (this commit). `witness::attest` truncates `ts` to whole
/// seconds before signing, so the lossy hop is a no-op. The caller no longer has
/// to know: passing `Utc::now()` — which is what the CLI does — now produces a
/// second-precision attestation. Per HUB, this needs no `v1`→`v2` bump: the
/// rendering is untouched, only the value changes.
///
/// The raw-`Attestation::sign` arm below is kept deliberately, to show the
/// hazard still exists one layer down for anyone who bypasses the producer.
#[test]
fn c3_attest_now_signs_whole_seconds_so_a_lossy_hop_is_a_no_op() {
    let sid = subject();
    let op = KeyPair::generate();
    let now = Utc::now();
    assert_ne!(now.timestamp_subsec_nanos(), 0, "Utc::now() carries sub-second precision");

    let att = hestia::witness::attest(&sid, "lct:web4:mb32:btest", now, &op).unwrap();
    assert_eq!(att.ts.timestamp_subsec_nanos(), 0, "R4: truncated before signing");
    assert_eq!(att.ts.timestamp(), now.timestamp(), "and truncated, not rounded");
    assert!(att.verify(&sid, &op.verifying_key()), "verifies as signed");

    let mut round: Attestation =
        serde_json::from_str(&serde_json::to_string(&att).unwrap()).unwrap();
    assert!(round.verify(&sid, &op.verifying_key()), "survives a JSON round-trip");
    round.ts = Utc.timestamp_millis_opt(round.ts.timestamp_millis()).unwrap();
    assert!(
        round.verify(&sid, &op.verifying_key()),
        "R4: and survives a millisecond hop, because truncation is a no-op"
    );

    // One layer down, unchanged: the signing primitive still honours whatever
    // precision it is handed. R4 is a producer-side discipline, not a format change.
    let raw = web4_core::Attestation::sign(
        &sid,
        "lct:web4:mb32:btest",
        web4_core::AttestationType::Existence,
        now,
        &op,
    );
    let mut lossy = raw.clone();
    lossy.ts = Utc.timestamp_millis_opt(now.timestamp_millis()).unwrap();
    assert!(raw.verify(&sid, &op.verifying_key()));
    assert!(
        !lossy.verify(&sid, &op.verifying_key()),
        "MEASURED: bypassing the producer still lets a millisecond hop void a signature"
    );
}

/// **C4 — the purpose string is a cross-repo literal with two spellings.**
///
/// hestia vouches and resolves `"witnessing"` (`member_registry.rs`, `cli.rs`).
/// web4-core's `OperationalKey::purpose` doc comment says `e.g. "witness"`, and
/// so do its tests. A hub-side resolver written from web4-core's own example
/// resolves `None` for every real witness and reports "quorum not met" — a
/// spelling mismatch wearing the costume of a governance failure.
///
/// Should move to: `WITNESS_KEY_PURPOSE` exported from web4-core, with the doc
/// comment and tests using it. This test is pinned to `HESTIA_WITNESS_PURPOSE`
/// so it follows the constant once it exists.
#[test]
fn c4_the_other_purpose_spelling_resolves_to_nothing() {
    let (lct, _binding) = onboarded(&KeyPair::generate());
    assert!(lct.operational_key_for(HESTIA_WITNESS_PURPOSE).is_some());
    assert!(
        lct.operational_key_for("witness").is_none(),
        "MEASURED: web4-core's documented spelling resolves None against a real vouch"
    );
}

/// **C5 — the subject id is inside the signed bytes, and two id spaces are live.**
///
/// `hestia witness attest <subject_lct_id>` takes the id as free text. Omitting
/// `--as` records the witness as `lct:web4:member:{uuid}`; the registry keys on
/// the pubkey-derived `lct:web4:mb32:…`. The same entity under its other
/// spelling is, to the signature, a different subject — so an attestation can be
/// well-formed, correctly signed, and structurally incapable of ever verifying.
///
/// **FIXED — R6** (this commit). `witness::attest` refuses a subject that is not
/// the canonical key-derived form, and names which id space it got instead. It
/// is a refusal and not a translation, necessarily: there is no mapping from
/// `lct:web4:member:{uuid}` back to the derived id without the key, and
/// inventing one would be the id-forgery the derived form exists to prevent.
///
/// The predicate, for the witness roster to key on (HUB's R6 note — one mapping,
/// not two): `lct:web4:mb32:b` + 52 characters of `[a-z2-7]`, final character
/// `a` or `q`. That last clause is not cosmetic: 52 base32 characters hold 260
/// bits and a SHA-256 digest supplies 256, so the final character's low four
/// bits are padding and always zero — alphabet index 0 or 16. Measured over
/// 20 000 random digests: exactly those two, ~50/50. It rejects 30 of every 32
/// otherwise-well-formed hand-typed ids.
#[test]
fn c5_attest_refuses_a_subject_from_the_other_id_space() {
    use hestia::witness::{attest, canonical_subject_id, is_canonical_lct_id, SubjectIdError};
    let (subject_lct, _) = Lct::new(EntityType::AiSoftware, None);
    let mb32 = subject_lct.lct_id();
    let legacy = format!("lct:web4:member:{}", uuid::Uuid::nil());
    let op = KeyPair::generate();

    assert!(is_canonical_lct_id(&mb32), "a real derived id passes");
    assert_eq!(
        attest(&legacy, "lct:web4:mb32:btest", fixed_ts(), &op).unwrap_err(),
        SubjectIdError::MembershipIdSpace(legacy.clone()),
        "R6: the membership id space is refused BY NAME, not signed"
    );
    // and the refusal explains itself rather than becoming "quorum not met"
    let msg = attest(&legacy, "lct:web4:mb32:btest", fixed_ts(), &op)
        .unwrap_err()
        .to_string();
    assert!(msg.contains("membership id"), "names the id space: {msg}");
    assert!(msg.contains("lct:web4:mb32:b"), "names the form it wants: {msg}");

    // The full clause set, each refused for its own reason.
    assert!(matches!(
        canonical_subject_id("lct:web4:role:citizen"),
        Err(SubjectIdError::WrongSpace(_))
    ));
    assert!(matches!(
        canonical_subject_id("lct:web4:mb32:bsubject"),
        Err(SubjectIdError::BodyLength { got: 7 })
    ), "the readable stand-in hestia's own tests used before R6");
    let mut bad_alpha: String = mb32.clone();
    bad_alpha.replace_range(bad_alpha.len() - 1.., "1");
    assert!(matches!(
        canonical_subject_id(&bad_alpha),
        Err(SubjectIdError::Alphabet { ch: '1' })
    ));
    // Same length, same alphabet, right prefix — and still impossible.
    let mut bad_tail: String = mb32.clone();
    bad_tail.replace_range(bad_tail.len() - 1.., "b");
    assert_eq!(bad_tail.len(), mb32.len());
    assert!(matches!(
        canonical_subject_id(&bad_tail),
        Err(SubjectIdError::PaddingBits { last: 'b' })
    ), "the clause that catches a transcribed id: {bad_tail}");

    // The real subject signs and verifies, under its own id and no other.
    let good = attest(&mb32, "lct:web4:mb32:btest", fixed_ts(), &op).unwrap();
    assert!(good.verify(&mb32, &op.verifying_key()));
    assert!(!good.verify(&legacy, &op.verifying_key()));
}
