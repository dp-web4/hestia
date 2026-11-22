#!/usr/bin/env python3
"""gate_evaluate (#1450 `evaluate` v0): the gate's answer, with nothing filed.

Each row drives the REAL `decide()` through `tools/gate_evaluate.py` against a loopback stub daemon (the
real wire shape) that records every tool it is asked, and checks two things: the answer the gate gives, and that the
daemon saw nothing but the snapshot read.

  1. an in-scope read is `would_allow`, society law reported unchecked, not passed;
  2. an existing out-of-scope path is `mrh.path` with a scope_request route, and NO scope
     request is opened or peeked (`hestia_request_scope`-class tools never reach the daemon);
  3. a missing path is `mrh.path.nonexistent`, with no appeal route (nothing there to grant);
  4. a write to a governance surface is `gate.self_access` with the escalation route, and no
     escalation is opened; a read of one is reported and passes to ordinary law, and nothing is witnessed;
  5. the snapshot is the session the gate would reuse: the dry-run connect finds the member's
     existing session, law and scope ride THAT session (no synthetic id, no dry-run spelling),
     and a changed HESTIA_ROLE still evaluates as the role the session was minted with (#1490);
  6. no live session, a daemon without the dry-run RPC, or an incomplete law read is an
     explicit `error` naming why, and none of them reaches a mutating connect;
  7. the belt: inside the dry run, a write tool posted on the raw wire (as `scope_call` posts),
     a mutating connect, or a law read on any session but the found one is refused before it is
     sent, and the daemon never sees it;
  8. after a dry run every replaced mechanism call is the original again.

Run: python3 tools/gate_evaluate_test.py
"""
import http.server
import json
import os
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
# The repo root: the nearest ancestor holding plugins/_shared (tools/, or a mutant's scratch dir).
ROOT = next(p for p in HERE.parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
sys.path.insert(0, str(HERE))   # the gate_evaluate beside this file
import hestia_gate_core as core  # noqa: E402
import hestia_gate_mechanism as m  # noqa: E402
import hestia_gate_mechanism_test as mt  # noqa: E402
import gate_evaluate as ge  # noqa: E402

FAILS = []
HANDSHAKE = ("initialize", "notifications/initialized")


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}: {str(detail)[:500]}")


class _Stub(http.server.BaseHTTPRequestHandler):
    """A loopback daemon speaking the real wire shape (MCP streamable-HTTP JSON-RPC; every tool
    reply a `result` carrying `structuredContent` and a JSON text block). It records every
    method and tool it is asked, so anything the belt fails to stop is seen here."""

    asked: list = []
    dry_args: list = []
    real_connects: int = 0
    legacy: bool = False
    broken_law: bool = False
    # A daemon that answers, but not the contract: "v1" (the withdrawn synthetic-id dry run),
    # "law_role" (law read as a different role than the found session's), "unbound_scope".
    fault: str = ""
    # The daemon's sessions, as (member, host session) -> (session id, minted role).
    sessions: dict = {}
    ws: str = ""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        method = body.get("method")
        name = (body.get("params") or {}).get("name") if method == "tools/call" else method
        _Stub.asked.append(name)
        arguments = (body.get("params") or {}).get("arguments") or {}
        if name == "hestia_connect":
            _Stub.real_connects += 1
        if name in ("hestia_connect_dry_run", "hestia_operating_law", "hestia_scope_status"):
            _Stub.dry_args.append((name, arguments))
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {},
                      "serverInfo": {"name": "stub", "version": "1"}}
        else:
            # The real daemon's contract, in miniature: the dry-run connect answers only for an
            # existing (member, host session) with its minted role; law and scope resolve the
            # session they are sent and answer as ITS member and role.
            by_sid = {sid: (mem, role) for (mem, _h), (sid, role) in _Stub.sessions.items()}
            if name == "hestia_connect_dry_run":
                hit = _Stub.sessions.get((arguments.get("plugin_id"), arguments.get("host_session_id")))
                sc = ({"_hestia_error": {"code": "hestia.unknown_tool"}} if _Stub.legacy
                      else {"_hestia_error": {"code": "hestia.connect_dry_run_no_session"}} if not hit
                      else {"sessionId": hit[0], "constellationRole": hit[1], "reused": True,
                            "roleDeclarationHonored": arguments.get("role") == hit[1],
                            "dryRun": True, "dryRunSnapshotContract": 2})
                if _Stub.fault == "v1" and hit:
                    sc.update({"sessionId": hit[0], "dryRunSnapshotContract": 1})
            elif name == "hestia_operating_law":
                who = by_sid.get(arguments.get("session_id"))
                sc = ({"_hestia_error": {"code": "hestia.operating_law_unattributed"}} if not who
                      else {"identity": {"plugin_id": who[0], "role": who[1]},
                            "law_hash": "h-stub", "operator_grant": None})
                if _Stub.broken_law and who:
                    sc.pop("law_hash")
                if _Stub.fault == "law_role" and who:
                    sc["identity"]["role"] = "role:constellation:interactive-dev"
            elif name == "hestia_scope_status":
                who = by_sid.get(arguments.get("session_id"))
                sc = {"plugin_id": arguments.get("plugin_id"), "requests": [], "live_grants": [],
                      "standing_grants": [{"path": _Stub.ws + "/web4", "recursive": True}],
                      "generation": 1, "snapshot_expires_at": int(time.time()) + 3600,
                      "caller_bound": (bool(who and who[0] == arguments.get("plugin_id"))
                                       and _Stub.fault != "unbound_scope")}
            else:
                sc = {"sessionId": "minted-by-a-real-connect", "ok": True} \
                    if name == "hestia_connect" else {"ok": True, "recorded": name}
            result = {"structuredContent": sc, "content": [{"type": "text", "text": json.dumps(sc)}]}
        out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("mcp-session-id", "stub-mcp")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def daemon(ws):
    _Stub.ws = ws
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{srv.server_address[1]}/mcp"
    m._discover_endpoint = lambda: endpoint
    return endpoint


SID = "5b0c7e1e-0000-4000-8000-00000000e7a1"   # the daemon's id for kimi-code's host session
MINTED = "role:constellation:member"           # the role that session was minted with


def run(tool, tool_input, ws, session="sess-eval-test"):
    _Stub.asked = []
    _Stub.dry_args = []
    _Stub.real_connects = 0
    out = ge.evaluate(tool, tool_input, member="kimi-code", cwd=ws, session_id=session)
    return out, [a for a in _Stub.asked if a not in HANDSHAKE]


def main() -> int:
    ws = mt._fake_workspace()
    os.environ["HESTIA_WORKSPACE"] = ws
    core._under_temp_root = lambda *a, **k: False
    originals = {n: getattr(m, n) for n in ("claim_self_write", "witness_gate_self", "claim_scope",
                                             "query_society_safety", "record_decision",
                                             "scope_batch", "tally_scope", "emit_attestation",
                                             "fetch_policy_snapshot")}
    import urllib.request
    urlopen_before = urllib.request.urlopen
    call_tool_before = m._McpHttp.call_tool
    daemon(ws)
    _Stub.sessions = {("kimi-code", "sess-eval-test"): (SID, MINTED)}
    os.environ.pop("HESTIA_ROLE", None)
    reads = ge.READ_TOOLS

    inside = os.path.join(ws, "web4", "notes.md")
    open(inside, "w").close()
    out, asked = run("Read", {"file_path": inside}, ws)
    check("in_scope_read_allows", out["answer"] == "would_allow", out)
    check("society_reported_unchecked", out["society"].startswith("unchecked"), out)
    check("would_allow_is_local_conditional",
          out["boundary"].startswith("LOCAL/CONDITIONAL would_allow")
          and "society unchecked" in out["boundary"], out)
    check("in_scope_read_asked_only_reads", set(asked) <= reads, asked)

    outside = os.path.join(ws, "private", "ledger.txt")
    os.makedirs(os.path.dirname(outside), exist_ok=True)
    open(outside, "w").close()
    out, asked = run("Read", {"file_path": outside}, ws)
    check("out_of_scope_denies_on_scope", out["answer"] == "would_deny" and out["rule"] == "mrh.path", out)
    check("out_of_scope_route_is_scope_request",
          [r["route"] for r in out["routes"]] == ["scope_request"]
          and out["routes"][0]["target"] == outside, out["routes"])
    check("out_of_scope_reason_is_the_law_not_a_dry_run_note", "dry run" not in out["reason"], out["reason"])
    check("out_of_scope_opened_nothing", set(asked) <= reads, asked)
    check("out_of_scope_no_refused_side_effect", out["refused_side_effects"] == [], out)

    missing = os.path.join(ws, "private", "not-there.txt")
    out, asked = run("Read", {"file_path": missing}, ws)
    check("missing_is_nonexistent", out["rule"] == "mrh.path.nonexistent", out)
    check("missing_has_no_appeal_route", out["routes"] == [], out["routes"])
    check("missing_asked_only_reads", set(asked) <= reads, asked)

    gate_file = str(ROOT / "plugins" / "_shared" / "hestia_gate_core.py")
    out, asked = run("Write", {"file_path": gate_file, "content": "x"}, ws)
    check("closure_write_is_self_access", out["rule"] == "gate.self_access", out)
    # Decided at the closure, before any snapshot is read: the answer stands without one.
    check("closure_write_is_a_deny_not_an_error", out["answer"] == "would_deny", out)
    check("closure_write_route_is_escalation",
          [r["route"] for r in out["routes"]] == ["escalation"], out["routes"])
    check("closure_write_opened_no_escalation", set(asked) <= reads, asked)
    check("closure_write_no_refused_side_effect", out["refused_side_effects"] == [], out)

    out, asked = run("Read", {"file_path": gate_file}, ws)
    # The closure reports the read and lets it pass; ordinary law below it then judges the
    # path (the gate file is outside this fake workspace, so here that is a scope refusal).
    check("closure_read_is_reported", out["closure"] == "read", out)
    check("closure_read_passes_to_law", out["rule"] != "gate.self_access", out)
    check("closure_read_witnessed_nothing", set(asked) <= reads, asked)
    check("closure_read_no_refused_side_effect", out["refused_side_effects"] == [], out)
    check("snapshot_uses_the_dry_run_connect",
          [n for n, _ in _Stub.dry_args] == [
              "hestia_connect_dry_run", "hestia_operating_law", "hestia_scope_status"],
          _Stub.dry_args)
    check("law_and_scope_ride_the_found_session",
          all(a.get("session_id") == SID for n, a in _Stub.dry_args
              if n != "hestia_connect_dry_run"), _Stub.dry_args)
    check("no_synthetic_or_dry_run_spelling_is_sent",
          not any("dry_run" in a for _, a in _Stub.dry_args), _Stub.dry_args)
    check("evaluated_as_the_found_session",
          out["evaluated_as"] and out["evaluated_as"]["session"] == SID
          and out["evaluated_as"]["role"] == MINTED, out)
    check("successful_snapshot_never_really_connects", _Stub.real_connects == 0)

    # The reviewer's parity row: the session was MINTED as member; the caller now declares
    # interactive-dev. The real gate's reuse keeps the minted role, so the dry run must too.
    os.environ["HESTIA_ROLE"] = "role:constellation:interactive-dev"
    out, asked = run("Read", {"file_path": inside}, ws)
    del os.environ["HESTIA_ROLE"]
    check("changed_role_evaluates_as_the_minted_role",
          out["evaluated_as"] and out["evaluated_as"]["role"] == MINTED
          and out["evaluated_as"]["declared_role_honored"] is False, out)
    check("changed_role_still_answers", out["answer"] == "would_allow", out)

    # No live session for this host session: a real connect would MINT one, so there is
    # nothing to evaluate as. An explicit error, and nothing but the dry-run connect is asked.
    out, asked = run("Read", {"file_path": inside}, ws, session="sess-never-seen")
    check("no_live_session_is_an_explicit_error", out["answer"] == "error", out)
    check("no_live_session_says_why",
          "connect_dry_run_no_session" in (out["snapshot_error"] or ""), out)
    check("no_live_session_asks_only_the_dry_run_connect",
          asked and set(asked) == {"hestia_connect_dry_run"}, asked)
    check("no_live_session_never_really_connects", _Stub.real_connects == 0)

    _Stub.legacy = True
    out, asked = run("Read", {"file_path": inside}, ws)
    _Stub.legacy = False
    check("legacy_daemon_is_an_explicit_error", out["answer"] == "error", out)
    check("legacy_daemon_gets_only_the_safe_unknown_rpc",
          asked and set(asked) == {"hestia_connect_dry_run"}, asked)
    check("legacy_daemon_never_gets_a_mutating_connect", _Stub.real_connects == 0)

    _Stub.broken_law = True
    out, asked = run("Read", {"file_path": inside}, ws)
    _Stub.broken_law = False
    check("incomplete_law_is_an_explicit_error", out["answer"] == "error", out)
    check("incomplete_law_is_not_silently_partial",
          (out["snapshot_error"] or "").startswith("hestia_operating_law"), out)
    check("incomplete_law_never_reaches_scope_status", "hestia_scope_status" not in asked, asked)

    # A daemon that answers but not with THIS contract is no answer: the withdrawn v1 dry run,
    # a law read as some other role than the found session's, an unbound scope read.
    for fault, stage in (("v1", "hestia_connect_dry_run"), ("law_role", "hestia_operating_law"),
                         ("unbound_scope", "hestia_scope_status")):
        _Stub.fault = fault
        out, asked = run("Read", {"file_path": inside}, ws)
        _Stub.fault = ""
        check(f"{fault}_is_an_explicit_error", out["answer"] == "error", out)
        check(f"{fault}_names_its_stage", (out["snapshot_error"] or "").startswith(stage), out)

    # The belt, at the wire: a write tool posted the way `scope_call` posts it (raw urllib, not
    # the mechanism's client) is refused before it is sent, and the daemon never sees it.
    import urllib.request
    endpoint = m._discover_endpoint()
    _Stub.asked = []
    with ge._dry(m, ge.load_gate()[0]) as rec:
        req = urllib.request.Request(endpoint, data=json.dumps(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "hestia_request_scope", "arguments": {}}}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=2)
            check("belt_refuses_a_write_tool", False, "the call went through")
        except ge.SideEffectRefused:
            pass
        check("belt_records_the_refusal", rec["refused_calls"] == ["hestia_request_scope"], rec)
    check("belt_never_reached_the_daemon", "hestia_request_scope" not in _Stub.asked, _Stub.asked)
    with ge._dry(m, ge.load_gate()[0]) as rec:
        req = urllib.request.Request(endpoint, data=json.dumps(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "hestia_connect", "arguments": {}}}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=2)
            check("belt_refuses_non_dry_connect", False, "the call went through")
        except ge.SideEffectRefused:
            pass
        check("belt_records_non_dry_connect", rec["refused_calls"] == ["hestia_connect"], rec)
    check("non_dry_connect_never_reached_the_daemon", "hestia_connect" not in _Stub.asked, _Stub.asked)
    # A law read on a session the dry-run connect did not find (here: none was found yet, and
    # the id is someone else's) is refused before it is sent: it would read another member's
    # law, or count as an unbound read against the step C rollout signal.
    with ge._dry(m, ge.load_gate()[0]) as rec:
        req = urllib.request.Request(endpoint, data=json.dumps(
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
             "params": {"name": "hestia_operating_law",
                        "arguments": {"session_id": "someone-elses"}}}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=2)
            check("belt_refuses_an_unfound_session_read", False, "the call went through")
        except ge.SideEffectRefused:
            pass
    check("unfound_session_read_never_reached_the_daemon",
          "hestia_operating_law" not in _Stub.asked, _Stub.asked)
    check("restored_urlopen", urllib.request.urlopen is urlopen_before)
    check("restored_call_tool", m._McpHttp.call_tool is call_tool_before)

    for n, fn in originals.items():
        check(f"restored_{n}", getattr(m, n) is fn, n)

    for f in FAILS:
        print("FAIL", f)
    print(f"gate_evaluate: {'FAIL' if FAILS else 'ok'} ({len(FAILS)} failures)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
