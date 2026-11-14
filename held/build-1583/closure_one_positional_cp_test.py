#!/usr/bin/env python3
"""Closure: a ONE-positional cp/install/rsync/ln whose word can expand to source + destination is not a
no-write (#1583).

The `cp` / `install` / `rsync` / `ln` destination is the last positional, taken only when there are two or more.
With one positional the line read as no-write, but one word can become several at run time: a glob
(`G/x*`), a brace (`G/x{.py,_test.py}`), an unquoted `$X` (bash), `"$@"` after `set --`, `"${arr[@]}"`,
or a command substitution. Its last expansion is the destination, and that can be a closure file.

Now a single positional is taken as one literal word only when it is made entirely of plain path
characters. Anything else is out of grammar, which is a write iff closure vocabulary appears in the
line. A plain word, `cp --help`, `cp -t DIR SRC` and two-positional lines are unchanged.

Run:  ./tools/closure_one_positional_cp_test.py
      HESTIA_CLOSURE_CORE=<path> ./tools/closure_one_positional_cp_test.py   (a staged classifier)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
_staged = os.getenv("HESTIA_CLOSURE_CORE")
if _staged:
    _spec = importlib.util.spec_from_file_location("hestia_governance_closure", _staged)
    C = importlib.util.module_from_spec(_spec)
    sys.modules["hestia_governance_closure"] = C
    _spec.loader.exec_module(C)
else:
    import hestia_governance_closure as C  # noqa: E402

FAIL = []
REPO = str(ROOT)
G = f"{REPO}/plugins/_shared"


def verdict(cmd):
    return C.classify("Bash", {"command": cmd}, cwd=REPO).classification


def row(name, cmd, want):
    got = verdict(cmd)
    # "not-write": `none` or `read` (a closure path named as a source is a witnessed read).
    ok = got == "write" if want == "write" else got != "write"
    print(("  ok    " if ok else "  FAIL  ") + f"{name}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        FAIL.append(name)


def main() -> int:
    # ---- one word that expands to src + dest, dest in the closure: must be write ----
    row("cp brace", f"cp {G}/x{{.py,_test.py}}", "write")
    row("cp glob *", f"cp {G}/hestia_gate_core*", "write")
    row("cp glob ?", f"cp {G}/hestia_gate_cor?.py", "write")
    row("cp glob [..]", f"cp {G}/hestia_gate_cor[ae].py", "write")
    row("install glob", f"install {G}/hestia_gate_core*", "write")
    row("rsync glob", f"rsync {G}/hestia_gate_core*", "write")
    row("cp unquoted $X", f'X="/tmp/a {G}/y"; cp $X', "write")
    row("install unquoted $X", f'X="/tmp/a {G}/y"; install $X', "write")
    row("rsync unquoted $X", f'X="/tmp/a {G}/y"; rsync $X', "write")
    row("cp \"${arr[@]}\"", f'arr=(/tmp/a {G}/y); cp "${{arr[@]}}"', "write")
    row("set -- then cp \"$@\"", f'set -- /tmp/a {G}/y; cp "$@"', "write")
    row("cp $( )", f"cp $(printf '/tmp/a {G}/y')", "write")
    row("cp backtick", f"cp `printf '/tmp/a {G}/y'`", "write")
    row("cp -p with a glob", f"cp -p {G}/hestia_gate_core*", "write")
    row("ln -f glob", f"ln -f {G}/hestia_gate_core*", "write")
    row("ln -sf brace", f"ln -sf {G}/x{{.py,_test.py}}", "write")
    row("ln -f unquoted $X", f'X="/tmp/a {G}/y"; ln -f $X', "write")

    # ---- unchanged ----
    row("control: set -e; cp two plain operands outside", "set -e; cp /tmp/a /tmp/b", "not-write")
    row("control: cp --help", "cp --help", "not-write")
    row("control: one plain closure word", f"cp {G}/hestia_gate_core.py", "not-write")
    row("control: closure file copied out", f"cp {G}/hestia_gate_core.py /tmp/x.py", "not-write")
    row("control: -t outside, closure source", f"cp -t /tmp/d {G}/hestia_gate_core.py", "not-write")
    row("control: one-word glob outside the closure", "cp /tmp/build/x*", "not-write")
    row("control: two operands into the closure", f"cp /tmp/a {G}/y", "write")
    row("control: mv $X", f'X="/tmp/a {G}/y"; mv $X', "write")
    row("control: ln -s two plain operands outside", "ln -s /tmp/a /tmp/b", "not-write")
    row("control: ln -s one plain closure word", f"ln -s {G}/hestia_gate_core.py", "not-write")

    print(f"\n{'PASS' if not FAIL else 'FAIL'}: {len(FAIL)} failing")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
