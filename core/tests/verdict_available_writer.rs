//! The deny recorder must WRITE `verdict_available`, not merely be told it.
//!
//! WHY THIS FILE EXISTS. `derivation.rs::has_no_verdict` excludes a deny from temperament
//! when the gate could not reach a verdict — "I could not judge" is not "I judged you
//! badly" (dp, 2026-07-26: "well, fix it"). It has two arms: the explicit
//! `verdict_available` flag, and a legacy substring match on `reason`. The hooks have sent
//! the flag since Sprint E. `tool_witness_decision` never read it, and the daemon declares
//! every tool `additionalProperties: true`, so it was accepted and dropped in silence.
//!
//! Measured on CBP 2026-08-15 across 142,756 chain entries
//! (`tools/claude_verdict_available_arm_audit.py`): the key appears ZERO times, in every
//! event type. The flag arm had never had an input; the exclusion rode entirely on words.
//! 33 enforced denies — `gate.degraded` (the mode RATIFIED 2026-08-11) and codex's
//! pre-Sprint-E "governor unreachable, failing closed" — match neither marker and reach
//! temperament as member conduct, six of them on the day of measurement.
//!
//! WHAT THIS TEST IS. A SHAPE pin on the writer site, comment-stripped so it cannot pass on
//! the prose that explains it — the failure mode a lexical guard has by default, and one
//! this corpus has hit before. The behavioural half lives in
//! `derivation::tests::infra_fail_close_is_excluded_by_the_flag_and_not_only_by_its_words`,
//! which drives `derive()` for real and carries the sibling that must still score.
//!
//! WHAT IT CANNOT CATCH, stated so nobody reads a green here as more than it is:
//!   - whether the DEPLOYED daemon contains this code (a tree is not an install);
//!   - whether some later handler edit drops the key downstream of the `json!`;
//!   - whether the 33 rows already on the chain are ever re-scored. They are not. That
//!     needs `exoneration` or `amnesty` and belongs to the operator, not to this diff.

use std::fs;
use std::path::Path;

/// The production (non-comment) lines of one `async fn` item in one file under `src`,
/// ending at the first item-position closing brace. Comment lines are dropped BEFORE
/// matching: a pin that a comment can satisfy pins nothing, and every line this test
/// cares about is explained by a comment sitting directly above it.
fn production_body(rel: &str, want_fn: &str) -> String {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"));
    let opener = format!("async fn {want_fn}(");
    let mut in_fn = false;
    let mut out = Vec::new();
    for line in text.lines() {
        if !in_fn {
            if line.trim_start().starts_with(&opener) {
                in_fn = true;
            }
            continue;
        }
        if line == "}" {
            break;
        }
        let t = line.trim();
        if t.starts_with("//") {
            continue;
        }
        out.push(t.to_string());
    }
    assert!(in_fn, "fn `{want_fn}` not found in {rel} — this pin is measuring nothing");
    assert!(!out.is_empty(), "fn `{want_fn}` body read as empty in {rel}");
    out.join("\n")
}

#[test]
fn the_deny_recorder_reads_and_records_verdict_available() {
    let body = production_body("server/handler.rs", "tool_witness_decision");

    assert!(
        body.contains(r#"args.get("verdict_available")"#),
        "tool_witness_decision does not READ `verdict_available` off its args.\n\
         The hooks send it (plugins/_shared/hestia_gate_mechanism.py:478) and\n\
         derivation.rs:353 reads it back off the chain, so dropping it here silently\n\
         scores infrastructure failure as member conduct."
    );
    assert!(
        body.contains(r#""verdict_available": verdict_available,"#),
        "tool_witness_decision reads `verdict_available` but does not put it in the\n\
         policy_decision payload. A value parsed and not recorded is the same absence\n\
         as never parsing it, and reads at the call site as if it were handled."
    );

    // POSITIVE CONTROL for the reader itself. If the comment-stripper or the fn-boundary
    // walk breaks, the two assertions above go quietly vacuous — they can only ever fail,
    // never falsely pass, but a body read as the WRONG fn would pass for the wrong reason.
    // These two lines are load-bearing code in this fn that predate the change under test.
    assert!(
        body.contains(r#"let payload_sha256 = optional_string(args, "payload_sha256");"#)
            && body.contains("let entry = s.append_chain("),
        "the fn-body reader is not reading tool_witness_decision — the pin above is vacuous"
    );

    // And the comment-stripper must actually strip. The explanatory block above the new
    // line names the identifier repeatedly; if comments survived, the pin would pass on
    // prose alone. This asserts the stripper removed a phrase that exists ONLY in a comment.
    assert!(
        !body.contains("well, fix it"),
        "comment lines survived the stripper — every assertion in this file can now pass \
         on prose rather than on code"
    );
}

#[test]
fn derivation_still_reads_the_key_this_writer_emits() {
    // The two halves are in different files and neither is useless without the other, so
    // nothing local goes red if the READER is deleted — the writer would simply emit a key
    // nobody consumes, which is exactly the `core_digest` shape one layer over.
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join("derivation.rs")).unwrap();
    let code: String = text
        .lines()
        .filter(|l| !l.trim_start().starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(
        code.contains(r#"e.event_data.get("verdict_available")"#),
        "derivation no longer reads `verdict_available`; the handler is now writing a key \
         with no consumer"
    );
    assert!(
        code.contains(r#""verdict_available","#),
        "`verdict_available` left DERIVATION_KEYS — the projection would strip it before \
         has_no_verdict ever sees it, and the fold would silently revert to the text arm"
    );
}
