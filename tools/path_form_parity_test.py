#!/usr/bin/env python3
"""The Python path form answers to the same table as the Rust one (hestia #1743, step 1).

core/src/path_form.rs RECORDS grants (the daemon) and plugins/_shared/hestia_path_form.py will
ENFORCE them (the gate). Both read fixtures/path-form/cases.json; the Rust half is pinned by
`cargo test --lib path_form`, this file pins the Python half. A result that moves in one and not
the other fails here or there, so the daemon and the gate cannot quietly disagree about which
file a Windows spelling names.

Run: python3 tools/path_form_parity_test.py
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "plugins" / "_shared"))

import hestia_path_form as pf  # noqa: E402

CASES = json.loads((REPO / "fixtures" / "path-form" / "cases.json").read_text(encoding="utf-8"))
RUST = (REPO / "core" / "src" / "path_form.rs").read_text(encoding="utf-8")


def test_every_canonical_case_holds():
    rows = CASES["canonical"]
    assert len(rows) >= 40, f"the table shrank to {len(rows)} rows"
    failures = []
    for case in rows:
        raw, dialect = case["raw"], case["dialect"]
        try:
            got = ("ok", pf.canonical(raw, dialect))
        except pf.PathRefused as e:
            got = ("refused", e.code)
        want = ("ok", case["ok"]) if "ok" in case else ("refused", case["refused"])
        if got != want:
            failures.append(f"{dialect} {raw!r}: got {got}, want {want} ({case['why']})")
    assert not failures, f"{len(failures)} case(s) failed:\n" + "\n".join(failures)


def test_every_same_and_within_case_holds():
    failures = []
    for case in CASES["same"]:
        d = case["dialect"]
        a, b = pf.canonical(case["a"], d), pf.canonical(case["b"], d)
        if (pf.match_key(a, d) == pf.match_key(b, d)) != case["same"]:
            failures.append(f"same {d} {case['a']!r} {case['b']!r}: want {case['same']}")
    for case in CASES["within"]:
        d = case["dialect"]
        root, cand = pf.canonical(case["root"], d), pf.canonical(case["candidate"], d)
        if pf.is_within(root, cand, d) != case["within"]:
            failures.append(f"within {d} {root!r} {cand!r}: want {case['within']}")
    assert not failures, "\n".join(failures)


def test_every_refusal_code_is_exercised_and_matches_rust():
    used = {c["refused"] for c in CASES["canonical"] if "refused" in c}
    missing = set(pf.REFUSAL_CODES) - used
    assert not missing, f"no case is refused as {sorted(missing)}"
    for code in pf.REFUSAL_CODES:
        assert f'=> "{code}"' in RUST, f"Rust Refusal::code has no {code!r}"


def test_a_canonical_path_is_its_own_canonical_form():
    for case in CASES["canonical"]:
        if "ok" in case:
            assert pf.canonical(case["ok"], case["dialect"]) == case["ok"], case


def test_the_host_dialect_is_never_git_bash():
    assert pf.host_dialect() in (pf.POSIX, pf.WINDOWS)


TESTS = [
    test_every_canonical_case_holds,
    test_every_same_and_within_case_holds,
    test_every_refusal_code_is_exercised_and_matches_rust,
    test_a_canonical_path_is_its_own_canonical_form,
    test_the_host_dialect_is_never_git_bash,
]


def main() -> int:
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        # An explicit list can go stale; that is a red, not a silently smaller run.
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print("all passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
