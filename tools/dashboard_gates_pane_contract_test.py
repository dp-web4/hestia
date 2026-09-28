#!/usr/bin/env python3
"""The dashboard's Gates pane (2026-09-28): the web half of #1132.

#1132 gave the operator a way to ratify the installed gates -- in the desktop app only. On the
boxes where the operator reads this dashboard no app build exists, so ratifying stayed a hand-signed
POST. The property that must not regress is the one #1132's review was about: the ratify carries
`expected` = the evidence.current the pane RENDERED, so the daemon can refuse bytes nobody saw.

Run: python3 tools/dashboard_gates_pane_contract_test.py   (bare; exit 1 on failure)
"""
import re
import sys
from pathlib import Path

UI = (Path(__file__).resolve().parents[1] / "core/src/server/dashboard/index.html").read_text()
FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)


def block() -> str:
    a = UI.index("// ---- GATES pane")
    b = UI.index("// ---- RUNTIME CONFIG pane", a)
    return UI[a:b]


def main() -> int:
    g = block()
    check("govern sub-nav has the chip", 'data-gov="gates"' in UI)
    check("pane registered and mounts by loading",
          re.search(r"gates:\s*\{\s*el:\s*'govern-gates',\s*mount:\s*\(\)\s*=>\s*gatesLoad\(\)", UI) is not None)
    check("reads the daemon's verdicts", "apiFetch('/api/gates/verify'" in g)
    check("exactly one write, and it is the ratify", g.count("method: 'POST'") == 1 and "apiFetch('/api/gates/ratify'" in g)
    check("the ratify carries expected = the rendered evidence.current",
          "gatesReport.evidence.current" in g and "JSON.stringify({ reason, expected })" in g)
    check("a reason is required before anything is sent", "if (!reason)" in g)
    check("a 409 says nothing was ratified and names what moved", "res.status === 409" in g and "differs" in g)
    check("UNKNOWN is never rendered as fine and cannot be ratified",
          "r.status === 'UNKNOWN'" in g and "disabled = true" in g)
    check("installed bytes are compared with the deploy's record", "matches deploy" in g and "differs from deploy" in g)
    for f in FAILS:
        print("FAIL", f)
    print(f"dashboard gates pane contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
