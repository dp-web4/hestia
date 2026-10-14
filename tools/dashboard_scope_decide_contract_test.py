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


def fn_src(name: str) -> str:
    """One top-level dashboard function, by brace matching from its declaration."""
    a = UI.index(f"function {name}(")
    i = UI.index("{", UI.index(")", a))
    depth = 0
    for j in range(i, len(UI)):
        if UI[j] == "{":
            depth += 1
        elif UI[j] == "}":
            depth -= 1
            if depth == 0:
                return UI[a:j + 1]
    raise ValueError(name)


def render_js() -> str:
    fake_dom = r"""
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ''; this.hidden = false;
    this._html = ''; this.textContent = ''; this.value = ''; this.disabled = false; this.listeners = {};
    this.options = []; }
  set innerHTML(h) { this._html = h; this.children = []; }
  get innerHTML() { return this._html; }
  appendChild(c) { this.children.push(c); if (this.tag === 'select' && c.tag === 'option') {
    this.options.push(c); if (this.options.length === 1) this.value = c.value; } return c; }
  addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); }
  async click() { for (const f of this.listeners.click || []) await f(); }
  walk(out = []) { out.push(this); for (const c of this.children) c.walk(out); return out; }
}
const byId = {};
const document = { createElement: t => new El(t), getElementById: id => (byId[id] = byId[id] || new El('div')) };
const $ = id => document.getElementById(id);
function escapeHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function memberName(id) { return escapeHtml(String(id)); }
function escFmtAge(s) { return s + 's'; }
const scopeDrafts = new Map();
let scopeRenderedSig = null;
let SENT = null;
async function apiFetch(url, opts) { SENT = JSON.parse(opts.body); return { ok: true, json: async () => ({}) }; }
async function tick() {}
"""
    names = ["renderScopeRequests", "scopeAwaitsOperator", "scopeRouteText", "scopeAllowedDecisions",
             "scopeEnumerable", "scopeOnceOnly", "scopeGrantLabel", "scopeRefuseLabel",
             "scopeDurationOptions", "scopeBreadthOptions", "scopeDecideBody",
             "renderLedgerRow", "renderLedgerIdentity", "ledgerOnceOnly", "ledgerOffersGrant",
             "ledgerScopeDecideBody", "ledgerFmtWhen"]
    why = UI[UI.index("const SCOPE_ONCE_ONLY_WHY"):]
    why = why[:why.index(";") + 1]
    return fake_dom + why + "\n" + "\n".join(fn_src(n) for n in names) + r"""
async function renderOne(r, clickFirst, note) {
  scopeRenderedSig = null; SENT = null;
  for (const k of Object.keys(byId)) delete byId[k];
  renderScopeRequests({ pending_scope_requests: [r] });
  const list = $('scope-list');
  const row = list.children[0];
  const els = row.walk();
  const buttons = els.filter(e => e.tag === 'button');
  const selects = els.filter(e => e.tag === 'select').map(e => e.className);
  if (clickFirst) {
    const input = els.find(e => e.tag === 'input');
    input.value = note;
    for (const f of input.listeners.input || []) f();
    await buttons[0].click();
  }
  return { buttons: buttons.map(b => b.textContent), selects, html: row.innerHTML, sent: SENT };
}
(async () => {
  const gate = { origin: 'gate_deny', invited_peers: [], act: 'for f in a b; do cat $f; done',
                 rule: 'mrh.command', tool: 'Bash', secs_remaining: 60, claimed_by: 'codex' };
  const out = {};
  out.unenum = await renderOne({ ...gate, request_id: 'scope-u',
    path: 'hestia:unpriceable:unenumerated#0123456789abcdef', once_available: true, once_only: true,
    enumerable: false, allowed_decisions: ['once', 'refuse'] }, true, 'one run');
  out.path = await renderOne({ ...gate, request_id: 'scope-p', path: '/w/plain.txt',
    once_available: true, once_only: false, enumerable: true,
    allowed_decisions: ['once', 'session', 'standing', 'refuse'] }, false);
  out.member = await renderOne({ request_id: 'scope-m', origin: 'member_request', path: '/w/m.txt',
    reason: 'need it', secs_remaining: 60, claimed_by: 'kimi-code', once_available: false,
    enumerable: true, allowed_decisions: ['session', 'standing', 'refuse'] }, false);
  const lrow = (over) => ({ status: 'open', kind: 'scope_request', id: 'scope-u', event_type: 'scope_requested',
    opened_at: '2026-10-13T00:00:00Z', opened_hash: 'ab'.repeat(32), plugin_id: 'codex', ...over });
  const lu = lrow({ allowed_decisions: ['once', 'refuse'] });
  const lp = lrow({ id: 'scope-p', allowed_decisions: ['once', 'session', 'standing', 'refuse'] });
  out.ledgerUnenum = renderLedgerRow(lu);
  out.ledgerPath = renderLedgerRow(lp);
  out.ledgerEsc = renderLedgerRow(lrow({ kind: 'escalation', id: 'e1', allowed_decisions: undefined }));
  out.ledgerUnenumBody = ledgerScopeDecideBody(lu, true, 'x');
  out.ledgerPathBody = ledgerScopeDecideBody(lp, true, 'x');
  process.stdout.write(JSON.stringify(out));
})();
"""


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
    check("an unenumerated act is labelled as no path, not shown as one",
          "!scopeEnumerable(r)" in g and "no path: the gate cannot enumerate" in g)
    # #1287 part 2: the row offers what the daemon says the decide endpoint accepts.
    check("a once-only row renders no duration/breadth and a grant only when one is accepted",
          "if (!onceOnly) {" in g and "if (offersGrant) controls.appendChild(grantBtn);" in g)
    check("a once-only row sends once, whatever the (absent) duration select says",
          "chosenDuration()" in g and "onceOnly ? 'once' : duration.value" in g)
    # dp, 2026-10-05: "scope escalations should go to peers not to me".
    check("the banner counts only what no peer can clear",
          "pend.filter(r => scopeAwaitsOperator(r))" in g and "awaiting your decision" in g)
    # dp, 2026-10-13: every gate request invites peers, so a banner shown only for operator-only
    # requests never showed, and the decide control (a modal) was unreachable from the main view.
    check("the banner shows whenever anything is pending, quietly when all are peer-routed",
          "banner.hidden = pend.length === 0;" in g and "with peers to decide" in g
          and "esc-banner-quiet" in g)
    check("a peer-routed row says who was invited and labels the controls as override",
          "scopeRouteText(r)" in g and "scopeGrantLabel(r, override)" in g
          and "scopeRefuseLabel(r, override)" in g)
    check("a peer's ruling shows the peer and its NOT-SAME basis on the reach row",
          "g.granted_by.startsWith('peer:')" in UI and "pb.independence" in UI)

    js = "function escapeHtml(s){return String(s);}\n" + helpers() + r"""
const out = {};
out.awaitPeer = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: ['kimi-code']});
out.awaitOpNoPeer = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: []});
out.awaitOpMember = scopeAwaitsOperator({origin: 'member_request'});
// dp, 2026-10-13: a peer-routed request escalates to the operator when the window lapses.
out.awaitPeerInWindow = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: ['kimi-code'], decided_by_default: 'peer'});
out.awaitEscalated = scopeAwaitsOperator({origin: 'gate_deny', invited_peers: ['kimi-code'], decided_by_default: 'operator', peer_window_lapsed: true});
out.routeEscalated = scopeRouteText({origin: 'gate_deny', invited_peers: ['kimi-code', 'codex'], decided_by_default: 'operator', peer_window_lapsed: true, peer_window_secs: 1800});
out.route = scopeRouteText({origin: 'gate_deny', invited_peers: ['kimi-code', 'codex']});
out.durGate = scopeDurationOptions({once_available: true}).map(x => x[0]);
out.durMember = scopeDurationOptions({once_available: false}).map(x => x[0]);
out.durUnenum = scopeDurationOptions({once_available: true, once_only: true}).map(x => x[0]);
// #1287 part 2: the daemon's allowed_decisions is authoritative over the older flags.
out.durAllowedUnenum = scopeDurationOptions({once_available: true, once_only: false,
                                             allowed_decisions: ['once', 'refuse']}).map(x => x[0]);
out.durAllowedPath = scopeDurationOptions({allowed_decisions: ['once', 'session', 'standing', 'refuse']}).map(x => x[0]);
out.durAllowedMember = scopeDurationOptions({allowed_decisions: ['session', 'standing', 'refuse']}).map(x => x[0]);
out.allowedFallbackUnenum = scopeAllowedDecisions({once_available: true, once_only: true});
out.allowedFallbackPath = scopeAllowedDecisions({once_available: true});
out.onceOnly = scopeOnceOnly({allowed_decisions: ['once', 'refuse']});
out.notOnceOnly = scopeOnceOnly({allowed_decisions: ['once', 'session', 'standing', 'refuse']});
out.labels = [scopeGrantLabel({allowed_decisions: ['once', 'refuse']}, false),
              scopeRefuseLabel({allowed_decisions: ['once', 'refuse']}, false),
              scopeGrantLabel({allowed_decisions: ['once', 'refuse']}, true),
              scopeGrantLabel({allowed_decisions: ['session', 'standing', 'refuse']}, false),
              scopeRefuseLabel({allowed_decisions: ['session', 'standing', 'refuse']}, false)];
out.why = SCOPE_ONCE_ONLY_WHY;
out.breadthUnenum = scopeBreadthOptions('hestia:unpriceable:unenumerated#0123456789abcdef', false);
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
        check("a lapsed peer window escalates to the operator; inside it, it stays with the peers",
              o["awaitPeerInWindow"] is False and o["awaitEscalated"] is True, o)
        check("an escalated row says no peer ruled in time and that a peer may still decide",
              "30 min" in o["routeEscalated"] and "ESCALATED" in o["routeEscalated"]
              and "kimi-code, codex" in o["routeEscalated"], o["routeEscalated"])
        check("the route text names the invited peers and the override",
              "kimi-code, codex" in o["route"] and "OVERRIDE" in o["route"], o["route"])
        check("once is offered only when the gate recorded an act",
              o["durGate"] == ["once", "session", "standing"] and o["durMember"] == ["session", "standing"], o)
        # dp, 2026-10-10 (#1232 narrowed): an act the gate could not enumerate is once-only.
        check("an unenumerated act offers only 'this act once' and no breadth",
              o["durUnenum"] == ["once"] and o["breadthUnenum"] == [], o)
        check("allowed_decisions drives the durations offered",
              o["durAllowedUnenum"] == ["once"]
              and o["durAllowedPath"] == ["once", "session", "standing"]
              and o["durAllowedMember"] == ["session", "standing"], o)
        check("an older daemon without allowed_decisions falls back to its flags",
              o["allowedFallbackUnenum"] == ["once", "refuse"]
              and o["allowedFallbackPath"] == ["once", "session", "standing", "refuse"], o)
        check("once-only is exactly 'no session and no standing'",
              o["onceOnly"] is True and o["notOnceOnly"] is False, o)
        check("a once-only request is labelled exactly 'Approve once' / 'Refuse'",
              o["labels"] == ["Approve once", "Refuse", "override: Approve once", "grant", "refuse"],
              o["labels"])
        check("the one line says why",
              o["why"] == "what this act reaches is decided by an expansion, so only this exact act can be approved",
              o["why"])
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

    # ---- RENDERING (#1287 part 2): run renderScopeRequests and the ledger row renderer under a
    # minimal DOM, and read what the operator would see: the buttons, their labels, the selects,
    # the explanation, and the body a click sends.
    ro = run_node(render_js())
    if ro is not None:
        u, p, m = ro["unenum"], ro["path"], ro["member"]
        check("unenumerated: exactly 'Approve once' and 'Refuse', no duration and no breadth",
              u["buttons"] == ["Approve once", "Refuse"] and u["selects"] == [], u)
        check("unenumerated: one line says why", "decided by an expansion" in u["html"], u["html"][:300])
        check("unenumerated: clicking 'Approve once' sends once and nothing broader",
              u["sent"] == {"request_id": "scope-u", "granted": True, "reason": "one run", "once": True},
              u["sent"])
        check("a pathful gate request keeps duration, breadth, grant and refuse",
              p["buttons"] == ["grant", "refuse"] and p["selects"] == ["scope-duration", "scope-breadth"]
              and "decided by an expansion" not in p["html"], p)
        check("a member-filed request keeps grant and refuse", m["buttons"] == ["grant", "refuse"], m)
        lu, lp, le = ro["ledgerUnenum"], ro["ledgerPath"], ro["ledgerEsc"]
        check("ledger: an unenumerated scope row offers 'Approve once' and 'Refuse' with the why",
              "Approve once</button>" in lu and ">Refuse</button>" in lu and ">approve</button>" not in lu
              and "decided by an expansion" in lu, lu[-600:])
        check("ledger: its approve sends once",
              ro["ledgerUnenumBody"] == {"request_id": "scope-u", "granted": True, "reason": "x", "once": True},
              ro["ledgerUnenumBody"])
        check("ledger: a pathful scope row and an escalation keep approve/deny and no once",
              ">approve</button>" in lp and ">deny</button>" in lp and ">approve</button>" in le
              and ro["ledgerPathBody"] == {"request_id": "scope-p", "granted": True, "reason": "x"}, lp[-400:])
    for f in FAILS:
        print("FAIL", f)
    print(f"dashboard scope decide contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
