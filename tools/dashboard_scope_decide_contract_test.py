#!/usr/bin/env python3
"""The dashboard's scope-request panel (2026-10-05): a scope refusal is an escalation.

dp, 2026-10-05: "yes on gate gap, let's fix it. escalation should allow standing grants". The spec
(docs/operator-surfaces/spec.json, decide-scope-request obligations) requires both surfaces to:
show a GATE-OPENED request's refused act as the act (never as the member's reason); choose the
DURATION at decide time (once only when the gate recorded an act, session, standing); choose the
BREADTH (exact, or a directory above it, always recursive, never the root); offer no exact grant
for a glob reach; and send all of it in the one decide call.

Static checks pin the wiring; the three pure helpers are also RUN under node, so the option sets
and the request body are asserted as values, not as spellings.

Run: python3 tools/dashboard_scope_decide_contract_test.py   (bare; exit 1 on failure)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

UI = (Path(__file__).resolve().parents[1] / "core/src/server/dashboard/index.html").read_text()
FAILS = []


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}{': ' + str(detail)[:400] if detail else ''}")


def block() -> str:
    a = UI.index("function renderScopeRequests(")
    b = UI.index("function scopeDecideBody(", a)
    c = UI.index("\n  }", b)
    return UI[a:c]


def helpers() -> str:
    a = UI.index("function scopeAwaitsOperator(")
    b = UI.index("function scopeDecideBody(", a)
    c = UI.index("\n  }\n", b) + 4
    return UI[a:c]


def run_node(js: str):
    node = shutil.which("node")
    if not node:
        FAILS.append("node is required to run the pure helpers (a check that cannot run certifies nothing)")
        return None
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        FAILS.append(f"node failed: {p.stderr[:400]}")
        return None
    return json.loads(p.stdout)


def main() -> int:
    g = block()
    check("a gate-opened request shows the refused act, labelled as the act",
          "r.origin === 'gate_deny'" in g and "this is what you are ruling on" in g and "r.act" in g)
    check("the act is never rendered as the member's reason",
          "the member stated no reason" in g)
    check("re-issues are shown", "r.reissues" in g)
    check("a glob reach says only a recursive grant covers it", "r.subtree" in g and "only a recursive grant" in g)
    check("duration and breadth controls exist", "scope-duration" in g and "scope-breadth" in g)
    check("breadth is disabled for a one-time approval", "breadth.disabled = duration.value === 'once'" in g)
    check("one decide call carries duration and breadth",
          g.count("apiFetch('/api/scope/decide'") == 1 and "scopeDecideBody(r, granted" in g)
    check("a grant still needs a note; refusing does not", "grantBtn.disabled = !note.value.trim()" in g)
    # dp, 2026-10-05: "scope escalations should go to peers not to me".
    check("the banner counts only what no peer can clear",
          "pend.filter(r => scopeAwaitsOperator(r))" in g and "no peer can clear" in g)
    check("a peer-routed row says who was invited and labels the controls as override",
          "scopeRouteText(r)" in g and "'override: grant'" in g and "'override: refuse'" in g)
    check("a peer's ruling shows the peer and its NOT-SAME basis on the reach row",
          "g.granted_by.startsWith('peer:')" in UI and "pb.independence" in UI)

    js = "function escapeHtml(s){return String(s);}\n" + helpers() + r"""
const out = {};
out.awaitPeer = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: ['kimi-code']});
out.awaitOpNoPeer = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: []});
out.awaitOpMember = scopeAwaitsOperator({origin: 'member_request'});
out.route = scopeRouteText({origin: 'gate_deny', invited_peers: ['kimi-code', 'codex']});
out.durGate = scopeDurationOptions({once_available: true}).map(x => x[0]);
out.durMember = scopeDurationOptions({once_available: false}).map(x => x[0]);
out.breadth = scopeBreadthOptions('/home/u/.local/state/mesh/x.log', false);
out.breadthGlob = scopeBreadthOptions('/var/log/app', true);
out.breadthTop = scopeBreadthOptions('/etc', false);
const r = {request_id: 'scope-1'};
out.refuse = scopeDecideBody(r, false, '', 'standing', out.breadth[2]);
out.once = scopeDecideBody(r, true, 'one read', 'once', out.breadth[2]);
out.session = scopeDecideBody(r, true, 'logs', 'session', out.breadth[0]);
out.standingAnc = scopeDecideBody(r, true, 'mesh state', 'standing', out.breadth[2]);
process.stdout.write(JSON.stringify(out));
"""
    o = run_node(js)
    if o is not None:
        check("a gate request with invited peers awaits a PEER, not the operator",
              o["awaitPeer"] is False and o["awaitOpNoPeer"] is True and o["awaitOpMember"] is True, o)
        check("the route text names the invited peers and the override",
              "kimi-code, codex" in o["route"] and "OVERRIDE" in o["route"], o["route"])
        check("once is offered only when the gate recorded an act",
              o["durGate"] == ["once", "session", "standing"] and o["durMember"] == ["session", "standing"], o)
        paths = [(b["grant_path"], b["recursive"]) for b in o["breadth"]]
        check("breadth: exact, the path recursive, then every ancestor recursive, never the root",
              paths == [(None, False), (None, True), ("/home/u/.local/state/mesh", True),
                        ("/home/u/.local/state", True), ("/home/u/.local", True), ("/home/u", True),
                        ("/home", True)], paths)
        check("every option label shows the path it reaches",
              all(("/home" in b["label"]) for b in o["breadth"]), o["breadth"])
        check("a glob reach offers no exact grant",
              all(b["recursive"] for b in o["breadthGlob"]) and o["breadthGlob"][0]["grant_path"] is None,
              o["breadthGlob"])
        check("a top-level path offers no root grant",
              [b["grant_path"] for b in o["breadthTop"]] == [None, None], o["breadthTop"])
        check("a refusal carries no duration and no breadth",
              o["refuse"] == {"request_id": "scope-1", "granted": False, "reason": None}, o["refuse"])
        check("once carries only once", o["once"] == {"request_id": "scope-1", "granted": True,
                                                       "reason": "one read", "once": True}, o["once"])
        check("session exact is not standing and not recursive",
              o["session"] == {"request_id": "scope-1", "granted": True, "reason": "logs",
                               "standing": False, "recursive": False}, o["session"])
        check("standing at an ancestor is recursive and names the directory",
              o["standingAnc"] == {"request_id": "scope-1", "granted": True, "reason": "mesh state",
                                   "standing": True, "recursive": True,
                                   "grant_path": "/home/u/.local/state/mesh"}, o["standingAnc"])
    for f in FAILS:
        print("FAIL", f)
    print(f"dashboard scope decide contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
