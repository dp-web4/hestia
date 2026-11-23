#!/usr/bin/env python3
"""Closure: BSD `sed -i '' SCRIPT FILE` reads SCRIPT as the script, not an in-place operand (#1598).

On macOS, BSD sed's `-i` takes the backup suffix as a SEPARATE argument (`sed -i '' s/a/b/ F`,
`sed -i .bak s/a/b/ F`). The classifier parsed only the GNU form (suffix attached, `-i.bak`), so it read
`''` as the script and the real script as a file edited in place. A script whose text names a closure
path was refused as `gate.self_access` and opened an escalation (McNugget, 2026-11-14, 8af5057f7a77a15c).

The BSD reading is taken only on its unambiguous shape: a BARE `-i`, no `-e` / `-f` script, at least three
positionals, and a first positional that is empty or dot-led (a BSD suffix; as a GNU script, `''` edits
nothing and `.bak` is a sed syntax error, so no GNU act is admitted that writes content).

Run:  ./tools/closure_bsd_sed_test.py
      HESTIA_CLOSURE_CORE=<path> ./tools/closure_bsd_sed_test.py   (a staged classifier)
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
GOV = f"{REPO}/plugins/_shared/hestia_gate_core.py"
M = "/plugins/" + "_shared/x"
OUT = "/private/tmp/x.py"


def verdict(cmd):
    return C.classify("Bash", {"command": cmd}, cwd=REPO).classification


def row(name, cmd, want):
    got = verdict(cmd)
    # "not-write": `none` or `read` (a closure path named as text is a witnessed read, and allowed).
    ok = got == "write" if want == "write" else got != "write"
    print(("  ok    " if ok else "  FAIL  ") + f"{name}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        FAIL.append(name)


def main() -> int:
    # ---- the false escalation: a BSD script naming a closure path, editing a file outside it ----
    row("BSD -i '' with a closure path in the script", f"sed -i '' 's|a|{M}|' {OUT}", "not-write")
    row("BSD -i .bak with a closure path in the script", f"sed -i .bak 's|a|{M}|' {OUT}", "not-write")
    row("BSD -n -i '' (separate flags)", f"sed -n -i '' 's|a|{M}|p' {OUT}", "not-write")
    row("BSD -i '' two files outside", f"sed -i '' 's|a|{M}|' {OUT} /private/tmp/y.py", "not-write")

    # ---- must stay write ----
    row("must write: BSD -i '' on a closure file", f"sed -i '' 's|a|b|' {GOV}", "write")
    row("must write: BSD -i .bak on a closure file", f"sed -i .bak 's|a|b|' {GOV}", "write")
    row("must write: BSD -i '' closure file second", f"sed -i '' 's|a|b|' {OUT} {GOV}", "write")
    row("must write: GNU -i on a closure file", f"sed -i 's|a|b|' {GOV}", "write")
    row("must write: GNU -i.bak attached", f"sed -i.bak 's|a|b|' {GOV}", "write")
    row("must write: -i '' -e script on a closure file", f"sed -i '' -e 's|a|b|' {GOV}", "write")
    row("must write: -i '' with only two positionals keeps the GNU reading", f"sed -i '' {GOV}", "write")
    row("must write: a first positional that is not suffix-shaped keeps GNU", f"sed -i 's|a|b|' {GOV} {OUT}", "write")
    row("must write: --in-place= with a closure file", f"sed --in-place=.bak 's|a|b|' {GOV}", "write")

    print(f"\n{'FAIL' if FAIL else 'PASS'}: {len(FAIL)} failing")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
