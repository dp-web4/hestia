#!/usr/bin/env python3
"""The launch-role bound is law, and it lives in the shared engine (hestia #1084, option b).

dp, 2026-09-22: "only absolutely essential things go into shims. all law goes into shared
engine." These pin `hestia_gate_core.launch_role_verdict` directly, so a seat that wires it gets
the same answer as every other seat. The seat-side behaviour (a hook run refusing an out-of-set
role, an absent role running unverified) stays pinned in projection_consumer_test.py arms 6-8.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / "plugins" / "_shared"
sys.path.insert(0, str(SHARED))
_spec = importlib.util.spec_from_file_location("hestia_gate_core", SHARED / "hestia_gate_core.py")
core = importlib.util.module_from_spec(_spec)
sys.modules["hestia_gate_core"] = core
_spec.loader.exec_module(core)

FAILS = []
P = "role:constellation:interactive-dev,role:constellation:mesh-worker"


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        FAILS.append(f"{name}: {detail}")


def test_a_role_in_the_declared_set_passes_and_reads_verified():
    miswire, verified = core.launch_role_verdict(P, "role:constellation:mesh-worker", "projection /p")
    check("in_set_passes", miswire is None, miswire)
    check("in_set_verified", verified is True, verified)


def test_a_role_outside_the_set_is_a_miswire_naming_the_role():
    miswire, verified = core.launch_role_verdict(P, "role:constellation:sovereign", "projection /p")
    check("out_of_set_is_miswire", miswire is not None and miswire[0] == "config.miswired", miswire)
    check("out_of_set_names_role", miswire is not None and "sovereign" in miswire[1], miswire)
    check("out_of_set_names_source", miswire is not None and "projection /p" in miswire[1], miswire)
    check("out_of_set_not_verified", verified is False, verified)


def test_an_absent_role_is_not_refused_and_reads_unverified():
    """The migration promise GPT held #1084 on: a declared set must not deny an unset role."""
    miswire, verified = core.launch_role_verdict(P, "", "projection /p")
    check("absent_role_not_refused", miswire is None, miswire)
    check("absent_role_unverified", verified is False, verified)


def test_no_declared_set_changes_nothing():
    miswire, verified = core.launch_role_verdict("", "role:anything:at:all", "projection /p")
    check("no_set_passes", miswire is None, miswire)
    check("no_set_unverified", verified is False, verified)


def test_the_set_may_arrive_as_a_list_or_a_comma_string():
    a = core.launch_role_verdict(["x", " y "], "y", "s")
    b = core.launch_role_verdict(" x , y ", "y", "s")
    check("list_and_string_agree", a == b == (None, True), (a, b))


def teardown_module(_module=None):
    assert not FAILS, FAILS


TESTS = [test_a_role_in_the_declared_set_passes_and_reads_verified,
         test_a_role_outside_the_set_is_a_miswire_naming_the_role,
         test_an_absent_role_is_not_refused_and_reads_unverified,
         test_no_declared_set_changes_nothing,
         test_the_set_may_arrive_as_a_list_or_a_comma_string]

if __name__ == "__main__":
    for t in TESTS:
        t()
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print("ok: the launch-role bound is the shared engine's, and agrees on every case")
