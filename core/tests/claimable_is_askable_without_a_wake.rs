//! A member can ask what it may spend, without first being refused again.
//!
//! WHY THIS FILE EXISTS. `claimable_for` answers the only question that closes the
//! deny → decide-out-of-band → re-issue loop: *what may I spend right now?* Before
//! `hestia_gate_escalation_claimable` it had ONE production caller — the refusal reply's
//! `decided_awaiting_claim` field — so the answer reached a member only as a side effect of
//! being refused AGAIN. A member whose approval landed while it sat idle had to provoke a
//! second refusal to be told about the first, and the 600s claim window ran the whole time.
//!
//! The push half exists and does not arrive. The disposition projector mints a mesh notice
//! on decision, but delivery is a WAKE, and a LIVE seat is never woken because it is already
//! running (#366). Measured 2026-08-23/24 on CBP: four escalations opened, four approved,
//! ZERO notifications received, exactly one claimed — and that one only because dp mentioned
//! it in conversation while the window happened to still be open. Reproduced 2026-08-25 on
//! `74195558206f22ca`: approved by the operator, `bar_met: true`, and
//! `claim_window_secs_remaining: 0` by the time its asker thought to look.
//!
//! WHAT IS PINNED HERE. Two things, and neither is "the function works".
//!
//!   PIN A — REACHABILITY. A tool that is declared but not dispatched, or dispatched but not
//!   declared, is dead in exactly the way `claimable_for` was already dead: present, correct,
//!   and callable by nobody. Both halves are asserted from the SOURCE, because that is where
//!   the two can disagree.
//!
//!   PIN B — THE HORIZON IS THE CLAIM CLOCK. The listing must go empty at
//!   `decided_at + APPROVAL_CLAIM_WINDOW_SECS`, not at `expires_at`. Those are two different
//!   clocks and the record clock is the longer one, which is how a dead permit publishes as
//!   live. Asserted on BOTH sides of the boundary: a surface that never lists anything would
//!   satisfy a one-sided check trivially.

use hestia::server::gate_escalation::{
    Channel, EscalationStore, APPROVAL_CLAIM_WINDOW_SECS, DEFAULT_TTL_SECS,
};

const T0: u64 = 1_800_000_000;
const SEAT: &str = "claude-code";
const ACT: &str = "Edit -> law_inject.py";

fn opened_and_approved(decided_at: u64) -> (EscalationStore, String) {
    let mut s = EscalationStore::default();
    let e = s
        .open(
            SEAT,
            "role:constellation:member",
            "Edit",
            "law_inject.py",
            // REQUIRED since #539, and the reason this fixture states it explicitly rather
            // than passing None: an escalation with no act mints a row that is approvable and
            // permanently unspendable, which is the exact defect the claimable listing exists
            // to stop a member walking into.
            Some(ACT),
            None,
            None,
            T0,
            DEFAULT_TTL_SECS,
        )
        .expect("open");
    let id = e.id.clone();
    s.decide(
        &id,
        true,
        "dp",
        "role:constellation:sovereign",
        Channel::LocalCli,
        None,
        Some("ok"),
        decided_at,
    )
    .expect("decide");
    (s, id)
}

/// PIN A — the tool is BOTH declared and dispatched.
///
/// Read from source rather than from a running server on purpose: a handler that dispatches a
/// name absent from the declared list is reachable only by a caller who already guessed it,
/// and a name declared but never dispatched answers "unknown tool" to everyone who reads the
/// list and believes it. Those are two different defects and neither shows up in a test that
/// calls the function directly.
#[test]
fn the_claimable_tool_is_both_declared_and_dispatched() {
    let src = include_str!("../src/server/handler.rs");
    const NAME: &str = "hestia_gate_escalation_claimable";

    let dispatched = src.contains(&format!(
        "\"{NAME}\" => tool_gate_escalation_claimable(&self.state, &args).await"
    ));
    assert!(
        dispatched,
        "{NAME} is not dispatched: declaring it without an arm makes it \
         'unknown tool' to every caller who reads the tool list and believes it"
    );

    // The declaration sits in the `t(...)` table. Counting occurrences separates "declared"
    // from "mentioned in a comment about being declared".
    let declared = src.matches(&format!("\"{NAME}\",")).count();
    assert!(
        declared >= 1,
        "{NAME} is dispatched but never declared: reachable only by a caller who guessed \
         the name, which is the state claimable_for was already in"
    );

    // NEGATIVE CONTROL. Both assertions above are substring searches over a 16,000-line file,
    // and a substring search that matches everything passes for the wrong reason. A name that
    // must NOT be found proves the matcher discriminates; without it, a green here is
    // consistent with `contains` having been handed something trivially true.
    const ABSENT: &str = "hestia_gate_escalation_claimable_that_does_not_exist";
    assert!(
        !src.contains(&format!(
            "\"{ABSENT}\" => tool_gate_escalation_claimable(&self.state, &args).await"
        )),
        "negative control fired: this matcher would report ANY name as dispatched, so the \
         assertions above prove nothing"
    );
}

/// PIN B — the listing dies on the CLAIM clock, and it is non-empty before it does.
///
/// The "before" half is not decoration. A `claimable_for` that returned nothing at all would
/// pass an emptiness-only assertion at every instant, which is the shape that lets a broken
/// surface certify itself.
#[test]
fn the_listing_expires_on_the_decision_clock_not_the_record_clock() {
    // Decided IMMEDIATELY. This is the case that punishes a prompt decider: the record lives
    // until T0 + 3600, the grant dies at T0 + 600, and a surface reading the record clock
    // reports ~3000s of life that does not exist.
    let (s, id) = opened_and_approved(T0 + 1);
    let horizon = T0 + 1 + APPROVAL_CLAIM_WINDOW_SECS;

    let live = s.claimable_for(SEAT, horizon - 1);
    assert_eq!(
        live.len(),
        1,
        "an approval one second inside its own window must be listed; a surface that lists \
         nothing satisfies the expiry half of this test trivially"
    );
    assert_eq!(live[0].id, id);
    assert_eq!(
        live[0].claim_window_secs_remaining(horizon - 1),
        1,
        "the remaining figure must count down to the CLAIM horizon"
    );

    // One second later the grant is gone, while the RECORD is still alive for ~50 minutes.
    assert!(
        s.claimable_for(SEAT, horizon).is_empty(),
        "past decided_at + {APPROVAL_CLAIM_WINDOW_SECS} the approval is unspendable and must \
         not be advertised: claim() would refuse it, and a listing that promises a claim \
         which fails is worse than no listing"
    );
    assert!(
        horizon < T0 + DEFAULT_TTL_SECS,
        "fixture is not exercising the two clocks: the claim horizon must fall INSIDE the \
         record lifetime, or this test proves nothing about which clock is read"
    );
    assert!(
        s.claimable_for(SEAT, T0 + DEFAULT_TTL_SECS - 1).is_empty(),
        "still empty while the record lives on: the record clock must never resurrect a grant"
    );
}

/// A listing is scoped to ONE member. Another seat's approval is not the caller's to spend,
/// and reading it as such is how a member re-issues an act it was never granted.
#[test]
fn one_members_grant_is_not_another_members_listing() {
    let (s, _) = opened_and_approved(T0 + 1);
    assert!(
        s.claimable_for("kimi", T0 + 2).is_empty(),
        "claimable_for must not leak another seat's approval"
    );
    assert_eq!(
        s.claimable_for(SEAT, T0 + 2).len(),
        1,
        "positive control: the owning seat still sees it, so the assertion above is about \
         scoping and not about an empty store"
    );
}

/// PIN C — the surface refuses an unproven caller instead of serving a named one.
///
/// GPT/Nova review of the first cut: the handler fell back to a caller-supplied `plugin_id`
/// when the session did not resolve, labelled it `asker_basis: "asserted"`, and then listed
/// that member's claimable approvals. An honest LABEL on a disclosure does not stop it being a
/// disclosure -- an unauthenticated caller could enumerate any member's grants by naming them,
/// while the tool advertised "what approvals YOU can spend". The doc's excuse ("discloses
/// nothing a member could not learn by being refused") was false on its face: your own refusal
/// never reports what a PEER holds.
///
/// Pinned from SOURCE because the defect was a fallback ARM, not a wrong value: a behavioural
/// test that passes a session would never exercise it, which is exactly how it shipped.
#[test]
fn the_claimable_surface_has_no_asserted_plugin_id_fallback() {
    let src = include_str!("../src/server/handler.rs");
    let start = src
        .find("async fn tool_gate_escalation_claimable")
        .expect("claimable handler not found");
    let end = src[start..]
        .find("\nasync fn ")
        .map(|o| start + o)
        .unwrap_or(src.len());
    // COMMENTS STRIPPED BEFORE MATCHING. The first run of this pin went red on the prose that
    // explains the fix -- the comment block quotes `asker_basis: "asserted"` while describing
    // why the arm was removed. A guard that a comment can satisfy (or break) is measuring the
    // documentation, not the code.
    let body: String = src[start..end]
        .lines()
        .filter(|l| !l.trim_start().starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n");
    let body = body.as_str();

    assert!(
        !body.contains("\"asserted\""),
        "the asserted-identity arm is back in tool_gate_escalation_claimable: an unproven \
         caller must be REFUSED, not served under a label. This surface reports the caller's \
         OWN permissions and a caller-supplied plugin_id lets one member enumerate another's."
    );
    assert!(
        !body.contains("args.get(\"plugin_id\")"),
        "tool_gate_escalation_claimable reads a caller-supplied plugin_id again; identity here \
         must come from resolve_attributed_caller and nowhere else"
    );
    // Positive control: the refusal path must still exist, or the two assertions above would
    // also pass on a handler that had been deleted entirely.
    assert!(
        body.contains("resolve_attributed_caller") && body.contains("cannot determine who is asking"),
        "positive control failed: the proven-identity path and its refusal message are gone, \
         so the negative assertions above prove nothing"
    );
}
