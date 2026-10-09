#!/usr/bin/env python3
"""Command scope: declared toolchain roots, and grep-family PATTERN operands (SAGE #368).

Measured 2026-10-05 on 2,187 legion-being calls replayed through the one gate with the
being under its SEAT's workspace (`/home/dp`, dp's ruling: a being judged by anything else is
judged by a different law than its seat): SAGE #368, which hands the gate the composed command,
denied 37/37 `check` and 84/84 `game` ("'miniforge3' is not granted": the sandbox's
`--ro-bind /home/dp/miniforge3` and the interpreter itself) and one `search` ("'[^' is not
granted": a fragment of the being's own regex). With HESTIA_TOOL_ROOTS=/home/dp/miniforge3 and
pattern operands masked, the same replay gives 0 new denies.

Run:  ./tools/gate_tool_roots_and_patterns_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_gate_core as G  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAIL.append(name)


def main() -> int:
    ws = tempfile.mkdtemp(prefix="ws-")
    for d in ("granted/sub", "tools/conda/bin", "other"):
        os.makedirs(f"{ws}/{d}")
    scopes = ("granted",)

    def reach(c):
        return G.command_scope_reach(c, scopes, ws, cwd=f"{ws}/granted")

    os.environ.pop(G.TOOL_ROOTS_ENV, None)
    ok, off, _ = reach(f"bwrap --ro-bind {ws}/tools/conda {ws}/tools/conda {ws}/tools/conda/bin/python3 {ws}/granted/t.py")
    check("without a declared tool root, the interpreter is an ungranted reach (unchanged)", not ok and off == "tools", off)

    os.environ[G.TOOL_ROOTS_ENV] = f"{ws}/tools/conda"
    ok, off, _ = reach(f"bwrap --ro-bind {ws}/tools/conda {ws}/tools/conda --setenv PATH {ws}/tools/conda/bin:/usr/bin "
                       f"{ws}/tools/conda/bin/python3 -m pytest {ws}/granted/sub")
    check("a declared tool root is not governed territory (check-shaped line)", ok, off)
    ok, off, _ = reach(f"{ws}/tools/conda/bin/python3 {ws}/other/stepper.py --instance {ws}/granted")
    check("operands outside the tool root are still judged (game-shaped line)", not ok and off == "other", off)
    ok, off, _ = reach(f"cat {ws}/tools/condaX/secret")
    check("a sibling of a tool root is not under it (boundary, not prefix)", not ok, off)
    for bad in ("/", ws, os.path.dirname(ws)):
        os.environ[G.TOOL_ROOTS_ENV] = bad
        ok, off, _ = reach(f"cat {ws}/other/x")
        check(f"a tool root that is /, the workspace or its ancestor is ignored ({bad})", not ok and off == "other", off)
    os.environ[G.TOOL_ROOTS_ENV] = "relative/path"
    ok, _, _ = reach(f"cat {ws}/other/x")
    check("a relative tool root is ignored", not ok)

    os.environ[G.TOOL_ROOTS_ENV] = f"{ws}/tools/conda"
    secret = tempfile.mkdtemp(prefix="s-")
    os.makedirs(f"{secret}/.ssh")
    open(f"{secret}/.ssh/id_x", "w").close()
    os.symlink(f"{secret}/.ssh/id_x", f"{ws}/tools/conda/link")
    ok, off, _ = reach(f"cat {ws}/tools/conda/link")
    check("egress is judged before the tool root: a link to a forbidden target denies", not ok and ".ssh" in (off or ""), off)
    os.environ.pop(G.TOOL_ROOTS_ENV, None)

    ok, off, _ = reach(f"git --no-pager -C {ws}/granted grep -n -I -E --max-count=15 -e 'ft09\\.py.*bytes|{ws}[^ ]*ft09\\.py' -- {ws}/granted/sub")
    check("a git grep -e pattern is text, not a path (search-shaped line)", ok, off)
    ok, off, _ = reach(f"git --no-pager -C {ws}/granted grep -n -e 'x' -- {ws}/other")
    check("git grep's pathspec after -- is still judged", not ok and off == "other", off)
    ok, off, _ = reach(f"grep -rn '{ws}/other/never-opened' {ws}/granted/sub")
    check("grep's positional pattern is text", ok, off)
    ok, off, _ = reach(f"grep -rn needle {ws}/other")
    check("grep's file operand is still judged", not ok and off == "other", off)
    ok, off, _ = reach(f"grep -f {ws}/other/patterns {ws}/granted/sub")
    check("grep -f's operand IS a file and is judged", not ok and off == "other", off)
    ok, off, _ = reach(f"rg --regexp={ws}/other/x {ws}/granted")
    check("rg --regexp=... is text", ok, off)
    ok, off, _ = reach(f"cat {ws}/other/x | grep -e '{ws}/other' ")
    check("masking is per simple command: cat's operand is still judged", not ok and off == "other", off)
    ok, off, _ = reach(f"grep -e 'unbalanced {ws}/other/x")
    check("an unsplittable line is judged as before (no masking)", not ok and off == "other", off)

    print("\nall checks pass" if not FAIL else f"\n{len(FAIL)} FAILED: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
