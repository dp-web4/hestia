#!/usr/bin/env python3
"""Pins the four things `report()` must never confuse with a deployment date.

The walk itself is exercised live (the docstring's worked example reproduces
byte-for-byte). What is pinned here is the REPORTING, because three of its four
branches only fire on chains this box does not have, and an unexercised branch that
prints a plausible timestamp is the exact failure this tool exists to replace.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vintage_from_wire import report


def R(with_ts, without_ts, inter=None, nulls=(), wpos=None, wopos=None):
    """Rows now carry a distinct `pos`, because chain position is the total order the
    tool sorts and compares on -- a shared `pos: 0` would make every ordering test
    vacuous, which is what the first version of this helper did."""
    wpos = wpos if wpos is not None else [i * 10 + 5 for i in range(len(with_ts))]
    wopos = wopos if wopos is not None else [i * 10 for i in range(len(without_ts))]
    w = [{"ts": t, "pos": p, "plugin": "p"} for t, p in zip(with_ts, wpos)]
    wo = [{"ts": t, "pos": p, "plugin": "p"} for t, p in zip(without_ts, wopos)]
    if inter is None:
        key = lambda r: (r["pos"], r["ts"])
        inter = [r for r in wo if w and key(r) >= key(w[0])]
    return {"event_type": "e", "field": "f", "hops_walked": 100,
            "rows": len(w) + len(wo), "with": w, "without": wo, "interleaved": inter,
            "null_valued": list(nulls)}


def test_clean_partition_names_the_gap():
    out = report(R(["2026-08-25T17:38:30"], ["2026-08-25T05:17:03"],
                   wpos=[20], wopos=[10]))
    assert "CLEAN PARTITION" in out, out
    assert "IN FORCE BETWEEN 2026-08-25T05:17:03 AND 2026-08-25T17:38:30" in out, out


def test_interleaving_refuses_to_name_a_date():
    """The load-bearing one. Two writers, or a conditional field, is NOT a cutover."""
    out = report(R(["2026-08-25T10:00:00"], ["2026-08-25T09:00:00",
                                             "2026-08-25T11:00:00"],
                   wpos=[20], wopos=[10, 30]))
    assert "NOT A DEPLOYMENT BOUNDARY" in out, out
    assert "IN FORCE BETWEEN" not in out, "an interleaved chain must not name a date: " + out


def test_all_present_is_not_always_present():
    """Absence needs a denominator: the cutover may be below the window."""
    out = report(R(["2026-08-25T10:00:00", "2026-08-25T11:00:00"], []))
    assert "cutover is below" in out, out
    assert "IN FORCE BETWEEN" not in out, out


def test_all_absent_says_not_deployed_not_never():
    out = report(R([], ["2026-08-25T10:00:00"]))
    assert "not deployed" in out, out
    assert "IN FORCE BETWEEN" not in out, out


def test_equal_second_interleave_is_still_interleave():
    """codex review of #614, finding 2. A present row followed IN THE SAME SECOND by an
    absent row is a contradiction, and truncating the timestamp to seconds hid it: the
    strict `>` comparison scored zero interleaving and printed CLEAN PARTITION. Chain
    position separates them even when the second does not."""
    ts = "2026-08-25T17:38:30"
    out = report(R([ts], [ts], wpos=[20], wopos=[21]))
    assert "NOT A DEPLOYMENT BOUNDARY" in out, out
    assert "IN FORCE BETWEEN" not in out, "same-second reversal must not name a date: " + out


def test_explicit_null_is_present_not_absent():
    """codex review of #614, finding 1. A key emitted with a null value is PRESENT. If it
    counted as absent it would manufacture a cutover out of a writer that always emitted
    the field. The report must say so rather than dating anything on it."""
    out = report(R(["2026-08-25T17:38:30"], ["2026-08-25T05:17:03"],
                   nulls=[{"ts": "2026-08-25T17:38:30", "pos": 20, "plugin": "p"}],
                   wpos=[20], wopos=[10]))
    assert "explicit" in out and "NULL" in out, out


def test_no_rows_says_widen_the_window():
    out = report(R([], []))
    assert "widen --hops" in out, out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
