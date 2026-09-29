#!/usr/bin/env python3
"""The dashboard's Gates pane (2026-09-28): the web half of #1132.

#1132 gave the operator a way to ratify the installed gates -- in the desktop app only. On the
boxes where the operator reads this dashboard no app build exists, so ratifying stayed a hand-signed
POST. The property that must not regress is the one #1132's review was about: the ratify carries
`expected` = the evidence.current the pane RENDERED, so the daemon can refuse bytes nobody saw.

Spec v3 (dp, 2026-09-28: "currently gate ratify button ratifies all - including mismatched and
non-deployed"): ratify is PER GATE -- each row sends paths:[it] with expected for it alone -- and
ratify-all is enabled only when the daemon says bulk_ratify.allowed. Stale rows get forget.

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
    check("exactly two writes: ratify and forget",
          g.count("method: 'POST'") == 2 and "apiFetch('/api/gates/ratify'" in g and "apiFetch('/api/gates/forget'" in g)
    check("the ratify carries expected taken from the rendered evidence.current",
          "gatesReport.evidence.current" in g and "JSON.stringify(paths ? { reason, expected, paths } : { reason, expected })" in g)
    check("a per-gate ratify binds only its own gates",
          "paths.map(p => [p, all[p] ?? null])" in g)
    check("every discovered row has its own ratify control, stale rows a forget",
          "gates-ratify-one" in g and "gates-forget-one" in g and "g.discovered === false" in g)
    check("forget is offered only where the daemon says forgettable (#1156)",
          "g.forgettable === true" in g and "gates-forget-one" in g)
    check("a de-registered gate is badged, not offered for forget (#1156)",
          "g.not_registered === true" in g and "NOT REGISTERED — possible bypass" in g
          and "forget_blocked_reason" in g)
    check("ratify-all is enabled only when the daemon says every gate matches the deploy",
          "r.bulk_ratify.allowed" in g and "bulkBtn.disabled = false" in g)
    check("no ratify control is offered to a daemon without per-gate support",
          "const perGate = !!r.bulk_ratify" in g and "!perGate ? ''" in g)
    check("each row shows its deployment status",
          "not deployed" in g and "DEPLOY[g.deployment]" in g)
    check("a reason is required before anything is sent", "if (!reason) return" in g)
    check("a 409 says nothing was ratified and names what moved", "res.status === 409" in g and "differs" in g)
    check("UNKNOWN is never rendered as fine and cannot be ratified",
          "r.status === 'UNKNOWN'" in g and "bulkBtn.disabled = true" in g)
    check("installed bytes are compared with the deploy's record", "matches deploy" in g and "differs from deploy" in g)
    for f in FAILS:
        print("FAIL", f)
    print(f"dashboard gates pane contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
