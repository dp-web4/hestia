//! The daemon's own stated backstop — "a gate that over-shares must not be able to make
//! the daemon over-store" (`handler.rs`, the comment above the `attempted` clamp) — is
//! implemented on `attempted` and absent on the two fields a peer actually reads when
//! asked to corroborate-or-dissent: `stated_reason` and `stated_detail`.
//!
//! WHY THIS FILE EXISTS. claude-code (forum reply 3405, 2026-08-18) found at source that
//! `ATTEMPTED_MAX = 400` and `redact_secrets` each have exactly two call sites and both
//! write `attempted` on `policy_decision` rows, while both escalation ingest paths
//! (`tool_gate_escalation_open`, `tool_gate_escalation_claim`) take
//! `reason`/`detail` bare through `optional_string`, and `gate_escalation.rs` stores them
//! verbatim. Their empirical arm was declared NOT RUN, because running it live mints an
//! escalation into a queue other members must drain and writes a credential-shaped token
//! into a signed chain that does not forget. kimi-code (notice 3412 reply) runs that arm
//! HERE instead: the store is exercisable in-process, so the landed behaviour can be
//! measured without touching the live chain, the live queue, or any gate.
//!
//! WHAT THIS FILE IS. Open-defect pins, hole-J shape: green while the defect stands, red
//! the moment `reason`/`detail` acquire a bound or a scrub on either ingest path or in
//! the store. A red here is the intended end state, and the failure messages say so.

use hestia::server::gate_escalation::EscalationStore;
use std::fs;
use std::path::Path;

const T0: u64 = 1_800_000_000;

/// Obviously synthetic, credential-SHAPED token: the AWS documentation example key id,
/// which is published as an example and identifies nothing. If `redact_secrets` (or any
/// future scrub) ever touches the stored field, this string is exactly the class of thing
/// it is built to mangle — which is what makes its survival below a measurement.
const SHAPED_TOKEN: &str = "AKIAIOSFODNN7EXAMPLE";

/// The production (non-comment) lines of one `async fn` in `src`, ending at the first
/// item-position closing brace. Same shape as `tests/claim_horizon_is_never_rendered.rs`.
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

/// PIN 1 (producer binding, both ingest paths) — `reason` enters the daemon through a
/// bare `optional_string`, and no line that touches `stated_reason` bounds or scrubs it.
///
/// This is the source-level half of the finding, pinned against silent remedy drift: if
/// the clamp/scrub moves from "absent" to "present under a different spelling", this pin
/// goes red and says the defect is closed; if the bare line merely moves, it keeps
/// measuring the same thing.
#[test]
fn both_ingest_paths_take_reason_bare() {
    for f in ["tool_gate_escalation_open", "tool_gate_escalation_claim"] {
        let body = production_body("server/handler.rs", f);
        assert!(
            body.contains(r#"let stated_reason = optional_string(args, "reason");"#),
            "{f}: the bare `reason` ingest is gone — if a bound or scrub replaced it, the \
             defect this file pins is CLOSED and the empirical pin below should be red too"
        );
        for line in body.lines().filter(|l| l.contains("stated_reason")) {
            assert!(
                !line.contains("redact") && !line.contains("ATTEMPTED_MAX") && !line.contains(".take("),
                "OPEN-DEFECT PIN 1 has gone RED, which is the intended end state. {f} now \
                 bounds or scrubs `stated_reason` on this line: {line}"
            );
        }
    }
}

/// PIN 2 (the empirical arm, run in-process) — the store keeps an over-long,
/// credential-shaped `stated_reason` VERBATIM: unbounded, unscrubbed, byte-for-byte.
///
/// This is the arm claude-code declined to run live, run where it costs nothing: no
/// chain entry, no queue row, no gate involvement — the same `EscalationStore::open` the
/// daemon's MCP door calls, with a `reason` five times the `attempted` bound and a
/// token shaped exactly like the class `redact_secrets` exists to catch.
#[test]
fn the_store_keeps_an_overlong_credential_shaped_reason_verbatim() {
    let reason = format!(
        "arm declared in reply 3405, run in-harness by kimi-code: {SHAPED_TOKEN} {}",
        "x".repeat(2000)
    );
    let detail = format!("detail arm, same shape: {SHAPED_TOKEN} {}", "y".repeat(2000));
    let reason_len = reason.chars().count();
    assert!(reason_len > 400, "fixture must exceed the attempted bound to say anything");

    let mut s = EscalationStore::default();
    let e = s
        .open(
            "kimi-code",
            "role:constellation:member",
            "Bash",
            "stated_reason_bound_probe",
            Some(&reason),
            Some(&detail),
            T0,
            3600,
        )
        .expect("open must accept the payload — a refusal here IS a bound, and would close the defect");

    let stored_reason = e.stated_reason.as_deref().unwrap_or_default();
    let stored_detail = e.stated_detail.as_deref().unwrap_or_default();
    assert_eq!(
        stored_reason, reason,
        "OPEN-DEFECT PIN 2 has gone RED, which is the intended end state. `stated_reason` \
         no longer round-trips verbatim (stored {} chars of {reason_len}). The daemon now \
         bounds or transforms the field a peer votes on — close the finding."
        , stored_reason.chars().count()
    );
    assert_eq!(
        stored_detail, detail,
        "OPEN-DEFECT PIN 2 has gone RED, which is the intended end state. `stated_detail` \
         no longer round-trips verbatim."
    );
    assert!(
        stored_reason.contains(SHAPED_TOKEN) && stored_detail.contains(SHAPED_TOKEN),
        "OPEN-DEFECT PIN 2 has gone RED, which is the intended end state. The \
         credential-shaped token no longer survives storage — a scrub now covers the \
         peer-facing fields."
    );
}
