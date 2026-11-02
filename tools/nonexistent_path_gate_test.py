#!/usr/bin/env python3
"""Existence first (hestia #1411).

dp, 2026-10-26: "we should not be doing escalations on nonexistent paths because there is nothing
to escalate - it's just noise"; "we should be checking existence first"; and "the not visible to you
should only come on an existing path thats off limits". Measured on cbp-being: nine operator cards
for `<ws>/hestia/governance/...`, a doubled root, while the refusal said "'hestia' is not granted".

Run: python3 tools/nonexistent_path_gate_test.py
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grant_modes_gate_test as g  # noqa: E402

core, m = g.core, g.m


def check(name, cond, detail=""):
    assert cond, f"{name} — {detail}"


def _pol(ws):
    # the being's shape: the governance snapshot granted recursively, read-only
    snap = g._snapshot(ws, by_mode=[g._grant(ws + "/governance", "r", True)])
    return g._policy(snap)


def _world(ws):
    real = ws + "/governance/hestia/hooks-gt/_shared"
    os.makedirs(real, exist_ok=True)
    open(real + "/gate.py", "w").close()
    os.makedirs(ws + "/hestia", exist_ok=True)          # the writable repo exists ...
    open(ws + "/hestia/README.md", "w").close()
    return real + "/gate.py"


def test_a_read_of_a_nonexistent_path_says_so_and_escalates_nothing():
    with g._Workspace() as ws:
        real = _world(ws)
        prof, pol = _pol(ws)
        doubled = ws + "/hestia/governance/hestia/hooks-gt/_shared/gate.py"  # ... this does not
        v = g._verdict(prof, pol, ws, "Read", path=doubled, materialize=False)
        check("refused", v.blocks, str(v))
        check("rule", v.rule == "mrh.path.nonexistent", v.rule)
        check("says_does_not_exist", "does not exist" in v.reason, v.reason)
        check("did_you_mean_the_grant", f"did you mean '{real}'" in v.reason, v.reason)
        check("not_scope_escalating", v.rule not in m.SCOPE_ESCALATING_RULES)
        check("no_not_granted_wording", "is not granted" not in v.reason, v.reason)


def test_an_existing_off_limits_path_is_still_the_ordinary_scope_refusal():
    with g._Workspace() as ws:
        _world(ws)
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Read", path=ws + "/hestia/README.md")
        check("refused", v.blocks, str(v))
        check("rule_is_mrh_path", v.rule == "mrh.path", v.rule)
        check("escalates_as_before", v.rule in m.SCOPE_ESCALATING_RULES)
        check("no_does_not_exist", "does not exist" not in v.reason, v.reason)


def test_a_write_creating_a_file_in_an_existing_dir_is_still_a_real_ask():
    with g._Workspace() as ws:
        _world(ws)
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Write", path=ws + "/hestia/new-note.md", materialize=False)
        check("refused", v.blocks, str(v))
        check("rule_is_mrh_path", v.rule == "mrh.path", v.rule)


def test_a_write_into_a_new_directory_is_still_a_real_ask():
    # dp: "how is mkdir or a new file write handled" -- creating a path is an ordinary write
    with g._Workspace() as ws:
        _world(ws)
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Write", path=ws + "/hestia/nope/also-nope/x.md", materialize=False)
        check("rule_is_mrh_path", v.rule == "mrh.path", v.rule)
        check("escalates", v.rule in m.SCOPE_ESCALATING_RULES)


def test_a_nonexistent_read_with_no_matching_grant_has_no_hint():
    with g._Workspace() as ws:
        _world(ws)
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Read", path=ws + "/hestia/nothing-like-it.md", materialize=False)
        check("rule", v.rule == "mrh.path.nonexistent", v.rule)
        check("no_hint", "did you mean" not in v.reason, v.reason)


def test_a_granted_read_of_a_nonexistent_path_is_not_refused_by_the_gate():
    # inside the grant the gate allows it and the tool itself reports not-found (no escalation)
    with g._Workspace() as ws:
        _world(ws)
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Read", path=ws + "/governance/hestia/missing.py", materialize=False)
        check("allowed", not v.blocks, str(v))


def test_the_hint_is_withheld_when_the_grant_is_exact():
    # codex/kimi on #1412: an EXACT grant on the root does not reach a child, so a hint that
    # names the child would send the member to a second refusal
    with g._Workspace() as ws:
        real = _world(ws)
        snap = g._snapshot(ws, by_mode=[g._grant(ws + "/governance", "r", False)])
        prof, pol = g._policy(snap)
        v = g._verdict(prof, pol, ws, "Read", path=ws + "/hestia/governance/hestia/hooks-gt/_shared/gate.py",
                       materialize=False)
        check("rule", v.rule == "mrh.path.nonexistent", v.rule)
        check("no_hint_for_exact", "did you mean" not in v.reason, v.reason)
        check("real_exists", os.path.exists(real))


def test_the_hint_is_withheld_when_the_candidate_escapes_its_grant_by_symlink():
    # codex/kimi on #1412: lexists is true for a symlink whose target is outside the grant;
    # confirming it would be an existence oracle for a path the member may not read
    with g._Workspace() as ws:
        _world(ws)
        outside = ws + "/hestia/outside.txt"
        open(outside, "w").close()
        os.symlink(outside, ws + "/governance/hestia/hooks-gt/_shared/link.txt")
        prof, pol = _pol(ws)
        v = g._verdict(prof, pol, ws, "Read", path=ws + "/hestia/governance/hestia/hooks-gt/_shared/link.txt",
                       materialize=False)
        check("rule", v.rule == "mrh.path.nonexistent", v.rule)
        check("no_hint_for_escaping_symlink", "did you mean" not in v.reason, v.reason)



TESTS = [
    test_a_read_of_a_nonexistent_path_says_so_and_escalates_nothing,
    test_an_existing_off_limits_path_is_still_the_ordinary_scope_refusal,
    test_a_write_creating_a_file_in_an_existing_dir_is_still_a_real_ask,
    test_a_write_into_a_new_directory_is_still_a_real_ask,
    test_a_nonexistent_read_with_no_matching_grant_has_no_hint,
    test_a_granted_read_of_a_nonexistent_path_is_not_refused_by_the_gate,
    test_the_hint_is_withheld_when_the_grant_is_exact,
    test_the_hint_is_withheld_when_the_candidate_escapes_its_grant_by_symlink,
]

if __name__ == "__main__":
    listed = {t.__name__ for t in TESTS}
    defined = {k for k in globals() if k.startswith("test_")}
    if listed != defined:
        print(f"TESTS is stale: missing {sorted(defined - listed)}, extra {sorted(listed - defined)}")
        sys.exit(1)
    failed = []
    for t in TESTS:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"PASS: {len(TESTS)} nonexistent-path tests")
