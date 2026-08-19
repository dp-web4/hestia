//! RETIRED 2026-08-19. The defect this file pinned is closed; what remains is the guard that
//! its coverage really moved somewhere, rather than being deleted with a claim that it did.
//!
//! WHAT IT PINNED. `permits_write` answered a four-conjunct question with two conjuncts, in
//! BOTH producers, so it went STALE-TRUE: after the claim horizon closed it kept saying a
//! permit permits a write. Three OPEN-DEFECT PINS asserted that wrong behaviour so they would
//! go red when it was fixed. On 2026-08-18 `6983b48` (#518) fixed it, and on 2026-08-19 all
//! three went red exactly as designed — but they went red by failing to COMPILE, because the
//! same commit changed `decision_reply(&self)` to `decision_reply(&self, now: u64)` and did
//! not update the two integration targets. A target that dies at exit 101 prints none of the
//! failure messages these pins were written to deliver, so the turnover arrived as `error:
//! could not compile` and `main` stayed red for a day (#528).
//!
//! WHERE EACH PIN WENT. Recorded per-pin, because "superseded" is a claim about coverage and
//! the way it fails is silently dropping the half nothing else watches:
//!
//!   PIN 1  the grant reply permits a write the gate refuses
//!          -> `permits_write_tracks_the_two_conjuncts_that_move` (gate_escalation.rs test
//!             module). Strictly stronger: it samples INSIDE the window, one second past the
//!             horizon, and SPENT — the third case this file never had a fixture for.
//!
//!   PIN 2  both producers drop the same two conjuncts, checked against production source
//!          -> split. The `decision_reply` half is closed and asserted positively by the test
//!             above. The POLL half moved to `claim_horizon_is_never_rendered.rs` PIN 4(c),
//!             producer-bound to the new expression, because `tool_gate_escalation_poll`
//!             still has no test of its own: `grep tool_gate_escalation_poll src/` finds the
//!             dispatch arm and the definition, and nothing else. Its (d) half — the note
//!             that still teaches the two-conjunct rule — did NOT turn over and is carried
//!             there as a live open-defect pin.
//!
//!   PIN 3  the existing one-predicate guard is evaluated where it cannot fail
//!          -> `permits_write_tracks_the_two_conjuncts_that_move`, whose docstring states the
//!             blindness argument in full and whose samples are the remedy for it. Note that
//!             this pin is the one a MECHANICAL fix would have destroyed quietly: threading
//!             `now` into its single `decision_reply()` call makes it compare
//!             `is_claimable(guard_time)` with `is_claimable(past_horizon)` and PASS — a
//!             tautology about a time-dependent predicate, green forever, certifying nothing.
//!             Measured on this branch before the turnover was written.
//!
//! WHAT IS LEFT HERE. One test, and it is not a pin: it asserts the two named replacements
//! still exist. A supersession note is prose and rots; if someone deletes or renames those
//! tests, the coverage this file gave up goes with them and nothing else would say so.

use std::fs;
use std::path::Path;

/// The in-crate tests this file's pins were retired into. Named, not described: a rename is
/// exactly the event that would silently drop the coverage.
const REPLACEMENTS: [&str; 2] = [
    "fn permits_write_tracks_the_two_conjuncts_that_move()",
    "fn one_answer_serves_both_deciding_surfaces()",
];

/// Production (non-comment) lines of `src/<rel>`. Comments are dropped BEFORE matching so
/// this can never be satisfied by the prose that explains it — including this file's own
/// per-pin table, were it ever copied there.
fn production_text(rel: &str) -> String {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"));
    text.lines()
        .map(str::trim)
        .filter(|t| !t.starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn the_pins_retired_from_this_file_still_have_somewhere_to_have_gone() {
    let escalation = production_text("server/gate_escalation.rs");
    for want in REPLACEMENTS {
        assert!(
            escalation.contains(want),
            "SUPERSESSION BROKEN: `{want}` no longer exists in gate_escalation.rs. This file's \
             OPEN-DEFECT PINS were retired into it on 2026-08-19 on the strength of it being \
             strictly stronger coverage — see the per-pin table in this file's header for what \
             is now unwatched. Restore it, or re-open the pins here."
        );
    }

    // And the enforcing conjunction the whole argument rests on. If `is_claimable` stops
    // carrying the two conjuncts that move, the replacements above are asserting equality
    // between two predicates that agree for a new reason, which is the failure this file's
    // PIN 3 existed to name.
    assert!(
        escalation.contains("&& self.consumed_at.is_none()")
            && escalation.contains("&& now < self.decided_horizon()"),
        "`is_claimable` no longer enforces the two conjuncts the retired pins were about; \
         re-derive the divergence before trusting the replacements named above"
    );
}
