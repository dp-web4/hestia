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


def R(with_ts, without_ts, inter=None):
    w = [{"ts": t, "pos": 0, "plugin": "p"} for t in with_ts]
    wo = [{"ts": t, "pos": 0, "plugin": "p"} for t in without_ts]
    if inter is None:
        inter = [r for r in wo if w and r["ts"] > w[0]["ts"]]
    return {"event_type": "e", "field": "f", "hops_walked": 100,
            "rows": len(w) + len(wo), "with": w, "without": wo, "interleaved": inter}


def test_clean_partition_names_the_gap():
    out = report(R(["2026-08-25T17:38:30"], ["2026-08-25T05:17:03"]))
    assert "CLEAN PARTITION" in out, out
    assert "IN FORCE BETWEEN 2026-08-25T05:17:03 AND 2026-08-25T17:38:30" in out, out


def test_interleaving_refuses_to_name_a_date():
    """The load-bearing one. Two writers, or a conditional field, is NOT a cutover."""
    out = report(R(["2026-08-25T10:00:00"], ["2026-08-25T09:00:00",
                                             "2026-08-25T11:00:00"]))
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


def test_no_rows_says_widen_the_window():
    out = report(R([], []))
    assert "widen --hops" in out, out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
