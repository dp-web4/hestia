#!/usr/bin/env python3
"""Synthetic and live-tree pins for #1103's M1/M2 implementation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("shim_metrics", ROOT / "tools" / "shim_metrics.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
FAILURES: list[str] = []


def check(name: str, condition: bool, detail="") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


TEMPLATE = '''\
def common():
    """certified docs"""
    x = 1
    return x

def adapter():
    pass

def main():
    return 0
'''
SEAT_A = '''\
def common():
    """a comment change cannot move either metric"""
    x = 1  # nor can this one
    return x

def adapter():
    x = 1
    return x

def main():
    return 0

def local():
    return 2
'''
SEAT_B = '''\
def common():
    x = 1
    return x

def adapter():
    pass

def main():
    return 1
'''


def test_code_lines_strips_only_prose():
    src = '''"""module docs"""
def f():
    """function docs"""
    value = """payload
# payload, not a comment
"""
    return value  # discarded comment

def one(): """inline docs"""; return 1  # discarded too
'''
    lines = M.code_lines(src)
    joined = "\n".join(lines.values())
    check("module and function docstrings are gone", "module docs" not in joined
          and "function docs" not in joined, joined)
    check("comment text is gone", "discarded comment" not in joined
          and "discarded too" not in joined, joined)
    check("a multiline string remains code", "# payload, not a comment" in joined, joined)
    check("an inline docstring does not erase its function", "def one():" in joined
          and "return 1" in joined, joined)


def test_metric_math_and_fleet_intersection():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        template, a, b = root / "template.py", root / "a.py", root / "b.py"
        template.write_text(TEMPLATE)
        a.write_text(SEAT_A)
        b.write_text(SEAT_B)
        report = M.measure(template, {"a": a, "b": b})
    check("certified denominator is code only", report["certified_sloc"] == 7,
          report["certified_sloc"])
    check("seat A M1", report["seats"]["a"]["m1"] == 6 / 7, report["seats"]["a"])
    check("seat A counts the whole divergent body and local function",
          report["seats"]["a"]["exception_sloc"] == 5 and report["seats"]["a"]["m2"] == 5 / 7,
          report["seats"]["a"])
    check("seat B M1 and M2", report["seats"]["b"]["m1"] == 6 / 7
          and report["seats"]["b"]["m2"] == 2 / 7, report["seats"]["b"])
    check("fleet M1 is the certified intersection, not a sum or average",
          report["fleet"] == {"m1": 5 / 7, "identical_sloc": 5}, report["fleet"])
    check("comments do not hide the adapter exception",
          report["seats"]["a"]["exception_functions"] == ["adapter", "local"],
          report["seats"]["a"]["exception_functions"])
    failures = M.bound_failures(report, 0.9, {"a": 0.8, "b": 0.7}, {"a": 0.5, "b": 0.25})
    check("ratchets move M1 down and M2 up", len(failures) == 3, failures)
    check("unknown seats are not silently compliant",
          M.bound_failures(report, None, {"missing": 0.1}, {"missing": 0.1}) != [])


def test_home_requires_current_verified_bytes():
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        status = home / "status" / "gate-integrity.json"
        status.parent.mkdir()
        status.write_text(json.dumps({"status": "VERIFIED", "gates": []}))
        check("VERIFIED home is admitted", M.verified_home(home) is None)
        status.write_text(json.dumps({"status": "PENDING", "reason": "not judged", "gates": []}))
        check("PENDING home is not certified", "PENDING" in M.verified_home(home))
        status.write_text(json.dumps({"status": "MODIFIED", "gates": []}))
        check("MODIFIED home is refused", "MODIFIED" in M.verified_home(home))


def test_real_tree_is_measurable():
    report = M.measure(M.TEMPLATE, M.seat_map(False))
    check("the template carries code", report["certified_sloc"] > 0, report["certified_sloc"])
    check("all four real seats are measured", set(report["seats"]) == set(M.CERT.REPO_SHIMS),
          sorted(report["seats"]))
    check("fleet fidelity never exceeds the certified denominator",
          0 <= report["fleet"]["m1"] <= 1
          and report["fleet"]["identical_sloc"] <= report["certified_sloc"], report["fleet"])
    check("M1 and M2 are finite ratios", all(0 <= row["m1"] <= 1 and row["m2"] >= 0
          for row in report["seats"].values()), report["seats"])
    print(json.dumps(report, indent=2, sort_keys=True))


def teardown_module(module):
    assert not FAILURES, f"{len(FAILURES)} shim-metric check(s) failed: {FAILURES}"


if __name__ == "__main__":
    test_code_lines_strips_only_prose()
    test_metric_math_and_fleet_intersection()
    test_home_requires_current_verified_bytes()
    test_real_tree_is_measurable()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        raise SystemExit(1)
    print("ok: M1/M2 ignore prose, measure divergence, and require verified deployed bytes")
