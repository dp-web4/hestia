//! The claim window burns from when the asker SAW the decision, not from when it was made.
//!
//! WHY. Measured four times across two seats, 2026-08-23..27: an approval granted and then
//! never claimed, because the member did not learn it existed until the window had closed. The
//! fuse ran from `decided_at`, so what it actually measured was PROXIMITY TO THE OPERATOR — a
//! member in live conversation claimed inside it; a member working asynchronously watched five
//! grants die unspent. On 2026-08-27 the only delivery channel that worked, four times running,
//! was the operator saying "approved" out loud in chat.
//!
//! Lengthening the window changes the odds, not the bias. The clock was keyed to the wrong
//! event.
//!
//! WHY THIS IS SAFE NOW. GPT's standing objection to wider claim windows is exact: a longer
//! window enlarges the SUBSTITUTION POOL. Since #539/#565 a claim matches on `act_digest` and a
//! missing binding is explicitly not a match, so a live grant can only ever be spent on the act
//! it was minted for. The objection is answered by the binding rather than waived.
//!
//! WHAT IS PINNED, and every one of these fails if the change is wrong in a DIFFERENT direction:
//!   1. unobserved behaves EXACTLY as before (this is the no-regression half, and it is the one
//!      a careless "just make the window bigger" would break);
//!   2. observation moves the horizon, so the fix actually does something;
//!   3. the `expires_at + WINDOW` ceiling still caps an observation made late;
//!   4. observation is ONE-WAY, so a member cannot hold a grant open by polling in a loop;
//!   5. a non-asker cannot move someone else's clock;
//!   6. a poll BEFORE the ruling starts nothing — the arm the first cut got wrong, and the
//!      one PINS 1-5 could not see because every one of them observes AFTER a decision;
//!   7. a DENIAL bears no approval to observe.
//!
//! Pins 6 and 7 exist because of a blocking review (GPT/Nova) of the first implementation:
//! `poll` marked observation before reading status, so the ORDINARY flow — an asker polling
//! while its petition is still pending — started the fuse against a ruling that did not yet
//! exist. A change written to stop grants dying unclaimed made them die sooner. The fixture
//! that felt natural to write was the single arm the defect did not live in.

use hestia::server::gate_escalation::{
    Channel, EscalationStore, APPROVAL_CLAIM_WINDOW_SECS, DEFAULT_TTL_SECS,
};

const T0: u64 = 1_800_000_000;
const SEAT: &str = "claude-code";
const ACT: &str = "Edit -> law_inject.py";

fn opened_and_approved(decided_at: u64) -> (EscalationStore, String) {
    let mut s = EscalationStore::default();
    let e = s
        .open(SEAT, "role:constellation:member", "Edit", "law_inject.py",
              Some(ACT), None, None, T0, DEFAULT_TTL_SECS)
        .expect("open");
    let id = e.id.clone();
    s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli,
             None, Some("ok"), decided_at)
        .expect("decide");
    (s, id)
}

/// PIN 1 — an UNOBSERVED grant is unchanged. The no-regression half.
///
/// This is the assertion that a naive "widen the window" fix fails. Nothing about this change
/// may make a grant nobody looked at live one second longer than it did before.
#[test]
fn an_unobserved_grant_still_dies_one_window_after_the_decision() {
    let decided = T0 + 1;
    let (s, _) = opened_and_approved(decided);
    let old_horizon = decided + APPROVAL_CLAIM_WINDOW_SECS;

    assert_eq!(s.claimable_for(SEAT, old_horizon - 1).len(), 1,
        "still claimable one second inside the old window");
    assert!(s.claimable_for(SEAT, old_horizon).is_empty(),
        "an unobserved grant MUST still expire at decided_at + {APPROVAL_CLAIM_WINDOW_SECS}. \
         If this fails, the change widened the window for members who never looked, which is \
         the substitution-pool objection and not the fix.");
}

/// PIN 2 — observation moves the horizon. The half that proves the fix does anything.
#[test]
fn observing_the_decision_starts_the_window_from_that_moment() {
    let decided = T0 + 1;
    let (mut s, id) = opened_and_approved(decided);
    let old_horizon = decided + APPROVAL_CLAIM_WINDOW_SECS;

    // The member learns about it LATE — after the old window would have closed.
    let learned_at = old_horizon + 60;
    assert!(s.mark_observed(&id, SEAT, learned_at), "the asker's first observation must record");

    assert_eq!(s.claimable_for(SEAT, learned_at).len(), 1,
        "the grant must be claimable at the moment it was observed, even though the old \
         decided_at window had already closed — this is the entire point");
    assert_eq!(s.claimable_for(SEAT, learned_at + APPROVAL_CLAIM_WINDOW_SECS - 1).len(), 1,
        "and for a full window from observation");
    assert!(s.claimable_for(SEAT, learned_at + APPROVAL_CLAIM_WINDOW_SECS).is_empty(),
        "the fuse is a WINDOW from observation, not an extension without end");
}

/// PIN 3 — the record ceiling still caps a late observation.
#[test]
fn observation_cannot_outlive_the_record() {
    let (mut s, id) = opened_and_approved(T0 + 1);
    // Observed at the last possible instant of the record's life.
    let very_late = T0 + DEFAULT_TTL_SECS - 1;
    assert!(s.mark_observed(&id, SEAT, very_late));

    let ceiling = T0 + DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS;
    assert!(s.claimable_for(SEAT, ceiling).is_empty(),
        "expires_at + {APPROVAL_CLAIM_WINDOW_SECS} must remain an absolute ceiling: observation \
         restarts the fuse, it does not detach the grant from the record's lifetime");
}

/// PIN 4 — observation is ONE-WAY. A member cannot hold a grant open by polling repeatedly.
#[test]
fn only_the_first_observation_counts() {
    let (mut s, id) = opened_and_approved(T0 + 1);
    let first = T0 + 100;
    assert!(s.mark_observed(&id, SEAT, first), "first observation records");
    assert!(!s.mark_observed(&id, SEAT, first + 500),
        "a second observation must NOT record — otherwise a poll loop is an infinite window");
    assert!(s.claimable_for(SEAT, first + APPROVAL_CLAIM_WINDOW_SECS).is_empty(),
        "the horizon must still be measured from the FIRST observation");
}

/// PIN 5 — a non-asker cannot move the clock.
///
/// The read side of `poll` is deliberately open to anyone; moving a deadline is not. Without
/// this, an asserted identity could extend — or by racing, prematurely start — another member's
/// window. Same boundary GPT/Nova blocked on the claimable surface.
#[test]
fn a_peer_cannot_start_another_members_fuse() {
    let (mut s, id) = opened_and_approved(T0 + 1);
    assert!(!s.mark_observed(&id, "kimi-code", T0 + 100),
        "a member that is not the asker must not be able to record an observation");
    // Positive control: the owning seat still can, so the assertion above is about identity
    // and not about an escalation that refuses every observation.
    assert!(s.mark_observed(&id, SEAT, T0 + 100),
        "positive control: the asker's own observation must still record");
}

/// PIN 6 — a poll BEFORE the ruling must not start the fuse.
///
/// GPT/Nova blocking review of the first cut, and the differential it specified. `poll` marks
/// observation before it reads status, and the first `mark_observed` checked only asker
/// identity — so the ORDINARY flow, an asker polling while its petition is still pending,
/// stamped `observed_at` immediately. `decided_horizon()` then preferred that pre-decision
/// timestamp over `decided_at`, and the claim fuse could burn out BEFORE the ruling existed.
///
/// A change written to stop grants dying unclaimed made them die sooner. PINS 1-5 could not
/// see it because every one of them observes AFTER a decision: the fixture that felt natural
/// to write was the one arm the defect does not live in.
#[test]
fn polling_a_pending_petition_does_not_start_the_fuse() {
    let mut s = EscalationStore::default();
    let e = s
        .open(SEAT, "role:constellation:member", "Edit", "law_inject.py",
              Some(ACT), None, None, T0, DEFAULT_TTL_SECS)
        .expect("open");
    let id = e.id.clone();

    // The asker polls one second in, while nobody has ruled. This is the NORMAL thing to do
    // and it must record nothing.
    assert!(!s.mark_observed(&id, SEAT, T0 + 1),
        "observation of a PENDING petition must not record: there is no grant to observe, \
         and stamping here starts a fuse against a ruling that does not exist yet");

    // The operator rules twenty minutes later — long past where the bogus fuse would have
    // expired (T0 + 1 + 600 = T0 + 601).
    s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli,
             None, Some("ok"), T0 + 1200).expect("decide");

    // Unobserved, so the horizon is the decision's: the grant is alive right after the ruling.
    assert_eq!(s.claimable_for(SEAT, T0 + 1201).len(), 1,
        "the grant must be live immediately after the ruling — if the pending poll had \
         started the fuse, this is where it would already be dead");

    // NOW the asker's poll counts, and a full window runs from THIS moment.
    let learned = T0 + 1500;
    assert!(s.mark_observed(&id, SEAT, learned),
        "the first observation of an APPROVED record must record");
    assert_eq!(s.claimable_for(SEAT, learned + APPROVAL_CLAIM_WINDOW_SECS - 1).len(), 1,
        "a full window begins at the first proven poll after the decision");
    assert!(s.claimable_for(SEAT, learned + APPROVAL_CLAIM_WINDOW_SECS).is_empty(),
        "and it is a window, not an extension without end");
}

/// PIN 7 — a DENIED record cannot be observed either.
///
/// `mark_observed` gates on approved-and-bar-met rather than merely decided, because a denial
/// is a decision too. Recording observation against one would be harmless today (a denied row
/// is never claimable) and load-bearing the moment anything else reads `observed_at`.
#[test]
fn observing_a_denial_records_nothing() {
    let mut s = EscalationStore::default();
    let e = s
        .open(SEAT, "role:constellation:member", "Edit", "law_inject.py",
              Some(ACT), None, None, T0, DEFAULT_TTL_SECS)
        .expect("open");
    let id = e.id.clone();
    s.decide(&id, false, "dp", "role:constellation:sovereign", Channel::LocalCli,
             None, Some("no"), T0 + 10).expect("decide");

    assert!(!s.mark_observed(&id, SEAT, T0 + 20),
        "a refusal is a decision, but it bears no approval to observe");
    // Positive control: the same fixture with a GRANT does record, so the assertion above is
    // about the verdict and not about a store that refuses every observation.
    let mut ok = EscalationStore::default();
    let g = ok.open(SEAT, "role:constellation:member", "Edit", "law_inject.py",
                    Some(ACT), None, None, T0, DEFAULT_TTL_SECS).expect("open");
    ok.decide(&g.id, true, "dp", "role:constellation:sovereign", Channel::LocalCli,
              None, Some("ok"), T0 + 10).expect("decide");
    assert!(ok.mark_observed(&g.id, SEAT, T0 + 20), "positive control: an approval records");
}
