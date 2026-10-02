#!/usr/bin/env python3
"""Contract tests for the ONE decision witness — one-gate stage A.

`hestia_gate_mechanism.record_decision` witnesses every final gate verdict (allow, warn, deny)
and reports COMMITTED only on a daemon receipt that names the decision it recorded. This file
pins that contract against a stub daemon that speaks the daemon's real wire shape (MCP
streamable-HTTP JSON-RPC; every tool reply, error or not, is a successful `result` whose
payload is both `structuredContent` and a JSON text block — handler.rs `call_tool`).

Why the receipt rule is the whole point. #1139's recorder (and today's deployed
`witness_decision_unified`) returned True on any outer `result`. The daemon answers a refused
verdict and a FAILED CHAIN APPEND with exactly that — a `result` carrying `_hestia_error` — so
"recorded" was true of records that do not exist. C11 makes a consequential permit wait on a
committed witness; a recorder that cannot tell committed from refused certifies the difference
away. `test_a_failed_append_is_not_committed` is that defect as a falsifier.

The REAL-DAEMON arm runs only when pointed at an isolated daemon, never the live one:
    HESTIA_DECISION_CONTRACT_ENDPOINT=http://127.0.0.1:7799/mcp python3 tools/decision_witness_contract_test.py
CI's isolated-daemon job sets it. An endpoint on :7711 (the live daemon's port) is refused.

Run: python3 tools/decision_witness_contract_test.py
"""
import http.server
import inspect
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
import hestia_gate_mechanism as m  # noqa: E402
import hestia_witness_core as wc  # noqa: E402

FAILS: list = []
RAN: list = []


def check(name, ok, detail=""):
    if not ok:
        FAILS.append(f"{name}{': ' + str(detail) if detail else ''}")


H = "a" * 64            # a well-formed chain hash
H2 = "0123456789abcdef" * 4
LIVE_PORT = 7711


# ---- the stub daemon --------------------------------------------------------------------------

def ok_reply(rid, payload, *, is_error=False):
    """The daemon's tools/call envelope: handler.rs `call_tool` -> CallToolResult::success."""
    return {"jsonrpc": "2.0", "id": rid, "result": {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "structuredContent": payload,
        "isError": is_error,
    }}


def receipt(decision, *, h=H, recorded="appended", action_id=None, key=None, event=None):
    """The receipt shape core/src/server/handler.rs `tool_witness_decision` returns."""
    return {
        "witnessEntryHash": h,
        "eventType": event or m.DECISION_EVENT_TYPES[decision],
        "decision": decision,
        "recorded": recorded,
        "charged": decision != "allow" and recorded == "appended",
        "actionId": action_id,
        "correlationKey": key,
        "updatedTrust": None,
    }


class Stub:
    """A loopback MCP daemon. `on_call(args) -> raw JSON-RPC dict | None (= ok_reply(receipt))`."""

    def __init__(self, on_call=None, *, sse=False, delay=0.0):
        self.on_call = on_call
        self.sse = sse
        self.delay = delay
        self.calls = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                method = body.get("method")
                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    out = {"jsonrpc": "2.0", "id": body["id"], "result": {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "serverInfo": {"name": "stub", "version": "0"}}}
                else:
                    if stub.delay:
                        time.sleep(stub.delay)
                    params = body.get("params") or {}
                    stub.calls.append((params.get("name"), params.get("arguments") or {}))
                    args = params.get("arguments") or {}
                    out = stub.on_call(body["id"], args) if stub.on_call else None
                    if out is None:
                        out = ok_reply(body["id"], receipt(
                            args.get("decision"), action_id=args.get("action_id"),
                            key=args.get("correlation_key")))
                raw = json.dumps(out)
                data = (f"event: message\ndata: {raw}\n\n" if stub.sse else raw).encode()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/event-stream" if stub.sse else "application/json")
                self.send_header("mcp-session-id", "stub-session")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up first: the deadline test's intended outcome

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def witness_calls(self):
        return [a for n, a in self.calls if n == "hestia_witness_decision"]


def record(url, decision="allow", **kw):
    """record_decision through the REAL discovery + transport path, aimed at `url`."""
    saved = m._discover_endpoint
    m._discover_endpoint = lambda: url
    try:
        base = dict(plugin_id="codex", decision=decision, rule="gate.allow",
                    tool_name="Write", target="/tmp/x", session_id="sess-1",
                    verdict_available=True, attempted_summary="Write -> /tmp/x")
        base.update(kw)
        return m.record_decision(None, **base)
    finally:
        m._discover_endpoint = saved


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/mcp"


# ---- committed ------------------------------------------------------------------------------

def test_every_verdict_commits_on_a_receipt_that_names_it():
    stub = Stub()
    try:
        for decision in ("allow", "warn", "deny"):
            r = record(stub.url, decision, action_id="11111111-2222-3333-4444-555555555555",
                       correlation_key="toolu_01ABC")
            check(f"{decision}-committed", r.committed and r.status == "committed", r)
            check(f"{decision}-hash", r.entry_hash == H, r)
            check(f"{decision}-event", r.event_type == m.DECISION_EVENT_TYPES[decision], r)
            check(f"{decision}-not-dedup", r.deduplicated is False, r)
        wire = stub.witness_calls()
        check("one-wire-call-per-verdict", len(wire) == 3, stub.calls)
        a = wire[0]
        for k, v in (("decision", "allow"), ("adjudicator", "plugin-gate:codex"),
                     ("rule_id", "gate.allow"), ("reason", "gate.allow"),
                     ("verdict_available", True), ("target", "/tmp/x"),
                     ("action_id", "11111111-2222-3333-4444-555555555555"),
                     ("correlation_key", "toolu_01ABC"), ("session_id", "sess-1")):
            check(f"wire-arg-{k}", a.get(k) == v, a)
        check("wire-carries-core-digest-key", "core_digest" in a, a)
    finally:
        stub.close()


def test_sse_framed_receipt_commits():
    stub = Stub(sse=True)
    try:
        r = record(stub.url, "deny")
        check("sse-committed", r.committed, r)
    finally:
        stub.close()


def test_the_daemons_existing_row_is_a_committed_receipt():
    stub = Stub(lambda rid, a: ok_reply(rid, receipt(
        a["decision"], h=H2, recorded="existing", action_id=a.get("action_id"))))
    try:
        r = record(stub.url, "deny", action_id="11111111-2222-3333-4444-555555555555")
        check("dedup-committed", r.committed, r)
        check("dedup-flagged", r.deduplicated is True, r)
        check("dedup-hash-is-the-daemons", r.entry_hash == H2, r)
    finally:
        stub.close()


# ---- not committed: the daemon ruled ---------------------------------------------------------

def _ruled(code):
    return lambda rid, a: ok_reply(rid, {"_hestia_error": {
        "code": code, "message": f"{code} (stub)", "data": {}}})


def test_a_refused_verdict_is_not_committed():
    """Today's deployed daemon refuses allow with this envelope INSIDE a successful result."""
    stub = Stub(_ruled("hestia.witness_decision_kind"))
    try:
        r = record(stub.url, "allow")
        check("kind-refused-status", r.status == "refused", r)
        check("kind-refused-not-committed", not r.committed and r.entry_hash is None, r)
        check("kind-refused-detail-names-code", "witness_decision_kind" in r.detail, r)
    finally:
        stub.close()


def test_a_failed_append_is_not_committed():
    """The #1139 P1 defect as a falsifier: append_chain Err -> hestia.internal_error in a result."""
    stub = Stub(_ruled("hestia.internal_error"))
    try:
        r = record(stub.url, "warn")
        check("append-failed-not-committed", not r.committed and r.status == "refused", r)
        # The deployed recorder, same reply: it says True. That is the bug this contract closes,
        # pinned so the difference stays visible while both exist.
        legacy = Stub(_ruled("hestia.internal_error"))
        saved = m._discover_endpoint
        m._discover_endpoint = lambda: legacy.url
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # witness_decision_unified's fallback guesses ~/.hestia when HESTIA_HOME is unset;
                # point its log at a temp home so this measurement writes nothing real.
                prev = m._deny_fallback_path
                m._deny_fallback_path = lambda pid: pathlib.Path(tmp) / f"gate-denies-{pid}.jsonl"
                try:
                    said = m.witness_decision_unified(
                        None, plugin_id="codex", decision="warn", rule="r", tool_name="Write",
                        target="/tmp/x", session_id=None, verdict_available=True,
                        attempted_summary="Write -> /tmp/x")
                finally:
                    m._deny_fallback_path = prev
            check("legacy-recorder-still-reads-a-refusal-as-delivered", said is True,
                  "if this flips, the deployed recorder changed: stage A must not touch it")
        finally:
            m._discover_endpoint = saved
            legacy.close()
    finally:
        stub.close()


def test_a_join_key_refusal_is_not_committed():
    stub = Stub(_ruled("hestia.witness_decision_arg"))
    try:
        r = record(stub.url, "allow", action_id="not-a-uuid")
        check("arg-refused", r.status == "refused" and not r.committed, r)
    finally:
        stub.close()


# ---- not committed: the daemon answered nothing usable ---------------------------------------

def test_replies_without_a_ruling_or_a_receipt_are_ambiguous():
    cases = {
        "is-error-no-ruling": lambda rid, a: ok_reply(rid, {"text": "boom"}, is_error=True),
        "json-rpc-error": lambda rid, a: {"jsonrpc": "2.0", "id": rid,
                                          "error": {"code": -32603, "message": "internal"}},
        "empty-payload": lambda rid, a: ok_reply(rid, {}),
        "no-result": lambda rid, a: {"jsonrpc": "2.0", "id": rid},
        "unreadable-text": lambda rid, a: {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "not json"}]}},
    }
    for name, fn in cases.items():
        stub = Stub(fn)
        try:
            r = record(stub.url, "allow")
            check(f"{name}-ambiguous", r.status == "ambiguous" and not r.committed, r)
        finally:
            stub.close()


def test_a_missing_or_malformed_hash_is_not_a_receipt():
    for name, h in (("missing", None), ("empty", ""), ("short", "abc"), ("int", 123),
                    ("upper", "A" * 64), ("non-hex", "g" * 64), ("long", "a" * 65)):
        def fn(rid, a, h=h):
            body = receipt(a["decision"])
            if h is None:
                body.pop("witnessEntryHash")
            else:
                body["witnessEntryHash"] = h
            return ok_reply(rid, body)
        stub = Stub(fn)
        try:
            r = record(stub.url, "deny")
            check(f"hash-{name}-not-committed", not r.committed and r.status == "ambiguous", r)
        finally:
            stub.close()


def test_a_receipt_must_name_every_input_it_acted_on():
    aid = "11111111-2222-3333-4444-555555555555"
    cases = {
        # the daemon recorded a different verdict than was sent
        "decision-mismatch": (lambda rid, a: ok_reply(rid, receipt("deny")), {}),
        # an allow written as a policy_decision is the governance-window defect, not a receipt
        "allow-as-policy-decision": (
            lambda rid, a: ok_reply(rid, receipt("allow", event="policy_decision")), {}),
        # a daemon that ignores action_id (any build before this contract) echoes none
        "action-id-dropped": (lambda rid, a: ok_reply(rid, receipt("allow")),
                              {"action_id": aid}),
        "action-id-other": (
            lambda rid, a: ok_reply(rid, receipt("allow", action_id="99999999-2222-3333-4444-555555555555")),
            {"action_id": aid}),
        "correlation-key-dropped": (lambda rid, a: ok_reply(rid, receipt("allow")),
                                    {"correlation_key": "toolu_X"}),
    }
    for name, (fn, kw) in cases.items():
        stub = Stub(fn)
        try:
            r = record(stub.url, "allow", **kw)
            check(f"{name}-not-committed", not r.committed and r.status == "ambiguous", r)
        finally:
            stub.close()


def test_todays_daemon_reply_is_not_a_stage_a_receipt():
    """main's daemon answers deny with {witnessEntryHash, decision, updatedTrust} and no
    eventType. Stage A's recorder needs the daemon from the same PR (deploy order: daemon first,
    plan §C); against the old one it fails closed rather than claiming."""
    stub = Stub(lambda rid, a: ok_reply(rid, {"witnessEntryHash": H, "decision": a["decision"],
                                             "updatedTrust": {}}))
    try:
        r = record(stub.url, "deny")
        check("old-daemon-deny-not-committed", not r.committed and r.status == "ambiguous", r)
    finally:
        stub.close()


# ---- not committed: nobody to ask -----------------------------------------------------------

def test_unreachable_paths_never_claim_and_never_raise():
    r = record(closed_port_url(), "allow")
    check("refused-connection-unreachable", r.status == "unreachable" and not r.committed, r)
    saved = m._discover_endpoint
    m._discover_endpoint = lambda: None
    try:
        r = m.record_decision(None, plugin_id="codex", decision="deny", rule="r",
                              tool_name="Bash", target="ls", session_id=None,
                              verdict_available=True, attempted_summary="ls")
        check("no-endpoint-unreachable", r.status == "unreachable" and not r.committed, r)
    finally:
        m._discover_endpoint = saved


def test_an_exhausted_deadline_makes_no_request():
    stub = Stub()
    try:
        r = record(stub.url, "allow", deadline=time.monotonic() - 0.01)
        check("past-deadline-unreachable", r.status == "unreachable", r)
        check("past-deadline-no-wire", stub.calls == [], stub.calls)
    finally:
        stub.close()


def test_the_callers_deadline_is_the_bound():
    """The helper mints no time: a 0.4 s deadline against a 2 s daemon returns well before 2 s."""
    stub = Stub(delay=2.0)
    try:
        t0 = time.monotonic()
        r = record(stub.url, "warn", deadline=time.monotonic() + 0.4)
        took = time.monotonic() - t0
        check("slow-daemon-not-committed", not r.committed, r)
        check("slow-daemon-bounded-by-caller", took < 1.5, f"took {took:.2f}s")
    finally:
        stub.close()


def test_a_client_that_raises_is_contained():
    class Boom:
        def __init__(self, exc):
            self.exc = exc

        def call_tool(self, name, args):
            raise self.exc

    r = m.record_decision(Boom(RuntimeError("x")), plugin_id="codex", decision="allow",
                          rule="r", tool_name="Read", target="/x", session_id=None,
                          verdict_available=True, attempted_summary="Read /x")
    check("raising-client-ambiguous", r.status == "ambiguous" and not r.committed, r)
    r = m.record_decision(Boom(urllib.error.URLError("down")), plugin_id="codex",
                          decision="allow", rule="r", tool_name="Read", target="/x",
                          session_id=None, verdict_available=True, attempted_summary="Read /x")
    check("network-client-unreachable", r.status == "unreachable", r)


def test_a_non_verdict_is_refused_without_a_wire_call():
    stub = Stub()
    try:
        for bad in ("escalate", "no-verdict", "Allow", ""):
            r = record(stub.url, bad)
            check(f"non-verdict-{bad!r}-refused", r.status == "refused" and not r.committed, r)
        check("non-verdict-no-wire", stub.calls == [], stub.calls)
    finally:
        stub.close()


# ---- the fallback log: kept, never evidence, never at a guessed home -------------------------

_FALLBACK_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import hestia_gate_mechanism as m
r = m.record_decision(None, plugin_id="codex", decision="allow", rule="gate.allow",
                      tool_name="Write", target="/tmp/x", session_id=None,
                      verdict_available=True, attempted_summary="Write -> /tmp/x")
print(json.dumps({"status": r.status, "committed": r.committed,
                  "fallback_path": r.fallback_path}))
"""


def _probe(env):
    out = subprocess.run([sys.executable, "-c", _FALLBACK_PROBE, str(SHARED)], env=env,
                         capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_fallback_needs_an_explicit_home_and_is_never_evidence():
    # Built from nothing (no inherited environment): the probe can only reach the endpoint named
    # here, a closed port — never a daemon found through a real home.
    dead = closed_port_url()
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as fake_user:
        base = {"PATH": "/usr/bin:/bin", "HOME": fake_user, "HESTIA_ENDPOINT": dead}
        no_home = _probe(base)
        check("no-home-not-committed", no_home["committed"] is False, no_home)
        check("no-home-no-fallback", no_home["fallback_path"] is None, no_home)
        check("no-home-wrote-nothing-under-HOME",
              not any(pathlib.Path(fake_user).rglob("gate-decisions-*")), "guessed a home")
        with_home = _probe({**base, "HESTIA_HOME": home})
        want = str(pathlib.Path(home) / "telemetry" / "gate-decisions-codex.jsonl")
        check("home-fallback-path", with_home["fallback_path"] == want, with_home)
        check("home-still-not-committed", with_home["committed"] is False, with_home)
        rows = [json.loads(x) for x in open(want, encoding="utf-8")]
        check("fallback-row-names-why", rows and rows[-1].get("witness_status") == "unreachable",
              rows)


# ---- the join key is the core's rule, from the RAW event (C13) -------------------------------

def test_the_correlation_key_is_the_cores_rule_from_the_raw_event():
    claude = {"session_id": "s", "tool_name": "Bash", "tool_use_id": "toolu_01A",
              "tool_input": {"command": "ls"}}
    kimi = {"session_id": "s", "tool_name": "Shell", "tool_call_id": "call:9/x",
            "tool_input": {"command": "ls"}}
    gemini_raw = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "ls"},
                  "source_event": {"tool_name": "run_shell_command",
                                   "tool_input": {"command": "ls"}}}
    for name, ev in (("claude", claude), ("kimi", kimi), ("gemini", gemini_raw)):
        check(f"{name}-mechanism-key-is-cores", m.correlation_key(ev) == wc.correlation_key(ev))
    check("kimi-key-uses-tool_call_id", m.correlation_key(kimi) == "call_9_x",
          m.correlation_key(kimi))
    # What a NORMALIZED event would do: drop gemini's source_event and key on translated names.
    # The Post side keys on the harness's own names, so that key would never join.
    normalized = {k: v for k, v in gemini_raw.items() if k != "source_event"}
    check("gemini-normalized-key-differs", m.correlation_key(normalized)
          != m.correlation_key(gemini_raw), "the raw event is what makes the join")
    stub = Stub()
    try:
        key = m.correlation_key(gemini_raw)
        r = record(stub.url, "allow", correlation_key=key)
        check("gemini-key-committed", r.committed, r)
        check("gemini-key-on-the-wire-verbatim",
              stub.witness_calls()[0].get("correlation_key") == key, stub.calls)
    finally:
        stub.close()


# ---- stage A changes no seat ---------------------------------------------------------------

def test_stage_a_is_unwired():
    callers = []
    for root in ("plugins", "integrations", "hooks-gt"):
        for p in (REPO / root).rglob("*.py"):
            if p.parent.name == "_shared" or p.name.endswith("_test.py"):
                continue
            if "record_decision(" in p.read_text(encoding="utf-8", errors="replace"):
                callers.append(str(p.relative_to(REPO)))
    check("no-seat-calls-record_decision-yet", callers == [], callers)
    params = list(inspect.signature(m.witness_decision_unified).parameters)
    check("deployed-recorder-signature-unchanged", params == [
        "client_or_none", "plugin_id", "decision", "rule", "tool_name", "target",
        "session_id", "verdict_available", "attempted_summary"], params)


# ---- the real daemon (isolated only) ---------------------------------------------------------

def _real_endpoint():
    url = os.getenv("HESTIA_DECISION_CONTRACT_ENDPOINT")
    if not url:
        return None
    if f":{LIVE_PORT}" in url:
        raise SystemExit(f"refusing {url}: :{LIVE_PORT} is the live daemon. Use an isolated one.")
    return url


def test_against_an_isolated_real_daemon():
    url = _real_endpoint()
    if url is None:
        print("  (real-daemon arm skipped: HESTIA_DECISION_CONTRACT_ENDPOINT unset)")
        return
    RAN.append("real-daemon")
    pid = "decision-contract-test"
    saved = m._discover_endpoint
    saved_budget = m.TOTAL_BUDGET_MS
    m._discover_endpoint = lambda: url
    # A fresh DEBUG daemon's first society-safety round trip measured over the hook's 4 s
    # budget (timeout on the first act, the second inside it). That budget is the gate's
    # latency contract, not this witness's, so this arm widens it locally, restores it, and
    # prints each call's elapsed time instead of hiding it.
    m.TOTAL_BUDGET_MS = 30000
    try:
        def rec(decision, **kw):
            return m.record_decision(None, plugin_id=pid, decision=decision,
                                     rule="contract." + decision, tool_name="Bash",
                                     target=kw.pop("target", "ls"), session_id=None,
                                     verdict_available=True, attempted_summary="contract",
                                     deadline=time.monotonic() + 5.0, **kw)
        for d in ("allow", "warn", "deny"):
            r = rec(d, correlation_key=f"contract-{d}")
            check(f"real-{d}-committed", r.committed, r)
            check(f"real-{d}-event", r.event_type == m.DECISION_EVENT_TYPES[d], r)
        # The daemon itself refuses a fourth verdict (asked directly, past the local check).
        client = m._McpHttp(url, time.monotonic() + 5.0)
        client.initialize()
        client.initialized()
        kind, payload = wc._classify_reply(client.call_tool("hestia_witness_decision", {
            "plugin_id": pid, "decision": "escalate", "adjudicator": "plugin-gate:" + pid}))
        check("real-daemon-refuses-escalate",
              kind == "ruled" and payload.get("code") == "hestia.witness_decision_kind",
              (kind, payload))
        # The B sequence end to end: the society path rules the act, then the ONE recorder
        # witnesses the final verdict with the action id. A daemon-ruled warn/deny comes back as
        # the daemon's own row; an allow is a new policy_allow row.
        for command in ("rm -rf /home/user/data", "ls -la"):
            t0 = time.monotonic()
            v = m.query_society_safety(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                plugin_id=pid, host_agent="contract-test")
            print(f"  real daemon: society-safety {command!r} -> {v.kind} "
                  f"in {time.monotonic() - t0:.2f}s")
            check(f"real-ruled-{command}", v.decided and v.action_id, v)
            if not (v.decided and v.action_id):
                continue
            r = rec(v.kind, action_id=v.action_id, target=command)
            check(f"real-recorded-{command}", r.committed, r)
            if v.kind in ("warn", "deny"):
                check(f"real-one-row-{command}", r.deduplicated is True,
                      f"{v.kind} was already witnessed by query_policy: {r}")
            else:
                check(f"real-allow-appended-{command}", r.deduplicated is False, r)
    finally:
        m._discover_endpoint = saved
        m.TOTAL_BUDGET_MS = saved_budget


TESTS = [
    test_every_verdict_commits_on_a_receipt_that_names_it,
    test_sse_framed_receipt_commits,
    test_the_daemons_existing_row_is_a_committed_receipt,
    test_a_refused_verdict_is_not_committed,
    test_a_failed_append_is_not_committed,
    test_a_join_key_refusal_is_not_committed,
    test_replies_without_a_ruling_or_a_receipt_are_ambiguous,
    test_a_missing_or_malformed_hash_is_not_a_receipt,
    test_a_receipt_must_name_every_input_it_acted_on,
    test_todays_daemon_reply_is_not_a_stage_a_receipt,
    test_unreachable_paths_never_claim_and_never_raise,
    test_an_exhausted_deadline_makes_no_request,
    test_the_callers_deadline_is_the_bound,
    test_a_client_that_raises_is_contained,
    test_a_non_verdict_is_refused_without_a_wire_call,
    test_the_fallback_needs_an_explicit_home_and_is_never_evidence,
    test_the_correlation_key_is_the_cores_rule_from_the_raw_event,
    test_stage_a_is_unwired,
    test_against_an_isolated_real_daemon,
]


def teardown_module(module=None):
    """pytest's channel for the accumulators (tools/ci_selfexec_test.py): a failure recorded in
    FAILS must fail a pytest run too, not only the bare `python3` run CI uses."""
    assert not FAILS, FAILS
    assert isinstance(RAN, list)


if __name__ == "__main__":
    for t in TESTS:
        try:
            t()
        except Exception as e:  # noqa: BLE001 — a crashing test is a failing test, never a skip
            FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}")
    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    extra = f" (+ {', '.join(RAN)})" if RAN else ""
    print(f"PASS: {len(TESTS)} decision-witness contract tests{extra}")
