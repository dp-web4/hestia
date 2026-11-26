#!/usr/bin/env python3
"""Guard: no test fixture may write git config unless it first drops inherited GIT_*.

Why (hestia #1738): tools/build_lock_manifest_test.py ran `git config user.*` with only
cwd= pointing at its tempdir fixture. With GIT_DIR exported, as inside a git hook, git
honours the variable over cwd=, so the identity landed in the CALLER's repository config.
The shared hestia checkout then authored every commit from every worktree as
`probe <probe@example.invalid>` (59 commits from 2026-11-24 17:31 PST). Thirteen more
fixtures had the same shape; each now carries a `fixture-git-isolation` block.

Two checks:
  static      every tracked .py/.sh file that runs `git config user.*` must carry the
              fixture-git-isolation marker. Includes a synthetic offender, so a matcher
              that stopped matching would fail here rather than pass silently.
  behavioural two fixtures (one Python, one bash) run with GIT_DIR exported at a scratch
              repository; the scratch repository's config must come back unchanged.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "fixture-git-isolation"

# Built by concatenation so this file does not match its own patterns.
_CFG = "con" + "fig"
PY_WRITE = re.compile(r"""["']""" + _CFG + r"""["']\s*,\s*["']user\.""")
SH_WRITE = re.compile(r"""(^|[;&|]\s*)git\s+""" + _CFG + r"""\s+(--local\s+)?user\.""", re.M)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"ok  {name}")
    else:
        FAILURES.append(name)
        print(f"FAIL {name}: {detail}")


def offends(path: str, text: str) -> bool:
    pattern = PY_WRITE if path.endswith(".py") else SH_WRITE
    return bool(pattern.search(text)) and MARKER not in text


def static_check() -> None:
    synthetic_py = 'subprocess.run(["git", "' + _CFG + '", "user.name", "x"], cwd=d)\n'
    synthetic_sh = "cd \"$WORK\"\ngit " + _CFG + " user.email a@b; git " + _CFG + " user.name a\n"
    check("matcher flags a synthetic python offender", offends("x_test.py", synthetic_py))
    check("matcher flags a synthetic bash offender", offends("x_test.sh", synthetic_sh))
    check("matcher accepts an isolated fixture",
          not offends("x_test.py", "# " + MARKER + "\n" + synthetic_py))

    listed = subprocess.run(["git", "ls-files", "-z", "--", "*.py", "*.sh"], cwd=ROOT,
                            check=True, capture_output=True).stdout.decode().split("\0")
    offenders = []
    writers = 0
    for rel in filter(None, listed):
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        pattern = PY_WRITE if rel.endswith(".py") else SH_WRITE
        if pattern.search(text):
            writers += 1
            if MARKER not in text:
                offenders.append(rel)
    check("population is non-empty (the scan sees fixtures at all)", writers > 0, "0 writers")
    check("every git-config-writing fixture drops inherited GIT_*", not offenders,
          "add a fixture-git-isolation block to: " + ", ".join(offenders))


def scratch_config(git_dir: Path) -> str:
    return (git_dir / "config").read_text(encoding="utf-8")


def behavioural_check() -> None:
    fixtures = [
        [sys.executable, str(ROOT / "tools" / "merge_order_census_test.py")],
        ["bash", str(ROOT / "tools" / "stranded_v2_control_test.sh")],
    ]
    with tempfile.TemporaryDirectory(prefix="fixture-git-isolation-") as raw:
        caller = Path(raw) / "caller"
        caller.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "init", "-q"], cwd=caller, check=True, env=env)
        git_dir = caller / ".git"
        before = scratch_config(git_dir)
        for argv in fixtures:
            name = Path(argv[-1]).name
            run_env = dict(env, GIT_DIR=str(git_dir), GIT_WORK_TREE=str(caller))
            result = subprocess.run(argv, cwd=raw, env=run_env, capture_output=True, text=True)
            check(f"{name} passes with GIT_DIR exported at a foreign repo",
                  result.returncode == 0, (result.stdout + result.stderr)[-600:])
            check(f"{name} leaves the foreign repo's config untouched",
                  scratch_config(git_dir) == before, "config changed:\n" + scratch_config(git_dir))


def main() -> int:
    static_check()
    behavioural_check()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall fixture-git-isolation checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
