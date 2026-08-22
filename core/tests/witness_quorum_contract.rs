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
/// Should move to: dedup on the RESOLVED KEY as well as the id — in the
/// producer (`valid_distinct_existence`) so a certificate like this is never
/// built, and in the verifier's stated contract so an existing one is caught.
#[test]
fn c1_three_witness_ids_backed_by_one_key_currently_pass() {
    let sid = subject();
    let ts = fixed_ts();
    let shared_op = KeyPair::generate();
    let registry: Vec<Lct> = (0..3).map(|_| onboarded(&shared_op).0).collect();
    let atts: Vec<Attestation> = registry
        .iter()
        .map(|m| hestia::witness::attest(&sid, &m.lct_id(), ts, &shared_op))
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
    .expect("the producer builds this certificate today");
    let record = CitizenshipRecord { certificate, attestations };

    let distinct_keys: std::collections::BTreeSet<String> = record
        .attestations
        .iter()
        .filter_map(|a| resolver(&registry)(&a.witness).map(|k| k.to_hex()))
        .collect();

    assert_eq!(record.certificate.birth_witnesses.len(), 3, "three declared witnesses");
    assert_eq!(distinct_keys.len(), 1, "backed by exactly one signing key");
    assert!(
        record.verify_quorum(&sid, resolver(&registry)),
        "MEASURED (to be fixed): the quorum passes on three spellings of one key"
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
        .map(|(m, op)| hestia::witness::attest(&sid, &m.lct_id(), ts, op))
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
/// Should move to: the producer truncates to whole seconds before signing.
/// Measured below: a second-precision attestation survives both a JSON
/// round-trip and a millisecond normalisation, because truncating it is a no-op.
#[test]
fn c3_second_precision_is_the_only_ts_that_survives_a_lossy_hop() {
    let sid = subject();
    let op = KeyPair::generate();
    let now = Utc::now();

    let as_signed = hestia::witness::attest(&sid, "lct:web4:mb32:btest", now, &op);
    assert!(as_signed.verify(&sid, &op.verifying_key()), "verifies as signed");

    let mut lossy = as_signed.clone();
    lossy.ts = Utc.timestamp_millis_opt(now.timestamp_millis()).unwrap();
    assert!(
        !lossy.verify(&sid, &op.verifying_key()),
        "MEASURED: a millisecond hop breaks a nanosecond-precision attestation"
    );

    let truncated = hestia::witness::attest(
        &sid,
        "lct:web4:mb32:btest",
        Utc.timestamp_opt(now.timestamp(), 0).unwrap(),
        &op,
    );
    let mut round: Attestation =
        serde_json::from_str(&serde_json::to_string(&truncated).unwrap()).unwrap();
    assert!(round.verify(&sid, &op.verifying_key()), "survives a JSON round-trip");
    round.ts = Utc.timestamp_millis_opt(round.ts.timestamp_millis()).unwrap();
    assert!(
        round.verify(&sid, &op.verifying_key()),
        "and survives a millisecond hop, because truncation is a no-op"
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
/// Should move to: `witness attest` canonicalises the subject id (or refuses a
/// form it cannot canonicalise) rather than signing whatever it was handed.
#[test]
fn c5_an_attestation_over_the_other_id_space_can_never_verify() {
    let (subject_lct, _) = Lct::new(EntityType::AiSoftware, None);
    let mb32 = subject_lct.lct_id();
    let legacy = format!("lct:web4:member:{}", uuid::Uuid::nil());
    let op = KeyPair::generate();

    let att = hestia::witness::attest(&legacy, "lct:web4:mb32:btest", fixed_ts(), &op);
    assert!(att.verify(&legacy, &op.verifying_key()), "well-formed under the id it signed");
    assert!(
        !att.verify(&mb32, &op.verifying_key()),
        "MEASURED: and worthless under the id the registry knows"
    );
}
