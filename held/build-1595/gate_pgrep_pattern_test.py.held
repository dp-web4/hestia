#!/usr/bin/env python3
"""Command scope: pgrep / pkill PATTERN operands are text, not paths (#1595).

`pgrep -f PAT` matches a regex against running processes' command lines and never opens a file,
but before this a pattern spelled like an absolute path outside the grant was refused as
`mrh.command` and opened a scope request (McNugget, 2026-11-14, chain pos 55835:
`pgrep -fl '/opt/homebrew/bin/hestia'`). Finding a daemon by its full command line is the normal
way to get its PID on a seat.

pgrep / pkill now ride the same grammar the grep family uses (#1241 recut): the first positional is
the pattern, recognised inside the shell grammar (`_CMD_SPECS`), never by rewriting the text. Their
one FILE operand, `-F` / `--pidfile`, is still judged, and an unquoted glob is still a directory read.

Run:  ./tools/gate_pgrep_pattern_test.py
      HESTIA_SCOPE_BATTERY_CORE=<path> ./tools/gate_pgrep_pattern_test.py   (a staged core)
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
    ws = tempfile.mkdtemp(prefix="ws-")
    out = tempfile.mkdtemp(prefix="outside-")          # outside the workspace: no grant reaches it
    for d in ("granted", "other"):
        os.makedirs(f"{ws}/{d}")
    os.makedirs(f"{out}/bin")
    open(f"{out}/bin/daemon", "w").close()
    open(f"{out}/daemon.pid", "w").close()
    scopes = ("granted",)

    def reach(c):
        return G.command_scope_reach(c, scopes, ws, cwd=f"{ws}/granted")

    # ---- the pattern is text ----
    ok, off, _ = reach(f"pgrep -fl '{out}/bin/daemon'")
    check("pgrep -fl '<outside path>' is a pattern, not a reach (the #1595 act)", ok, off)
    ok, off, _ = reach(f"pgrep -f {out}/bin/daemon")
    check("pgrep -f <outside path> unquoted, no glob: still a pattern", ok, off)
    ok, off, _ = reach(f"pkill -f '{out}/bin/daemon serve'")
    check("pkill -f '<outside path> serve' is a pattern on scope grounds", ok, off)
    ok, off, _ = reach(f"pgrep -f '{ws}/other/x'")
    check("a pattern naming an ungranted in-workspace dir is text too", ok, off)
    ok, off, _ = reach(f"pgrep -u root -f '{out}/bin/daemon'")
    check("an option value (-u root) does not shift the pattern position", ok, off)
    ok, off, _ = reach(f"pkill -HUP -f '{out}/bin/daemon'")
    check("a signal word (-HUP) is a flag, not a clustered -U/-P value", ok, off)
    ok, off, _ = reach(f"pkill -9 -f '{out}/bin/daemon'")
    check("a numeric signal (-9) is a flag", ok, off)
    ok, off, _ = reach(f"pkill -SIGTERM -f '{out}/bin/daemon'")
    check("a SIG-prefixed signal is a flag", ok, off)
    ok, off, _ = reach(f"pgrep -fl '{out}/bin/daemon' | head -3")
    check("in a pipeline, the pattern is still text", ok, off)

    # ---- what stays judged ----
    ok, off, _ = reach(f"pgrep -F {out}/daemon.pid")
    check("must deny: pgrep -F's operand IS a file (pidfile)", not ok, off)
    ok, off, _ = reach(f"pkill --pidfile={out}/daemon.pid")
    check("must deny: pkill --pidfile=<outside> is a file", not ok, off)
    ok, off, _ = reach(f"pgrep -F{out}/daemon.pid")
    check("must deny: an attached -F<path> is a file", not ok, off)
    ok, off, _ = reach(f"pgrep -f {out}/bin/*")
    check("must deny: an UNQUOTED glob is a directory read before pgrep runs", not ok, off)
    ok, off, _ = reach(f"pgrep -f x; cat {out}/bin/daemon")
    check("must deny: per simple command, cat's operand after pgrep is judged", not ok, off)
    ok, off, _ = reach(f"pgrep -f \"$(cat {out}/bin/daemon)\"")
    check("must deny: a substitution inside the pattern is lifted out and judged", not ok, off)

    print(f"\n{'FAIL' if FAIL else 'PASS'}: {len(FAIL)} failing")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
