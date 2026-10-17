#!/usr/bin/env python3
"""The dashboard's standing-grant writes are bound to the row the page SHOWED (2026-09-29).

Last edit wins in the engine (ruled 2026-09-25). A grant on a (member, path) that already holds a
standing grant replaces it; make-standing replaces a standing twin; reassign moves the source row
as it is now. The daemon refuses (409 `moved`, nothing written) when the `expected_existing` it is
sent is not the row in its store (#1168, #1178) — but only if the view SENDS it. The desktop app
does; this pins that the dashboard does too, for all three writes, and that a replaced row is put
in front of the operator before the grant form overwrites it.

The binding lookup is PURE and is run under node, not only matched as text: a source-only pin
would stay green if the lookup returned null for every row, which would bind every write to
"shown none" and turn each replacement into a spurious 409.

Run: python3 tools/dashboard_scope_binding_contract_test.py   (bare; exit 1 on failure)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

UI = (Path(__file__).resolve().parents[1] / "core/src/server/dashboard/index.html").read_text()
FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)


def fn(name: str) -> str:
    a = UI.index(f"function {name}(")
    depth, i = 0, UI.index("{", a)
    while True:
        depth += UI[i] == "{"
        depth -= UI[i] == "}"
        i += 1
        if depth == 0:
            return UI[a:i]


def between(a: str, b: str) -> str:
    i = UI.index(a)
    return UI[i:UI.index(b, i)]


def source_contract():
    grant = between("apiFetch('/api/scope/grant'", "grant failed:")
    pre_grant = UI[UI.rindex("const shown = standingBinding(", 0, UI.index("apiFetch('/api/scope/grant'")):UI.index("apiFetch('/api/scope/grant'")]
    check("the grant form looks up the standing row it would replace", "standingBinding(lastData, body.plugin_id, grantPath)" in pre_grant)
    check("and shows it before replacing it", "This REPLACES the standing grant" in pre_grant and "confirm(" in pre_grant)
    check("and sends it as expected_existing (null when none)", "body.expected_existing = shown" in pre_grant)
    check("a moved grant says nothing was done and re-reads",
          "out.moved" in grant and "scopeMovedMessage(out)" in grant and "renderScopeGrants(lastData)" in grant)

    promote = between("const pro = e.target.closest('[data-promote-member]')", "// make recursive / make exact")
    check("make standing names the standing twin it replaces", "standingBinding(lastData, member, p)" in promote
          and "This REPLACES the standing grant already on this path" in promote)
    check("make standing is bound to that twin", "expected_existing: twin" in promote)
    check("a moved promote is reported as such", "o && o.moved" in promote or "out && out.moved" in promote)

    move = between("const mv = e.target.closest('[data-move-member]')", "// Revoke a LIVE grant")
    check("reassign captures the source row at the click, before its prompts",
          move.index("const shownSrc = standingBinding(lastData, from, p2)") < move.index("prompt("))
    check("reassign is bound to that row", "expected_existing: shownSrc" in move)
    check("a moved reassign is reported as such", "o && o.moved" in move)

    reach = between("const rch = e.target.closest('[data-reach-member]')", "// REASSIGN")
    check("reach sends no binding: it only flips exact/subtree, and the daemon refuses a no-op",
          "expected_existing" not in reach)


def behaviour():
    prog = (fn("normScopePath") + fn("standingBinding") + fn("scopeMovedMessage") +
            "\nconst A = JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify(A.calls.map(c => c[0] === 'bind'"
            " ? standingBinding(A.data, c[1], c[2]) : scopeMovedMessage(c[1]))));")
    data = {"scope_grants": [
        {"lifetime": "live", "plugin_id": "hub-being", "path": "/w/notes", "reason": "asked",
         "request_id": "r1", "recursive": False, "secs_remaining": 60},
        {"lifetime": "standing", "plugin_id": "hub-being", "path": "/w/home", "reason": "its home",
         "granted_by": "operator", "request_id": None, "recursive": True, "expires_at": None,
         "secs_remaining": None, "granted_at": 5},
    ]}
    calls = [
        ["bind", "hub-being", " /w/./home/ "],      # the store's key, from a sloppy spelling
        ["bind", "hub-being", "/w/notes"],          # a LIVE row is not what a standing write replaces
        ["bind", "claude-code", "/w/home"],         # another member's path
        ["moved", {"moved": True, "current": {"reason": "edited elsewhere", "recursive": False}}],
        ["moved", {"moved": True, "current": None}],
    ]
    r = subprocess.run(["node", "-e", prog, json.dumps({"data": data, "calls": calls})],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[:300]}")
        return
    got = json.loads(r.stdout)
    # exactly the five fields the daemon compares (grant_binding_of) — clock fields excluded
    check("the binding is the five fields the daemon compares, from the standing row",
          got[0] == {"reason": "its home", "recursive": True, "granted_by": "operator",
                     "expires_at": None, "request_id": None})
    check("a live row binds as none", got[1] is None)
    check("another member's row binds as none", got[2] is None)
    check("the moved message names what it now reads", "edited elsewhere" in got[3] and "nothing was done" in got[3])
    check("and says when the row is gone", "it is gone" in got[4])


def main() -> int:
    source_contract()
    if shutil.which("node"):
        behaviour()
    else:
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"dashboard scope binding contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
