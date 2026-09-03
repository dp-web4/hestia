//! `policy_edit` — law amendment, the highest-consequence act class here — must NAME the
//! authorization that admitted it, not merely sit next to it.
//!
//! WHY THIS FILE EXISTS, measured rather than imagined (forum 2662/2664/2666). `policy_edit`
//! was one of exactly two chain families out of 39 naming no author at all. `operator_gate`
//! resolves the operator, writes it into its OWN row, and then drops it one stack frame
//! before the handler that performs the act. The author was proven and then discarded at the
//! boundary.
//!
//! THE POINTER IS THE LOAD-BEARING HALF, not the author string. Without it an act row and
//! its authorizing gate row are joinable only by POSITION — they land adjacent — and a
//! positional join is not a reference: nothing in either row commits to the pair, so the
//! join's width is chosen by the reader and concurrent traffic silently breaks it. Measured
//! over the eight most recent `policy_edit` rows on this seat: at strict position−1 the gate
//! row is the neighbour for 5 of 8. The other three are separated by an interleaved
//! `outcome`, a `gate_escalation_opened`, and another `policy_edit`.

use hestia::server::operator_auth::GateWitness;
use serde_json::json;

/// PIN 1 — the stamp carries the pointer, and its ABSENCE writes nothing.
///
/// The control arm is the half that matters. A witness with no hash must leave the record
/// untouched, not write a null or an empty string: a reader has to be able to tell "this act
/// had no operator session" from "the operator went unrecorded", and an empty author field
/// is the failure that reads as an answer.
#[test]
fn the_stamp_names_the_gate_row_and_absence_writes_nothing() {
    let witness = GateWitness {
        provenance: None,
        gate_entry_hash: Some("abc123".into()),
    };
    let stamped = witness.stamp(json!({"change": "preset", "preset": "strict"}));
    assert_eq!(
        stamped.get("authorized_by_gate").and_then(|v| v.as_str()),
        Some("abc123"),
        "the act row must reference the gate row that admitted it: {stamped}"
    );
    // The original content survives — stamping augments, never replaces.
    assert_eq!(stamped.get("change").and_then(|v| v.as_str()), Some("preset"));

    let bare = GateWitness::default().stamp(json!({"change": "preset"}));
    assert!(
        bare.get("authorized_by_gate").is_none(),
        "absent authorization must leave the FIELD ABSENT, not null and not empty — those \
         read as an answer: {bare}"
    );
}

/// PIN 2 — every `policy_edit` act site goes through the stamper.
///
/// Source-grained on purpose. PIN 1 proves the stamper works; it cannot prove the act sites
/// USE it, and a sixth handler added later without stamping is exactly how this defect
/// returns — silently, because an unstamped row looks like every row did before the fix.
/// Same class as "the right answer existing somewhere does not put it on the path anyone
/// takes".
#[test]
fn every_policy_edit_act_site_stamps_its_authorization() {
    let src = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src/server/http.rs"),
    )
    .expect("http.rs is readable");
    // Production region only: test modules write `policy_edit` rows as fixtures and must
    // not be required to carry an authorization they are not testing.
    //
    // Computed by brace-matching each `#[cfg(test)]` module rather than splitting on the
    // first occurrence. The naive split truncated at the FIRST test module — and since #593
    // added `mod arena_tests` near the top of this file, that discarded every real handler
    // below it and the pin reported "0 sites". A guard that silently measures nothing is
    // the failure it exists to catch, so it asserts a floor on the site count below.
    let lines: Vec<&str> = src.lines().collect();
    let mut in_test = vec![false; lines.len()];
    let mut i = 0;
    while i < lines.len() {
        if lines[i].trim_start().starts_with("#[cfg(test)]") {
            // Walk to the module's opening brace, then to its match.
            let mut j = i;
            while j < lines.len() && !lines[j].contains('{') {
                j += 1;
            }
            let mut depth = 0i32;
            while j < lines.len() {
                depth += lines[j].matches('{').count() as i32;
                depth -= lines[j].matches('}').count() as i32;
                in_test[j] = true;
                if depth <= 0 {
                    break;
                }
                j += 1;
            }
            for k in i..j.min(lines.len()) {
                in_test[k] = true;
            }
            i = j + 1;
            continue;
        }
        i += 1;
    }
    let mut sites = 0;
    let mut unstamped = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if !line.contains("\"policy_edit\",") || in_test[i] {
            continue;
        }
        sites += 1;
        // The stamper is applied to the record argument, which follows the event type on the
        // same line or the next few.
        let window = lines[i..(i + 4).min(lines.len())].join("\n");
        if !window.contains("stamp_gate(") {
            unstamped.push(i + 1);
        }
    }
    assert!(
        sites >= 5,
        "expected at least the five known policy_edit act sites, found {sites} — if the \
         handlers moved or were renamed this pin is measuring nothing"
    );
    assert!(
        unstamped.is_empty(),
        "policy_edit rows written WITHOUT stamp_gate at http.rs lines {unstamped:?}. An \
         unstamped amendment names no authorization, and it looks exactly like every row \
         did before this was fixed — which is why it has to fail here rather than be noticed \
         later in the chain."
    );
}
