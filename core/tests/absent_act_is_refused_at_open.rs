//! #565 arm 3 — an escalation that names NO act must be refused at `open`, not granted and
//! then stranded.
//!
//! WHY THIS FILE EXISTS. #539 bound a gate approval to the act it was granted for. The first
//! version bound the digest to `stated_reason`, which is an act string on the gate-hook door
//! and a rationale on the member door, so the two doors could never match — legion's review
//! of PR #565. That was fixed by giving `open` a `stated_act` argument of its own.
//!
//! legion's follow-up review (2026-08-21) measured that the fix closed the *mismatched*
//! digest and left the *absent* one open, and that absent reproduces the identical loop:
//!
//! ```text
//! opened id=5bd71e907e89b2a8 act_digest=None
//! claim with act -> None
//! reopened id=29b944ac3d91c77f (first was 5bd71e907e89b2a8)
//! 200 approve->fail->reopen cycles with NO refusal: quota never engaged
//! ```
//!
//! Open with no act → operator approves → member re-issues the write → the hook presents the
//! real act → no match (`None == None` is explicitly not a match in `claim`) → and because
//! `hestia_gate_escalation_claim` is claim-OR-open, the refused claim mints a fresh
//! escalation. An approval that burns an operator decision and can never be spent, and a
//! queue that grows once per retry.
//!
//! `MAX_PENDING` does not backstop it, and the reason is worth keeping: the quota counts
//! `Status::Pending` and these rows are *Approved*. The obvious cap misses this by
//! construction — which is why the guard is at the mint site and not in the quota.
//!
//! WHAT THIS FILE IS. A closed-defect regression pin, not an open-defect pin: GREEN while
//! the guard stands, and it goes RED the moment a `None`-digest row becomes mintable again.
//! PIN 4 is the arm that makes the rest mean something — it walks the exact cycle legion
//! measured and shows it now terminates at the first step, with nothing minted.

//!
//! CALL ORDER, adapted 2026-08-25 when this file was rescued onto main. This branch predates
//! the merged form of #565 (codex's), which orders `open` as
//! `(plugin_id, role, tool, marker, ACT, stated_reason, stated_detail, now, ttl)` — the act
//! FIRST of the three `Option<&str>`, not last. The original call sites here passed the act
//! last, so every one of them fed a rationale in as the act and the act in as
//! `stated_detail`.
//!
//! Worth stating because the compiler could not help: three consecutive `Option<&str>`
//! parameters make a reorder TYPE-INVISIBLE. Same arity, same types, clean build, opposite
//! meaning. This file failed loudly only because its assertions are refusal-shaped; a test
//! asserting success would have passed while measuring nothing.

use hestia::server::gate_escalation::{Channel, EscalationStore, Status, DEFAULT_TTL_SECS};

const T0: u64 = 1_800_000_000;

/// A derived act string of the shape the gate hook actually produces — tool-name prefixed,
/// which is the property that makes it un-reconstructable by the member and is therefore why
/// the deny text has to print it. Nothing here depends on the value, only on both ends
/// agreeing.
const ACT: &str = "Edit -> /home/dp/ai-agents/hestia/core/src/server/law_inject.py";

fn store_with_one_open(act: Option<&str>) -> (EscalationStore, Result<String, String>) {
    let mut s = EscalationStore::default();
    let r = s
        .open(
            "kimi-code",
            "role:constellation:member",
            "Edit",
            "law_inject.py",
            act,
            Some("I need this write to land the arbiter fix"),
            None,
            T0,
            DEFAULT_TTL_SECS,
        )
        .map(|e| e.id)
        .map_err(|e| e.to_string());
    (s, r)
}

/// PIN 1 — the member door's own case: absent `act` is REFUSED.
///
/// This is the assertion that was false before the guard. It is stated over all three
/// spellings of "absent" a caller can produce through `optional_string`, because the field is
/// trimmed and empty-filtered downstream and a guard that caught only `None` would let
/// `Some("")` and `Some("   ")` mint the same unspendable row.
#[test]
fn an_escalation_that_names_no_act_is_refused() {
    for absent in [None, Some(""), Some("   "), Some("\t\n ")] {
        let (_s, r) = store_with_one_open(absent);
        let err = r.expect_err(
            "#565 arm 3 REGRESSION: `open` accepted an escalation with no act. That row binds \
             `act_digest: None`, which `claim` can never match, so the approval it earns is \
             unspendable and every retry mints another one — the loop this PR exists to close, \
             reached by the other trigger",
        );
        assert!(
            err.contains("'act' is required"),
            "the refusal must NAME the field, or the member cannot act on it: {err}"
        );
        assert!(
            err.contains("deny text"),
            "the refusal must say WHERE to get the act string. It is derived and truncated, so \
             a member that retypes its own command produces a different string and simply \
             trades this refusal for an unspendable approval: {err}"
        );
    }
}

/// PIN 2 — the refusal is not a blanket tightening: a stated act still opens.
///
/// Guards get written in a hurry and inverted in a hurry. Without this arm, PIN 1 would pass
/// just as happily against an `open` that refused everything.
#[test]
fn a_stated_act_still_opens_and_binds() {
    let (s, r) = store_with_one_open(Some(ACT));
    let id = r.expect("a member that names its act must still be able to escalate");
    let e = s.get(&id).expect("opened escalation is in the store");
    assert!(
        e.act_digest.is_some(),
        "the whole point of requiring the field is that the row carries a digest"
    );
    assert_eq!(e.status_at(T0), Status::Pending, "a fresh escalation is pending");
}

/// PIN 3 — the migration stance survives, which is the reason the guard is in `open` and not
/// in the member-door handler.
///
/// `a_replayed_row_with_no_act_digest_is_unspendable` accepts legacy `None`-digest rows on
/// the argument that "the legacy population drains within one TTL, so the cost is bounded by
/// the hour after deploy". That argument holds only while nothing can mint new ones. `open`
/// is the only mint site; `rehydrate` inserts directly. So the guard must NOT be reachable
/// from the replay path — a legacy row still has to restore, or a restart after deploy would
/// silently drop the pending queue it is supposed to recover.
#[test]
fn the_guard_does_not_block_replay_of_legacy_rows() {
    let mut s = EscalationStore::default();
    let entry = hestia::storage::chain::ChainEntry {
        chain_position: 0,
        hash: String::new(),
        prev_hash: String::new(),
        signer_lct: "test".into(),
        timestamp: chrono::Utc::now(),
        event_type: "gate_escalation_opened".to_string(),
        event_data: serde_json::json!({
            "escalation_id": "legacy1",
            "plugin_id": "kimi-code",
            "role": "role:constellation:member",
            "tool_name": "Edit",
            "marker": "law_inject.py",
            "opened_at": T0,
            "expires_at": T0 + DEFAULT_TTL_SECS,
            // The legacy shape: written before the field existed, so no `act_digest` key.
        }),
    };
    let restored = s.rehydrate(&[entry], T0 + 1);
    assert_eq!(
        restored, 1,
        "REGRESSION: the arm-3 guard leaked into the replay path. A row that predates \
         `act_digest` must still restore — dropping it does not make the legacy population \
         drain, it makes a restart lose the pending queue"
    );
    let e = s.get("legacy1").expect("legacy row restored");
    assert!(
        e.act_digest.is_none(),
        "the legacy row is supposed to come back exactly as it was, digest-less and \
         unspendable — that is the bounded cost the migration stance priced"
    );
}

/// PIN 4 — the cycle legion measured, walked end to end, terminating at step 1.
///
/// The other three pins assert properties. This one reproduces the actual sequence, because
/// the finding was never "a field is unvalidated" — it was "an operator ruling gets burned on
/// something unspendable, once per retry, forever". Structured so that if the guard is ever
/// removed the failure message is the loop itself rather than a bare `unwrap` panic.
#[test]
fn the_approve_fail_reopen_cycle_cannot_start() {
    let mut s = EscalationStore::default();

    // Step 1: the member escalates without naming an act. Under the defect this SUCCEEDS and
    // the remaining steps run; under the guard it stops here, which is the fix.
    let opened = s.open(
        "kimi-code",
        "role:constellation:member",
        "Edit",
        "law_inject.py",
        None,
        Some("please let me write the arbiter fix"),
        None,
        T0,
        DEFAULT_TTL_SECS,
    );

    let why = match opened {
        Err(e) => e.to_string(),
        // Reached only if the guard is gone. Walk the rest of legion's cycle so the failure
        // reports the consequence rather than the symptom.
        Ok(e) => {
            let first = e.id;
            s.decide(
                &first,
                true,
                "dp",
                "role:constellation:sovereign",
                Channel::LocalCli,
                None,
                Some("approved — and this ruling is about to be unspendable"),
                T0 + 10,
            )
            .expect("operator approves");
            let claimed = s.claim("kimi-code", "law_inject.py", Some(ACT), T0 + 20);
            panic!(
                "#565 arm 3 REGRESSION — the loop is live again. Escalation {first} opened with \
                 no act, the operator APPROVED it, and the re-issued write claiming with the \
                 real act got {}. Because `hestia_gate_escalation_claim` is claim-or-open, that \
                 refusal mints a fresh escalation and the member repeats — legion measured 200 \
                 such cycles with no refusal, since `MAX_PENDING` counts Pending and these rows \
                 are Approved.",
                if claimed.is_some() { "a match, which is worse" } else { "nothing" }
            );
        }
    };

    assert!(
        why.contains("'act' is required"),
        "the cycle must stop with a refusal that names the field: {why}"
    );
    // And nothing was minted: the queue the loop used to grow is empty, so there is no
    // operator ruling to burn and nothing for a TTL to drain.
    assert_eq!(
        s.pending(T0 + 10).len(),
        0,
        "a refused open must leave NO row behind — a queue entry here would be the growth the \
         loop was made of, merely relabelled"
    );
}

/// PIN 5 — how far the loop actually reaches, which is NOT as far as either review said.
///
/// Both legion's review and my own commit message for the arm-2 fix call this an "unbounded
/// approval loop that no TTL drains". Measured, that is one notch too high for the path the
/// gate hook actually walks, and the reason is worth pinning because it is the thing that
/// bounds the *remaining* arm.
///
/// `hestia_gate_escalation_claim` is claim-or-open, and when it opens it passes the SAME
/// `stated_act` it just tried to claim with — the real, hook-derived act string. So a failed
/// claim does not merely mint another unspendable row: it mints a CORRECTLY BOUND one. The
/// operator's next ruling lands on a row the very next retry can spend. Cost is one burned
/// ruling and one orphan, then it converges.
///
/// The genuinely unbounded arm needs the member to keep re-escalating through
/// `hestia_gate_escalation_open` instead of waiting on the auto-opened row — which is not
/// contrived, because that is exactly where the deny text routes members. So: unbounded when
/// the member follows the documented instruction, convergent when it retries the write. Arm 3
/// is refused at open now either way; this pin exists so the severity claim in the commit
/// message above it stays honest, and so that a future change to claim-or-open that dropped
/// the act on the auto-open would be caught here rather than re-derived from a live queue.
#[test]
fn a_mismatched_act_costs_one_ruling_and_then_converges() {
    const WRONG: &str = "Edit -> what the member typed from memory";
    let mut s = EscalationStore::default();

    // The member escalates with an act it composed itself. It is well-formed, so the arm-3
    // guard passes it — and it is not the derived string, so it will never match.
    let first = s
        .open("kimi-code", "role:constellation:member", "Edit", "law_inject.py",
              Some(WRONG), Some("I need this write"), None, T0, DEFAULT_TTL_SECS)
        .expect("a stated act opens, right or wrong — the guard checks presence, not truth")
        .id;
    s.decide(&first, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None,
             Some("approved"), T0 + 10)
        .expect("operator rules");
    assert!(
        s.claim("kimi-code", "law_inject.py", Some(ACT), T0 + 20).is_none(),
        "a permit bound to one act must not be spendable on another — that is #539 itself"
    );

    // This is the auto-open the claim door performs on that refusal, with the act it just
    // failed to claim with. THIS is the step that bounds the loop.
    let second = s
        .open("kimi-code", "role:constellation:member", "Edit", "law_inject.py",
              Some(ACT), None, None, T0 + 21, DEFAULT_TTL_SECS)
        .expect("claim-or-open mints the paperwork for the refusal")
        .id;
    assert_ne!(second, first, "a genuinely new row, which is why the queue grew by one");
    s.decide(&second, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None,
             Some("approved"), T0 + 30)
        .expect("operator rules again — this is the ONE burned ruling the loop costs");
    assert!(
        s.claim("kimi-code", "law_inject.py", Some(ACT), T0 + 40).is_some(),
        "REGRESSION in the convergence path: the auto-opened row must be spendable by the \
         retry that caused it. If this fails, claim-or-open has stopped carrying the act \
         through, and the bounded case becomes the unbounded one"
    );
}
