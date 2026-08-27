#!/usr/bin/env python3
"""Run the checks that keep turning branches red, BEFORE the push instead of after.

WHY. Five independent PRs went red in one week on the same two guards:

    tools/shebang_exec_bit_test.py   -- #671 (x3), #673, #681
    tools/public_boundary_test.py    -- #665, #671, #678

Both guards are correct. The shebang one even prints the exact repair command. Nothing was
wrong with the checks; the loop was wrong: write a tool, push, read the repair off a CI job
log, push again. The author never sees the guard until it has already cost a round trip and a
reviewer's attention.

The reason nobody ran them locally is measurable rather than cultural: `shebang_exec_bit_test`
took **37 seconds** on this fleet's WSL checkout, because it spawned one `git show` per
tracked file. A check that costs 37s does not get run before a push, so it can only ever
report mistakes rather than prevent them. Batching the blob reads took it to **0.93s** (same
answer, verified against the old implementation on a clean tree AND on a sabotaged one), and
that is what makes this file worth existing.

    fast mode (default)   ~6s   the two guards above
    --full                ~3m   everything `plugin tests (python)` runs in CI

WHAT THIS IS NOT. It is not the CI gate and must never be mistaken for it. Fast mode runs 2
of 72 discovered tests. It is a high-yield filter for the two mistakes that actually recur,
and it says so on every run -- a partial suite that presents as a full one is worse than no
suite, because green then means "the subset I happened to pick passed".

Discovery comes from `tools/ci_discovery.py`, the same module CI uses, so --full cannot drift
from the job it stands in for. If a new check starts recurring, add it to FAST below rather
than building a second discovery.

Install as a pre-push hook (optional, and it does not gate the push -- see --advisory):

    printf '#!/bin/sh\\nexec python3 tools/preflight.py\\n' > .git/hooks/pre-push
    git update-index --chmod=+x .git/hooks/pre-push   # chmod alone is dropped here

Exit status:
  0  everything run passed
  1  something failed -- the failing test's own output says what to repair
  2  could not determine (discovery empty, or a test could not be executed)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# The two that recur. Deliberately a SHORT literal list and not a heuristic: the value here
# is that it is fast and predictable, and a heuristic that silently widens would reintroduce
# the cost that stopped anyone running it.
FAST = (
    "tools/shebang_exec_bit_test.py",
    "tools/public_boundary_test.py",
)


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def discovered(root: Path) -> list[str]:
    """Exactly what CI's `plugin tests (python)` job runs, via the same discovery module."""
    out = subprocess.run([sys.executable, "tools/ci_discovery.py", "bare"],
                         cwd=root, capture_output=True, text=True)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def run_one(root: Path, rel: str) -> tuple[bool, str]:
    started = time.monotonic()
    proc = subprocess.run([sys.executable, rel], cwd=root,
                          capture_output=True, text=True)
    took = time.monotonic() - started
    ok = proc.returncode == 0
    # On failure show the test's OWN words. These guards print their repair command; a
    # wrapper that summarises them into "FAILED" throws away the only actionable part.
    detail = "" if ok else (proc.stdout + proc.stderr).strip()
    return ok, f"{'ok  ' if ok else 'FAIL'} {took:5.1f}s  {rel}" + (f"\n{detail}" if detail else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--full", action="store_true",
                    help="run every test CI's plugin-tests job runs (~3m), not just the two")
    ap.add_argument("--advisory", action="store_true",
                    help="always exit 0; print findings without blocking a push")
    args = ap.parse_args()

    root = repo_root()
    all_tests = discovered(root)
    if not all_tests:
        print("cannot determine: ci_discovery found no tests — the layout moved",
              file=sys.stderr)
        return 2

    if args.full:
        tests, mode = all_tests, "FULL"
    else:
        tests = [t for t in FAST if t in all_tests]
        mode = "fast"
        missing = [t for t in FAST if t not in all_tests]
        if missing:
            # A named fast check that discovery no longer finds is a rename or a deletion,
            # and silently running one fewer test is how a suite hollows out.
            print(f"cannot determine: {', '.join(missing)} named in FAST but not discovered",
                  file=sys.stderr)
            return 2

    print(f"preflight [{mode}]: {len(tests)} of {len(all_tests)} discovered tests")
    failed = []
    for t in tests:
        ok, line = run_one(root, t)
        print(line)
        if not ok:
            failed.append(t)

    # NAME WHAT WAS SKIPPED, every time. Silence about the other 70 is what would turn this
    # into "green means CI will pass", which it does not mean.
    if not args.full:
        print(f"\nNOT RUN: {len(all_tests) - len(tests)} other tests CI will run. "
              f"This is a filter for the two failures that recur, not the CI gate. "
              f"Use --full before a push you care about.")

    if failed:
        print(f"\n{len(failed)} failed: {' '.join(failed)}", file=sys.stderr)
        if args.advisory:
            print("(advisory mode: not blocking)", file=sys.stderr)
            return 0
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
