#!/usr/bin/env python3
"""Command scope: an unquoted glob after `cd D &&` is judged where it expands (#1317, glob variant).

McNugget 2026-11-13 and again 2026-11-16 (v0.3.0-118-g480279d3): `cd ~/repos/hestia && ls tools/*x*`
was refused as `~/ai-workspace/tools/*`, the event cwd, and opened a peer-ruled scope request for a
directory that does not exist. The same act with a plain relative path (`cat tools/x.py`) was allowed.

The cause was one line in pass 3's relative vote. An interpretation is judged only if it could name
something: a plain path when its PARENT exists. A glob's probe is `<dir>/*`, and stripping the `*`
and taking the dirname climbed one level too far, so `<cwd>/tools/*` was judged because `<cwd>`
exists although `<cwd>/tools` does not. A glob expands only inside its own directory; where that
directory does not exist the shell passes the word through literally and nothing is reached, which
is the same reasoning the plain-path rule already uses.

Run:  ./tools/gate_glob_after_cd_test.py
      HESTIA_SCOPE_BATTERY_CORE=<path> ./tools/gate_glob_after_cd_test.py   (a staged core)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
_staged = os.getenv("HESTIA_SCOPE_BATTERY_CORE")
if _staged:
    _spec = importlib.util.spec_from_file_location("hestia_gate_core", _staged)
    G = importlib.util.module_from_spec(_spec)
    sys.modules["hestia_gate_core"] = G
    _spec.loader.exec_module(G)
else:
    import hestia_gate_core as G  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAIL.append(name)


def main() -> int:
    ws = os.path.realpath(tempfile.mkdtemp(prefix="ws-"))
    launch = os.path.realpath(tempfile.mkdtemp(prefix="launch-"))   # the event cwd: outside ws, ungranted
    out = os.path.realpath(tempfile.mkdtemp(prefix="outside-"))     # an outside directory that exists
    os.makedirs(f"{ws}/granted/tools/sub")
    open(f"{ws}/granted/tools/a_store.py", "w").close()
    os.makedirs(f"{launch}/secret")
    open(f"{launch}/secret/k", "w").close()
    open(f"{out}/f", "w").close()
    # A `path:` grant, as every live seat holds them (McNugget's are all `path:<abs>/**`). A bare
    # segment grant ("granted") would put the repo root among the vote's bases, and that
    # interpretation would vote the glob in scope and hide the defect.
    scopes = (f"path:{ws}/granted/**",)
    # Temp-root admission off (as grant_modes_gate_test._Workspace does): every directory here is a
    # mkdtemp, and path_in_scope admits anything under a temp root before it consults grants, which
    # would make the event-cwd rows pass for the wrong reason.
    G._under_temp_root = lambda *a, **k: False

    def reach(c):
        return G.command_scope_reach(c, scopes, ws, cwd=launch)

    # ---- the #1317 act: the glob expands under the cd target, which is granted ----
    ok, off, _ = reach(f"cd {ws}/granted && ls tools/*store*")
    check("cd <granted> && ls tools/*x*: allowed (the #1317 act)", ok, off)
    ok, off, _ = reach(f"cd {ws}/granted && ls tools/*")
    check("a bare dir/* under the cd target: allowed", ok, off)
    ok, off, _ = reach(f"cd {ws}/granted && ls tools/sub/*.py")
    check("a deeper glob under the cd target: allowed", ok, off)
    ok, off, _ = reach(f"cd {ws}/granted && git status && cd {ws}/granted/tools && ls sub/*")
    check("a later && cd governs the glob too (the 11-13 shape)", ok, off)

    # ---- controls that already passed ----
    ok, off, _ = reach(f"cd {ws}/granted && cat tools/a_store.py")
    check("control: a plain relative path under the cd target", ok, off)
    ok, off, _ = reach(f"ls {ws}/granted/tools/*")
    check("control: an absolute glob inside the grant", ok, off)

    # ---- must still refuse ----
    ok, off, _ = reach(f"cd {ws}/granted && ls ../../{os.path.basename(out)}/*")
    check("must deny: a glob that climbs out of the cd target to an existing outside dir", not ok, off)
    ok, off, _ = reach("ls secret/*")
    check("must deny: a glob whose directory EXISTS at the event cwd, with no cd", not ok, off)
    ok, off, _ = reach(f"ls {out}/*")
    check("must deny: an absolute glob outside the grant", not ok, off)
    ok, off, _ = reach(f"cd {ws}/granted && cat ../../{os.path.basename(out)}/f")
    check("must deny: a plain relative escape from the cd target", not ok, off)

    # ---- under a bare segment grant the repo root also votes; a glob it does not hold no longer
    # votes in scope for a directory that exists only at the event cwd (a tightening) ----
    seg = G.command_scope_reach("ls secret/*", ("granted",), ws, cwd=launch)
    check("must deny (segment grant): a glob whose dir exists only at the event cwd", not seg[0], seg[1])
    seg = G.command_scope_reach(f"cd {ws}/granted && ls tools/*", ("granted",), ws, cwd=launch)
    check("segment grant: the cd-then-glob act is still allowed", seg[0], seg[1])

    print()
    print("PASS: 0 failing" if not FAIL else f"FAIL: {len(FAIL)} failing")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
