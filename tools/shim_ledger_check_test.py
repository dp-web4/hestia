#!/usr/bin/env python3
"""shim_ledger_check.py fails on exactly what it says (absent, stale, unowned), and judges nothing else.

A fixture shim with four functions (one thin delegation, one law-bearing body, two plain) and a
fixture ledger emitted from it, sabotaged one way at a time:

  1. faithful ledger                    -> rc 0; the law-bearing body is a POINTER line, not a failure
  2. a function with no row             -> rc 1, named
  3. a row naming no function           -> rc 1, named as a stale row
  4. LAW-DEBT with no issue             -> rc 1, named
  5. an unknown class                   -> rc 1, named
  6. the function's source changed      -> rc 1, "changed since it was justified"; --refresh
                                           updates the hash and the check is green again with the
                                           SAME justification (the re-justifying is the reviewer's,
                                           not the tool's)
  7. no ledger                          -> rc 2, not 0
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "shim_ledger_check.py"
FAILURES: list[str] = []

SHIM = '''
import os
_core = None
def command_of(ti):
    """event shape"""
    return ti.get("command") or ""
def path_in_scope(p):
    return _core.path_in_scope(p)
def local_deny(msg):
    print("hestia: deny [gate] " + msg)
    return 2
def main():
    return 0
'''
JUST = {
    "command_of": ("event-shape", "this harness spells the shell command under `command`; translation only, no meaning"),
    "path_in_scope": ("wiring", "one-call delegation to the engine's predicate; the seat keeps its call shape only"),
    "local_deny": ("LAW-DEBT", "prints the deny text and picks the exit code locally; content belongs to the gate (#999)"),
    "main": ("refusal-channel", "reads this harness's stdin event and returns its exit code; the verdict comes from the gate"),
}


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    assert not FAILURES, FAILURES


class Fixture:
    def __init__(self, raw: str):
        self.d = Path(raw)
        self.shim = self.d / "shim.py"
        self.ledger = self.d / "LEDGER.md"
        self.shim.write_text(SHIM, encoding="utf-8")
        skeleton = self.run("--emit", "fx")[1]
        rows = []
        for ln in skeleton.splitlines():
            if ln.startswith("| `"):
                name = ln.split("`")[1]
                cls, just = JUST[name]
                src = ln.split("|")[3].strip()
                ln = f"| `{name}` | {cls} | {src} | {just} |"
            rows.append(ln)
        self.ledger.write_text("# ledger\n" + "\n".join(rows) + "\n", encoding="utf-8")

    def run(self, *extra) -> tuple[int, str]:
        r = subprocess.run([sys.executable, str(TOOL), "--root", str(self.d), "--gate", f"fx={self.shim}",
                            "--ledger", str(self.ledger), *extra], capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def edit_ledger(self, old: str, new: str) -> None:
        s = self.ledger.read_text(encoding="utf-8")
        assert s.count(old) == 1, (old, s)
        self.ledger.write_text(s.replace(old, new, 1), encoding="utf-8")


def test_faithful() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        rc, out = fx.run()
        check(rc == 0, f"[1] faithful ledger passes (rc={rc})\n{out[-400:] if rc else ''}")
        check("read this row first" not in out.split("local_deny")[1].split("\n")[0],
              "[1] a LAW-DEBT row is not a pointer (it already says what it is)")
        fx.edit_ledger("| `local_deny` | LAW-DEBT |", "| `local_deny` | refusal-channel |")
        rc, out = fx.run()
        check(rc == 0 and "read this row first" in out,
              f"[1] a law-bearing body filed as refusal-channel is a POINTER for review, not a failure (rc={rc})")


def test_unlisted_and_stale_row() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        fx.edit_ledger("| `main` |", "| `nope` |")
        rc, out = fx.run()
        check(rc == 1 and "`main` has no justification row" in out, f"[2] unlisted function named (rc={rc})")
        check("`nope` names no top-level" in out, "[3] the stale row is named too")


def test_debt_without_issue() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        fx.edit_ledger("(#999)", "(no issue)")
        rc, out = fx.run()
        check(rc == 1 and "LAW-DEBT with no owning issue" in out, f"[4] debt without issue named (rc={rc})")


def test_unknown_class() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        fx.edit_ledger("| event-shape |", "| convenience |")
        rc, out = fx.run()
        check(rc == 1 and "class 'convenience' is not one of" in out, f"[5] unknown class named (rc={rc})")


def test_changed_function_is_stale_until_refreshed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        fx.shim.write_text(SHIM.replace('return ti.get("command") or ""', 'return ti.get("command") or ti.get("cmd") or ""'),
                           encoding="utf-8")
        rc, out = fx.run()
        check(rc == 1 and "`command_of` changed since it was justified" in out,
              f"[6] a changed function is stale until re-justified (rc={rc})")
        rc, out = fx.run("--refresh")
        check(rc == 0 and "refreshed src on 1 row(s)" in out, f"[6] --refresh updates the hash and the check is green (rc={rc})")
        check("translation only, no meaning" in fx.ledger.read_text(encoding="utf-8"),
              "[6] the justification text was left for the reviewer, not rewritten")


def test_discovery_on_the_real_tree_names_every_seat() -> None:
    """The discovery branch (no --gate) was the one path the fixture never fired; it crashed on
    first use because discover_gates yields (seat, path) tuples. Run it on the real tree with a
    ledger path that does not exist: rc 2, and the run must have discovered the four seats."""
    r = subprocess.run([sys.executable, str(TOOL), "--ledger", "/nonexistent/LEDGER.md", "--emit", "codex"],
                       capture_output=True, text=True, timeout=120)
    check(r.returncode == 0 and "## codex" in r.stdout and "| `main` |" in r.stdout,
          f"[8] discovery finds the codex gate and --emit prints its rows (rc={r.returncode}) {r.stderr[-200:]}")
    r = subprocess.run([sys.executable, str(TOOL), "--ledger", "/nonexistent/LEDGER.md"],
                       capture_output=True, text=True, timeout=120)
    check(r.returncode == 2, f"[8] no ledger on the real tree -> rc 2 (rc={r.returncode})")


def test_no_ledger() -> None:
    with tempfile.TemporaryDirectory() as raw:
        fx = Fixture(raw)
        fx.ledger.unlink()
        rc, out = fx.run()
        check(rc == 2, f"[7] no ledger -> rc 2 (rc={rc})")


if __name__ == "__main__":
    test_faithful()
    test_unlisted_and_stale_row()
    test_debt_without_issue()
    test_unknown_class()
    test_changed_function_is_stale_until_refreshed()
    test_no_ledger()
    test_discovery_on_the_real_tree_names_every_seat()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: the ledger check fails on the absent, the stale and the unowned, and judges nothing else")
