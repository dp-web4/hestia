#!/usr/bin/env python3
"""Contract tests for `classify_terminal` in tools/await_escalation.py — the SENTENCES.

The exit codes were never wrong. What was wrong is what got printed beside them, and prose is
the part of a tool no type check reaches: for every terminal payload the daemon can produce
where the record has been REAPED, this file printed

    <id>: expired — no decision landed in the window.

which is an assertion about history the daemon never made. `reap()` deletes DECIDED rows on
the same clock as lapsed ones (`expires_at + REAP_KEEP_SECS`, run inside every `open()`), so
an hour past TTL an approved-and-spent grant is byte-identical to a petition nobody ruled.

MEASURED, and this is why the file exists: 2026-09-02, kimi-code reviewing mesh notices
9313-9391 polled seven decided escalations ~6h after their decisions — five approved and
claimed, two approved and lapsed unspent — and this tool rendered all seven as "no decision
landed in the window". Seven of seven. The two lapsed ones are not "accidentally right": a
decision landed on those too (+13s and +112s), it simply went unclaimed.

The discriminator was in the payload the whole time. `bar` is the row's own field, so it is
`null` exactly when the daemon holds no row — reaped, or never existed — and non-null when a
real pending row lapsed undecided. hestia#544 is the same shape in the two DECIDING tools and
is still open; it carved the poll out as "deliberate and right", which is true of the verdict
and not of the sentence printed next to it.

Run: python3 tools/await_escalation_test.py   (or via pytest)
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "await_escalation", os.path.join(_HERE, "await_escalation.py"))
ae = importlib.util.module_from_spec(_spec)
sys.modules["await_escalation"] = ae
_spec.loader.exec_module(ae)

ID = "a5b01c819a3a0807"

# A row the daemon still holds and has not ruled, past its TTL. Every field the row owns is
# present; `bar` is what says the row is present at all.
LAPSED_UNDECIDED = {
    "escalation_id": ID, "status": "expired", "permits_write": False, "granted": False,
    "claim_window_secs_remaining": None, "consumed_at": None, "bar": "single_approver",
    "bar_met": False, "factors_present": [], "secs_remaining": 0, "decided_by": None,
}

# The same id after `reap`. `status_of` falls through to `unwrap_or(Status::Expired)` and
# every row-owned field goes null — which is exactly the shape kimi-code polled.
REAPED = {
    "escalation_id": ID, "status": "expired", "permits_write": False, "granted": False,
    "claim_window_secs_remaining": 0, "consumed_at": None, "bar": None, "bar_met": None,
    "factors_present": None, "secs_remaining": 0, "decided_by": None,
}


def test_a_reaped_row_does_not_claim_that_nobody_ruled():
    code, msg, err = ae.classify_terminal(ID, REAPED)
    assert code == 5, f"still fails closed: {code}"
    assert err is True, "a non-grant is not stdout news"
    assert "no decision landed" not in msg, (
        "THE DEFECT: the tool asserted a fact about history it cannot know. A reaped row is "
        f"silent about its own disposition, not evidence of silence. got: {msg}")
    assert "NO ROW" in msg, f"it must say what it actually observed: {msg}"
    assert "chain" in msg, f"and where the durable answer is: {msg}"


def test_a_row_that_is_present_and_unruled_still_says_so():
    # The honest use of the sentence. Removing it entirely would be the opposite error:
    # a lapsed pending row IS a decision that never landed, and the asker needs to hear it.
    code, msg, err = ae.classify_terminal(ID, LAPSED_UNDECIDED)
    assert code == 5, f"{code}"
    assert err is True
    assert "no decision landed in the window" in msg, f"got: {msg}"
    assert "NO ROW" not in msg, f"the row is right there: {msg}"


def test_the_two_expired_shapes_do_not_produce_the_same_message():
    # The whole finding in one assertion. Both are `status: expired`, both exit 5, and until
    # 2026-09-02 both printed the same sentence — so a reviewer could not tell a reaped
    # approval from a petition nobody answered.
    _, reaped_msg, _ = ae.classify_terminal(ID, REAPED)
    _, lapsed_msg, _ = ae.classify_terminal(ID, LAPSED_UNDECIDED)
    assert reaped_msg != lapsed_msg, (
        "one sentence for two different facts is the defect, not a formatting choice")


def test_unknown_status_is_read_the_same_way_as_expired():
    # `status_of` answers `Expired` for an absent id, but the tool must not depend on which
    # of the two words the daemon chose: the ROW-PRESENCE test is what carries the meaning.
    payload = dict(REAPED, status="unknown")
    code, msg, _ = ae.classify_terminal(ID, payload)
    assert code == 5, f"{code}"
    assert "NO ROW" in msg, f"got: {msg}"


def test_a_spent_grant_is_named_as_spent_not_merely_dead():
    # Exit 3 covers two different facts too — SPENT and LAPSED — and `consumed_at` is the
    # field the daemon added so nobody has to substring-match the note.
    spent = {"status": "approved", "permits_write": False, "claim_window_secs_remaining": 0,
             "consumed_at": 1_800_000_500, "bar": "single_approver", "bar_met": True}
    code, msg, err = ae.classify_terminal(ID, spent)
    assert code == 3, f"{code}"
    assert err is True
    assert "CLAIMED" in msg and "1800000500" in msg, f"got: {msg}"


def test_an_approved_grant_that_lapsed_unspent_is_not_called_claimed():
    lapsed = {"status": "approved", "permits_write": False, "claim_window_secs_remaining": 0,
              "consumed_at": None, "bar": "single_approver", "bar_met": True}
    code, msg, _ = ae.classify_terminal(ID, lapsed)
    assert code == 3, f"{code}"
    assert "LAPSED" in msg and "CLAIMED" not in msg, f"got: {msg}"


def test_a_live_grant_still_tells_the_holder_to_spend_it():
    # The one payload that must NOT go to stderr, and the only branch that returns 0.
    live = {"status": "approved", "permits_write": True, "claim_window_secs_remaining": 412,
            "consumed_at": None, "bar": "single_approver", "bar_met": True}
    code, msg, err = ae.classify_terminal(ID, live)
    assert code == 0, f"{code}"
    assert err is False, "a claimable grant is the answer the caller waited for"
    assert "412" in msg and "VERBATIM" in msg, f"got: {msg}"


def test_a_denial_carries_its_reason():
    code, msg, err = ae.classify_terminal(ID, {"status": "denied", "reason": "out of grammar",
                                               "bar": "single_approver"})
    assert code == 4, f"{code}"
    assert err is False
    assert "out of grammar" in msg, f"got: {msg}"


TESTS = [
    test_a_reaped_row_does_not_claim_that_nobody_ruled,
    test_a_row_that_is_present_and_unruled_still_says_so,
    test_the_two_expired_shapes_do_not_produce_the_same_message,
    test_unknown_status_is_read_the_same_way_as_expired,
    test_a_spent_grant_is_named_as_spent_not_merely_dead,
    test_an_approved_grant_that_lapsed_unspent_is_not_called_claimed,
    test_a_live_grant_still_tells_the_holder_to_spend_it,
    test_a_denial_carries_its_reason,
]


def main():
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, e))
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
