#!/usr/bin/env python3
"""The known_gaps ratchet in operator_surfaces_spec_test.py, exercised the way it was broken.

GPT's re-review of #1138 reproduced a reopening: remove the dashboard's gates calls, restore the two
gates entries in known_gaps, leave `version` alone -- and the checker PASSED, because the v1 ceiling
still held them. Each case below mutates a temporary spec and/or the surface calls and runs the real
checker. A closed gap must never reopen without a deliberate, named migration.

Run: python3 tools/operator_surfaces_ratchet_test.py   (bare; exit 1 on failure)
"""
import copy
import importlib.util
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ops_spec", HERE / "operator_surfaces_spec_test.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

REAL_SPEC = json.loads(C.SPEC.read_text())
REAL_CALLS = C.surface_calls()
REAL_BASELINE = dict(C.KNOWN_GAPS_BASELINE)
GATES = {("GET", "/api/gates/verify"), ("POST", "/api/gates/ratify")}
FAILS = []


def run(spec: dict, calls: dict, baseline: dict | None = None) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "spec.json"
        p.write_text(json.dumps(spec))
        C.SPEC, C.FAILS[:] = p, []
        C.surface_calls = lambda: calls
        C.KNOWN_GAPS_BASELINE = baseline if baseline is not None else dict(REAL_BASELINE)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = C.main([])
    return rc, out.getvalue()


def expect(name: str, rc: int, want_fail: bool, out: str, needle: str = "") -> None:
    ok = (rc != 0) == want_fail and (needle in out if needle else True)
    if not ok:
        FAILS.append(f"{name}: rc={rc}, want {'FAIL' if want_fail else 'PASS'}"
                     + (f" mentioning {needle!r}" if needle else "") + f"\n{out[-600:]}")


def gates_reopened(version: int) -> tuple[dict, dict]:
    spec = copy.deepcopy(REAL_SPEC)
    spec["version"] = version
    spec["known_gaps"] = [{"capability": "gates-verify", "surface": "dashboard", "why": "x"},
                          {"capability": "gates-ratify", "surface": "dashboard", "why": "x"}]
    calls = {s: set(c) for s, c in REAL_CALLS.items()}
    calls["dashboard"] -= GATES
    return spec, calls


def main() -> int:
    rc, out = run(REAL_SPEC, REAL_CALLS)
    expect("the real spec passes", rc, False, out)

    # GPT's reproduction: closed surface removed AND its old exception restored, version unchanged.
    spec, calls = gates_reopened(REAL_SPEC["version"])
    rc, out = run(spec, calls)
    expect("a closed gap reopened at the current version fails", rc, True, out, "only shrinks")

    # ...and rolling `version` back to the one whose ceiling still held it.
    spec, calls = gates_reopened(1)
    rc, out = run(spec, calls)
    expect("rolling version back to reuse an older ceiling fails", rc, True, out, "is the latest")

    # A later version that GROWS the set without a named migration.
    b = dict(REAL_BASELINE)
    b[max(b) + 1] = frozenset({("gates-verify", "dashboard")})
    spec, calls = gates_reopened(max(b))
    spec["known_gaps"] = spec["known_gaps"][:1]
    rc, out = run(spec, calls, b)
    expect("a version that adds gaps without GAP_GROWTH_MIGRATIONS fails", rc, True, out, "without a named")

    # A closure not recorded: the baseline still holds a gap the spec no longer lists.
    b = dict(REAL_BASELINE)
    b[max(b)] = frozenset({("gates-verify", "dashboard")})
    rc, out = run(REAL_SPEC, REAL_CALLS, b)
    expect("slack in the current baseline fails", rc, True, out, "record the closure")

    for f in FAILS:
        print("FAIL", f)
    print(f"operator surfaces ratchet: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
