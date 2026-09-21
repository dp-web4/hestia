#!/usr/bin/env python3
"""gate_verdict.py: a verdict applies only to the bytes it judged.

The arms that matter are the ones where a stale or absent verdict could read as a pass:
a gate rewritten after the daemon looked (PENDING, not the old VERIFIED), no status file at
all (NO_STATUS, not success), and a pass whose chain rows did not land (said so).
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_verdict as gv  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        FAILS.append(f"{name}: {detail}")


def stage(root: Path, status: str, body: bytes = b"print('gate')", **extra):
    gate = root / "gate.py"
    gate.write_bytes(body)
    doc = {"status": status, "checked_at": 100, "witness_failures": 0,
           "gates": [{"gate": str(gate), "status": status.lower(),
                      "found_sha256": hashlib.sha256(body).hexdigest(),
                      "open_finding_chain_hash": None if status == "VERIFIED" else "abc123"}]}
    doc.update(extra)
    (root / "status").mkdir(exist_ok=True)
    (root / gv.STATUS_FILE).write_text(json.dumps(doc))
    return gate


def test_a_verdict_about_these_bytes_applies():
    with tempfile.TemporaryDirectory() as d:
        stage(Path(d), "VERIFIED")
        r = gv.assess(Path(d))
        check("verified_bytes_verified", r["verdict"] == "VERIFIED", r)


def test_a_gate_rewritten_after_the_pass_is_pending_not_the_old_verdict():
    with tempfile.TemporaryDirectory() as d:
        gate = stage(Path(d), "VERIFIED")
        gate.write_bytes(b"import sys; sys.exit(0)")
        r = gv.assess(Path(d))
        check("rewritten_is_pending", r["verdict"] == "PENDING", r)
        check("rewritten_names_the_gate", r["stale"][0]["gate"] == str(gate), r)


def test_no_status_file_is_not_success():
    with tempfile.TemporaryDirectory() as d:
        r = gv.assess(Path(d))
        check("absent_is_no_status", r["verdict"] == "NO_STATUS", r)
        rc = subprocess.run([sys.executable, str(HERE / "gate_verdict.py"), "--home", d],
                            capture_output=True, text=True).returncode
        check("absent_exits_nonzero", rc == 5, rc)


def test_findings_exit_nonzero_and_name_the_chain_row():
    with tempfile.TemporaryDirectory() as d:
        stage(Path(d), "MODIFIED")
        p = subprocess.run([sys.executable, str(HERE / "gate_verdict.py"), "--home", d],
                           capture_output=True, text=True)
        check("modified_exit_3", p.returncode == 3, p.returncode)
        check("modified_names_chain_row", "abc123" in p.stdout, p.stdout)


def test_a_pass_whose_rows_did_not_land_says_so():
    with tempfile.TemporaryDirectory() as d:
        stage(Path(d), "VERIFIED", witness_failures=1)
        r = gv.assess(Path(d))
        check("unwitnessed_is_flagged", "did NOT land" in r["reason"], r)


TESTS = [test_a_verdict_about_these_bytes_applies,
         test_a_gate_rewritten_after_the_pass_is_pending_not_the_old_verdict,
         test_no_status_file_is_not_success,
         test_findings_exit_nonzero_and_name_the_chain_row,
         test_a_pass_whose_rows_did_not_land_says_so]

if __name__ == "__main__":
    for t in TESTS:
        t()
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print("ok: a gate verdict applies only to the bytes it judged")
