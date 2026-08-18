//! `permits_write` answers a four-conjunct question with two conjuncts, so it goes
//! STALE-TRUE: after the claim horizon closes it keeps saying a permit permits a write,
//! on the one surface whose stated job is to answer exactly that.
//!
//! WHY THIS FILE EXISTS, and how it differs from `claim_horizon_is_never_rendered.rs`.
//! That file (kimi-code, 2026-08-15) pins three ABSENCES: `decided_horizon()` reaches no
//! surface, `retry_within_secs` advertises an unattainable supremum, and the grant reply
//! carries no deadline the asker could compute from. All three are "the system declines to
//! say the true thing."
//!
//! This is the opposite polarity and it is not covered there: the system SAYS A FALSE
//! THING. `permits_write` is not missing — it is present, affirmative, and wrong, for the
//! entire interval between the horizon closing and the row being reaped. Its own sibling
//! `note` is emitted alongside it: *"only `approved` WITH the stated bar met permits the
//! write"*. Both are published about a permit the claim path will refuse.
//!
//! ENFORCEMENT (`is_claimable`, gate_escalation.rs) is a FOUR-way conjunction:
//!
//!     status == Approved  &&  bar_met()  &&  consumed_at.is_none()  &&  now < decided_horizon()
//!
//! REPORTING keeps the first two and drops the last two, in BOTH producers:
//!
//!     gate_escalation.rs  decision_reply()          stored_status() == Approved && bar_met
//!     handler.rs          tool_gate_escalation_poll status.permits_write() && esc.bar_met()
//!
//! The two dropped conjuncts are the only two that are time- and use-dependent. So the
//! reported answer is not a stale copy of the enforced one — it is a DIFFERENT PREDICATE
//! that happens to agree for the first 600 seconds after a grant and can only ever err in
//! the permissive direction.
//!
//! WHY THE EXISTING GUARD CANNOT SEE IT. `one_answer_serves_both_deciding_surfaces`
//! (gate_escalation.rs, test module) asserts, in its own words, *"the reported answer and
//! `is_claimable` are one predicate or they will diverge"* — and evaluates that equality at
//! `T0 + 6`, one second after a grant at `T0 + 5`. At that instant `consumed_at` is `None`
//! and `now < decided_horizon()` holds trivially, so the two omitted conjuncts are both
//! `true` and the comparison is between two expressions that CANNOT differ. It certifies
//! resemblance, which is the thing its docstring says it is not doing. PIN 3 below fires
//! that same guard's assertion at a time where the conjuncts are live, and it fails.
//!
//! LIVE SPECIMEN, off-box, chain-observed 2026-08-18 (claude-code seat):
//! escalation `5725d296b05cbc4c`, `sovereign_plus_peer`, opened 17:11:21Z, decided
//! 17:12:03Z by `operator`. `decided_horizon` = min(decided_at+600, expires_at+600) =
//! 17:22:03Z. A cross-vendor peer factor from `kimi-code` landed at 17:44:03Z — 22 minutes
//! AFTER the horizon closed — flipping `bar_met` false -> true. At 18:45Z the live daemon's
//! `hestia_gate_escalation_poll` returned `"permits_write": true`, `"secs_remaining": 0`,
//! for a permit that had been unclaimable for 83 minutes. Not exploitable: `claim` enforces
//! the horizon and refuses. The damage is to the record a reader weighs, which is the
//! stated purpose of putting the bar on the reply at all (#219).
//!
//! WHAT THIS FILE IS. Three OPEN-DEFECT PINS in the hole-J shape, matching the convention
//! of `claim_horizon_is_never_rendered.rs`: each asserts the CURRENT WRONG BEHAVIOUR, so
//! each is green while the defect stands and RED the moment it is fixed. A red here is the
//! intended end state and each failure message says so.

use hestia::server::gate_escalation::{
    Channel, EscalationStore, APPROVAL_CLAIM_WINDOW_SECS, DEFAULT_TTL_SECS,
};
use std::fs;
use std::path::Path;

const T0: u64 = 1_800_000_000;

/// The expression `tool_gate_escalation_poll` puts on the wire as `permits_write`.
///
/// Bound to the PRODUCER, not re-derived here. A re-derivation would stay green through a
/// fix at the emitting site and report an open defect that had been closed — the failure
/// `fb_derived_constant_needs_producer` names, and the same reasoning
/// `claim_horizon_is_never_rendered.rs` applies to `ADVERTISED_RETRY_EXPR`.
const POLL_PERMITS_WRITE_EXPR: &str =
    r#""permits_write": status.permits_write() && esc.map(|e| e.bar_met()).unwrap_or(false),"#;

/// The expression `Escalation::decision_reply` uses for the same field.
const REPLY_PERMITS_WRITE_EXPR: &str =
    r#"let permits_write = self.stored_status() == Status::Approved && bar_met;"#;

/// The poll surface's note, which does not merely accompany the false field — it asserts
/// CURRENCY ("authoritative as of now") about it. This is the string the live daemon
/// returned at 18:45Z for `5725d296b05cbc4c`, 83 minutes after that grant stopped being
/// claimable.
const POLL_AUTHORITATIVE_NOTE: &str =
    "authoritative as of now; only `approved` WITH the stated bar met permits the write";

/// Production (non-comment) lines of `src/<rel>`. Comments are dropped BEFORE matching so a
/// pin can never be satisfied by the prose that explains it. Borrowed verbatim in shape from
/// `claim_horizon_is_never_rendered.rs`.
fn production_text(rel: &str) -> String {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"));
    text.lines()
        .map(str::trim)
        .filter(|t| !t.starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// Open on a `SingleApprover` marker so a lone sovereign grant meets the bar and the claim
/// path is reachable without a peer factor. Same fixture shape as the sibling file.
fn opened(ttl: u64) -> (EscalationStore, String) {
    let mut s = EscalationStore::default();
    let e = s
        .open(
            "claude-code",
            "role:constellation:member",
            "Edit",
            "law_inject.py",
            None,
            None,
            T0,
            ttl,
        )
        .expect("open");
    (s, e.id)
}

fn approve_at(s: &mut EscalationStore, id: &str, at: u64) {
    s.decide(
        id,
        true,
        "dp",
        "role:constellation:sovereign",
        Channel::LocalCli,
        None,
        Some("ok"),
        at,
    )
    .expect("decide");
}

/// PIN 1 — past the horizon, the reply says `permits_write: true` and the gate refuses.
///
/// Both halves are asserted against the SAME escalation at the SAME instant, so this is a
/// divergence and not two facts about two fixtures. The `claim` call is what makes it a
/// statement about enforcement rather than about a predicate helper.
#[test]
fn the_grant_reply_still_permits_a_write_the_gate_will_refuse() {
    let granted_at = T0 + 4;
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut s, &id, granted_at);

    let horizon = granted_at + APPROVAL_CLAIM_WINDOW_SECS;
    // One second past the last claimable instant. Deliberately NOT far past: the defect is
    // not about a long-abandoned row, it begins the moment the window shuts.
    let after = horizon;

    // Control, at the same fixture: one second BEFORE the horizon everything agrees. Without
    // this the pin below could be reporting a broken fixture rather than a live divergence.
    {
        let esc = s.get(&id).expect("get").clone();
        assert!(
            esc.is_claimable(horizon - 1),
            "control: the permit must be genuinely live just before the horizon"
        );
        assert_eq!(
            esc.decision_reply()["permits_write"].as_bool(),
            Some(true),
            "control: and reported live at the same instant"
        );
    }

    let esc = s.get(&id).expect("get").clone();

    // Enforcement, at `after`.
    assert!(
        !esc.is_claimable(after),
        "fixture error: the horizon did not close at grant + APPROVAL_CLAIM_WINDOW_SECS"
    );
    // And it is not merely the predicate — the act itself is refused.
    assert!(
        s.claim("claude-code", "law_inject.py", after).is_none(),
        "fixture error: a claim past the horizon was honoured"
    );

    // Reporting, at the same instant. THIS is the defect.
    let reply = esc.decision_reply();
    assert_eq!(
        reply["permits_write"].as_bool(),
        Some(true),
        "OPEN-DEFECT PIN 1 has gone RED, which is the intended end state: `decision_reply` \
         no longer reports `permits_write: true` after the claim horizon closes. Confirm the \
         remedy added the two MISSING CONJUNCTS (`consumed_at.is_none()` and \
         `now < decided_horizon()`) rather than merely gating on `secs_remaining`, which is \
         the other clock and would still be wrong for a fast decision."
    );
    // The note ships with it, and it is not merely affirmative — it is an INSTRUCTION TO
    // ACT, sending the asker to re-issue a write the gate has already stopped honouring.
    // `claim_horizon_is_never_rendered.rs` PIN 3 checks for this same branch, but only at
    // the grant instant, where the instruction is still good advice.
    assert!(
        reply["note"]
            .as_str()
            .unwrap_or_default()
            .contains("RE-ISSUE"),
        "OPEN-DEFECT PIN 1(b) has gone RED, which is the intended end state: the reply no \
         longer tells the asker to re-issue a write after the claim horizon has closed. \
         Reply was: {reply}"
    );
}

/// PIN 2 — the same hole in the OTHER producer, which is the one that actually serves the
/// hook.
///
/// `claim_horizon_is_never_rendered.rs` says `decision_reply` "is what a member reads back
/// from BOTH deciding surfaces (`poll` and `arbitrate`)". That is true of `arbitrate` and
/// NOT of `poll`: `tool_gate_escalation_poll` builds its own object and never calls
/// `.decision_reply()`. So there are two independent computations of `permits_write`, both
/// missing the same two conjuncts — which is precisely the failure #219 recorded in this
/// module's own comment: *"two places deciding what 'permits the write' means is how they
/// come to disagree."* They have not disagreed with each other; they have jointly disagreed
/// with the enforcement.
///
/// Producer-bound on both sites, so a fix to one of them turns this red and names the other.
#[test]
fn both_producers_of_permits_write_drop_the_same_two_conjuncts() {
    let handler = production_text("server/handler.rs");
    let escalation = production_text("server/gate_escalation.rs");

    assert!(
        handler.contains(POLL_PERMITS_WRITE_EXPR),
        "OPEN-DEFECT PIN 2(a) has gone RED, which is the intended end state: the poll surface \
         no longer emits `{POLL_PERMITS_WRITE_EXPR}`. If the sibling producer in \
         gate_escalation.rs was NOT changed with it, the two now disagree with each other as \
         well as with `is_claimable`."
    );
    assert!(
        escalation.contains(REPLY_PERMITS_WRITE_EXPR),
        "OPEN-DEFECT PIN 2(b) has gone RED, which is the intended end state: \
         `decision_reply` no longer computes `{REPLY_PERMITS_WRITE_EXPR}`. Check the poll \
         producer in handler.rs moved with it."
    );

    // `poll` does not read the shared answer. Asserted so the claim above is a measurement,
    // not a reading of the comment that says otherwise.
    let poll_fn = handler
        .split("async fn tool_gate_escalation_poll(")
        .nth(1)
        .expect("tool_gate_escalation_poll not found — this pin is measuring nothing");
    let poll_body = poll_fn.split("\n}").next().unwrap_or_default();
    assert!(
        !poll_body.contains(".decision_reply()"),
        "OPEN-DEFECT PIN 2(c) has gone RED: `tool_gate_escalation_poll` now reads the shared \
         answer, so there is one producer again and this pin is obsolete."
    );

    // The poll surface's note asserts currency about the field, unconditionally on the row
    // existing — no branch on the horizon, so an expired grant is described as
    // "authoritative as of now".
    assert!(
        handler.contains(POLL_AUTHORITATIVE_NOTE),
        "OPEN-DEFECT PIN 2(d) has gone RED, which is the intended end state: the poll note \
         no longer claims currency for a field that does not track the horizon."
    );

    // And the enforcing conjunction still carries the two the reporters drop.
    assert!(
        escalation.contains("&& self.consumed_at.is_none()")
            && escalation.contains("&& now < self.decided_horizon()"),
        "`is_claimable` no longer enforces the two conjuncts this file is about; re-derive \
         the divergence before trusting either pin above"
    );
}

/// PIN 3 — the guard that claims to prevent exactly this is evaluated where it cannot fail.
///
/// `one_answer_serves_both_deciding_surfaces` asserts
/// `permits_write == is_claimable(T0 + 6)` after granting at `T0 + 5`. This re-runs that
/// assertion's SHAPE against the same fixture at two times: the time it uses, and a time
/// past the horizon. It passes at the former and fails at the latter, which is the
/// definition of a control that cannot discriminate — the two omitted conjuncts are both
/// trivially `true` at `T0 + 6`, so the equality holds for a reason unrelated to the
/// property it names.
#[test]
fn the_existing_one_predicate_guard_is_evaluated_where_it_cannot_fail() {
    let granted_at = T0 + 5;
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut s, &id, granted_at);
    let esc = s.get(&id).expect("get").clone();
    let reported = esc.decision_reply()["permits_write"]
        .as_bool()
        .expect("permits_write is a bool");

    // The instant the existing guard picks. Equality holds.
    let guard_time = T0 + 6;
    assert_eq!(
        reported,
        esc.is_claimable(guard_time),
        "the existing guard's own assertion must still pass at its own instant, or this pin \
         is describing a test that no longer exists"
    );

    // The same assertion, one horizon later. Equality fails — so the guard's conclusion was
    // a property of the instant it chose, not of the predicate pair.
    let past_horizon = granted_at + APPROVAL_CLAIM_WINDOW_SECS;
    assert_ne!(
        reported,
        esc.is_claimable(past_horizon),
        "OPEN-DEFECT PIN 3 has gone RED, which is the intended end state: the reported answer \
         and `is_claimable` now agree past the claim horizon, i.e. they really are one \
         predicate. The existing guard should be re-anchored to a time past the horizon so it \
         keeps discriminating, and this file deleted."
    );

    // Name the mechanism, so a future reader does not have to re-derive why the guard was blind.
    assert!(
        guard_time < esc.decided_at.unwrap_or(granted_at) + APPROVAL_CLAIM_WINDOW_SECS,
        "the guard's instant must sit INSIDE the claim window for the blindness argument to hold"
    );
}
