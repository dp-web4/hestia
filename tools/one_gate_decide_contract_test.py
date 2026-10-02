#!/usr/bin/env python3
"""Contract suite for the common orchestrator `decide()` — one-gate stage B.

docs/one-gate-convergence-plan.md §3. Two arms, both against a loopback stub daemon that speaks
the daemon's real wire shape (MCP streamable-HTTP JSON-RPC; every tool reply, error or not, is a
successful `result` carrying `structuredContent` and a JSON text block — handler.rs `call_tool`),
so nothing here touches a live witness chain:

1. CONTRACT (in-process). The plan's B acceptance, each as a falsifier:
   - the REAL `record_decision` against a refusing stub turns a consequential permit into
     `gate.evidence_uncommitted`, in every rollout mode (C11; GPT's #1140 HOLD);
   - `correlation_key(raw)` from a kimi / gemini / codex raw event reaches `begin_action`,
     `record_decision` and the claim's invocation key, unchanged (C13);
   - `hestia_single_gate.py` writes no action cache and opens no MCP client (AST, not grep);
   - ONE deadline: a cold daemon (4.4 s first society check, measured in stage A) is a
     `society.unreachable` deny inside 3 s + slack, and the final record still commits from the
     reserved tail; no phase starts after the deadline;
   - a superseded invocation is denied in every mode (#1169); daemon-ruled verdicts come back as
     the daemon's own row; closure-write approval lifts only the closure bar;
   - every test seam asserts it was reached (C12b).

2. PARITY (subprocesses). Each seat's CURRENT gate (plugins/<seat>/hooks/...) and `decide()` are
   driven with the SAME harness-native event — the four real shapes, modelled on recorded events
   (claude-code PreToolUse with `tool_use_id`; codex `Bash`/`apply_patch` with `call_` ids and
   `turn_id`; kimi `path`-keyed inputs with `tool_call_id`; gemini `BeforeTool` with native tool
   names) — under the same stub policy. Every cell where the verdict CLASS differs must be named
   in DECLARED_DIVERGENCES with its justification, and every declared divergence must still
   occur: a divergence can be neither hidden nor stale. `--report` prints the table as markdown.

The REAL-DAEMON arm runs only when pointed at an isolated daemon, never the live one:
    HESTIA_DECIDE_CONTRACT_ENDPOINT=http://127.0.0.1:7799/mcp python3 tools/one_gate_decide_contract_test.py
An endpoint on :7711 (the live daemon's port) is refused.

Run: python3 tools/one_gate_decide_contract_test.py [--report] [--only contract|parity]
"""
from __future__ import annotations

import ast
import dataclasses
import http.server
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

REPO = pathlib.Path(os.getenv("HESTIA_CONTRACT_REPO") or pathlib.Path(__file__).resolve().parents[1])
PLUGINS = REPO / "plugins"
SHARED = PLUGINS / "_shared"
LIVE_PORT = 7711
#: Staging only: {"module_name": "/path/to/file.py"} loaded under the canonical module name in
#: place of the SHARED copy (the test's module-dir seam; unset in the repo and in CI).
OVERLAY = json.loads(os.getenv("HESTIA_CONTRACT_OVERLAY") or "{}")

FAILS: list = []
RAN: list = []


def check(name, ok, detail=""):
    if not ok:
        FAILS.append(f"{name}{': ' + str(detail)[:600] if detail else ''}")


def load_engine():
    """The shared engine as the gate imports it, with any staging overlay first."""
    if str(SHARED) not in sys.path:
        sys.path.insert(0, str(SHARED))
    for name in ("hestia_gate_mechanism", "hestia_single_gate"):
        path = OVERLAY.get(name)
        if path and name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
    import hestia_gate_mechanism as m  # noqa: E402
    import hestia_single_gate as g  # noqa: E402
    import hestia_witness_core as wc  # noqa: E402
    return m, g, wc


def gate_source_path() -> pathlib.Path:
    return pathlib.Path(OVERLAY.get("hestia_single_gate") or SHARED / "hestia_single_gate.py")


# ── the stub daemon ───────────────────────────────────────────────────────────────────────────

def _ok(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "structuredContent": payload, "isError": False}}


def _err(rid, code, msg="stub", data=None):
    return _ok(rid, {"_hestia_error": {"code": code, "message": msg, "data": data or {}}})


class Policy:
    """What the stub answers. `query(begin_args) -> allow|warn|deny`; the rest are switches."""

    def __init__(self, query=None, *, superseded=False, claim="escalate", witness="receipt",
                 delays=None, snapshot=True):
        self.query = query or (lambda a: "allow")
        self.superseded = superseded
        self.claim = claim                 # escalate | approve
        self.witness = witness             # receipt | refuse-allow | refuse-all | old
        self.delays = delays or {}         # {tool name: seconds, "*": seconds}
        self.snapshot = snapshot           # False: the snapshot connect is refused


class Stub:
    def __init__(self, policy: Policy | None = None):
        self.policy = policy or Policy()
        self.calls: list = []              # (tool, args, plugin_id-of-session)
        self.sessions: dict = {}
        self.decided: dict = {}            # action_id -> decision
        self.lock = threading.Lock()
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                method = body.get("method")
                if isinstance(method, str) and method.startswith("notifications/"):
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    out = {"jsonrpc": "2.0", "id": body.get("id"), "result": {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "serverInfo": {"name": "decide-contract-stub", "version": "0"}}}
                else:
                    params = body.get("params") or {}
                    out = stub.tool(body.get("id"), params.get("name"), params.get("arguments") or {})
                data = json.dumps(out).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("mcp-session-id", "stub-mcp")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass   # the client's deadline ran out first: the intended outcome of a delay

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def named(self, tool):
        return [(a, p) for t, a, p in self.calls if t == tool]

    def tool(self, rid, name, args):
        p = self.policy
        delay = p.delays.get(name, p.delays.get("*", 0))
        if delay:
            time.sleep(delay)
        with self.lock:
            plugin = self.sessions.get(args.get("session_id"))
            self.calls.append((name, args, plugin if name != "hestia_connect" else args.get("plugin_id")))
        if name == "hestia_connect":
            if not p.snapshot and args.get("instance_name") == "gate-policy-fetch":
                return _err(rid, "hestia.connect_refused")
            sid = f"sess-{uuid.uuid4().hex[:12]}"
            with self.lock:
                self.sessions[sid] = args.get("plugin_id")
            return _ok(rid, {"sessionId": sid, "plugin_id": args.get("plugin_id"),
                             "role": args.get("role") or "role:constellation:member"})
        if name == "hestia_operating_law":
            return _ok(rid, {"identity": {"role": "role:constellation:member"},
                             "law_hash": "0" * 64, "operator_grant": None})
        if name == "hestia_scope_status":
            return _ok(rid, {"live_grants": [], "standing_grants": [], "society_floor": [],
                             "generation": 1, "snapshot_expires_at": int(time.time()) + 3600})
        if name == "hestia_begin_action":
            if p.superseded:
                return _err(rid, "hestia.invocation_superseded", "superseded (stub)",
                            {"escalation_id": "stub-esc-superseded"})
            aid = str(uuid.uuid4())
            with self.lock:
                self.decided[aid] = p.query(args)
            return _ok(rid, {"actionId": aid})
        if name == "hestia_query_policy":
            verdict = self.decided.get(args.get("action_id"), "allow")
            return _ok(rid, {"status": "decided", "decision": verdict, "enforced": True,
                             "ruleName": "stub.policy", "reason": f"stub rules {verdict}"})
        if name == "hestia_gate_escalation_claim":
            if p.claim == "approve":
                return _ok(rid, {"claimed": True, "permits_write": True, "decided_by": "stub-human",
                                 "decided_via": "stub"})
            return _ok(rid, {"claimed": False, "permits_write": False,
                             "escalation_id": "stub-esc-" + uuid.uuid4().hex[:8],
                             "how_to_decide": "stub: nobody decides"})
        if name == "hestia_request_witness":
            return _ok(rid, {"ok": True, "witnessEntryHash": "c" * 64})
        if name == "hestia_witness_decision":
            d = args.get("decision")
            if p.witness == "refuse-all" or (p.witness == "refuse-allow" and d == "allow"):
                return _err(rid, "hestia.witness_decision_kind", "stub refuses")
            if p.witness == "old":
                return _ok(rid, {"witnessEntryHash": "a" * 64, "decision": d, "updatedTrust": {}})
            aid = args.get("action_id")
            existing = aid is not None and self.decided.get(aid) == d and d in ("warn", "deny")
            return _ok(rid, {
                "witnessEntryHash": ("e" if existing else "b") * 64,
                "eventType": "policy_allow" if d == "allow" else "policy_decision",
                "decision": d, "recorded": "existing" if existing else "appended",
                "charged": d != "allow" and not existing, "actionId": aid,
                "correlationKey": args.get("correlation_key"), "updatedTrust": None})
        return _ok(rid, {"ok": True})


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/mcp"


# ── seats: the four harness shapes, profiles, and the test-local to_event adapters ────────────

SEATS = ("claude-code", "codex", "kimi", "gemini")
SEAT_SHIM = {"claude-code": "claude-code/hooks/pre_tool_use.py", "codex": "codex/hooks/pre_tool_use.py",
             "kimi": "kimi/hooks/pre_tool_use.py", "gemini": "gemini/hooks/before_tool.py"}
SEAT_MEMBER = {"claude-code": "claude-code", "codex": "codex", "kimi": "kimi-code", "gemini": "gemini"}
SEAT_HOME = {"claude-code": "~/.claude", "codex": "~/.codex", "kimi": "~/.kimi-code", "gemini": "~/.gemini"}
SEAT_MODE_ENV = {"codex": "HESTIA_CODEX_GATE_MODE", "kimi": "HESTIA_KIMI_GATE_MODE",
                 "gemini": "HESTIA_GEMINI_GATE_MODE"}
SEAT_LAUNCH_ENV = {"claude-code": "", "codex": "HESTIA_CODEX_LAUNCH_CWD",
                   "kimi": "HESTIA_KIMI_LAUNCH_CWD", "gemini": "HESTIA_GEMINI_LAUNCH_CWD"}
# gemini's native vocabulary -> lineage (the shim's own LINEAGE_TOOL/LINEAGE_ARG tables).
GEMINI_LINEAGE_TOOL = {"run_shell_command": "Shell", "write_file": "Write", "replace": "Edit",
                       "read_file": "Read", "read_many_files": "Read", "glob": "Glob",
                       "search_file_content": "Grep", "list_directory": "Read",
                       "web_fetch": "WebFetch", "google_web_search": "WebSearch"}
GEMINI_LINEAGE_ARG = {"absolute_path": "file_path", "dir_path": "path"}


def profile_for(g, seat, home: pathlib.Path):
    return g.GateProfile(
        member_id=SEAT_MEMBER[seat],
        identity_path=str(home / "identity.json"),
        home_markers=(SEAT_HOME[seat],),
        launch_cwd_env=SEAT_LAUNCH_ENV[seat],
        host_agent=SEAT_MEMBER[seat],
        client_name=f"hestia-{SEAT_MEMBER[seat]}-gate",
        gate_path=str(PLUGINS / SEAT_SHIM[seat]),
        observe_dir=str(home / "observe"),
        declares_review_door=seat != "gemini")


def to_event(g, seat, raw: dict):
    """Pure syntax translation (what each stage-C shim's `to_event` will be). `raw` rides along
    untouched: the gate computes the correlation key from it."""
    tool = raw.get("tool_name") or "?"
    ti = raw.get("tool_input") if isinstance(raw.get("tool_input"), dict) else {}
    if seat == "gemini":
        mcp = raw.get("mcp_context") if isinstance(raw.get("mcp_context"), dict) else None
        ti = {GEMINI_LINEAGE_ARG.get(k, k): v for k, v in ti.items()}
        if mcp and isinstance(mcp.get("server_name"), str):
            tool = f"mcp__{mcp['server_name']}__{mcp.get('tool_name') or '?'}"
            ti["_hestia_mcp_context"] = mcp
        else:
            tool = GEMINI_LINEAGE_TOOL.get(str(tool).lower(), tool)
    return g.GateEvent(tool=tool, tool_input=ti, cwd=raw.get("cwd"),
                       session_id=raw.get("session_id"),
                       tool_use_id=raw.get("tool_use_id") or raw.get("tool_call_id"), raw=raw)


def native_event(seat, act_tool, act_input, cwd, n):
    """The act in this harness's native hook event, shaped on recorded events (see docstring)."""
    if seat == "claude-code":
        return {"session_id": "9261dc9a-0000-4000-8000-00000000c1a0",
                "transcript_path": "/home/probe/.claude/projects/x/9261dc9a.jsonl", "cwd": cwd,
                "permission_mode": "default", "hook_event_name": "PreToolUse",
                "tool_name": act_tool, "tool_input": act_input, "tool_use_id": f"toolu_01Contract{n:04d}"}
    if seat == "codex":
        if act_tool in ("Edit", "Write"):
            path = act_input["file_path"]
            verb = "Update" if act_tool == "Edit" else "Add"
            tool, ti = "apply_patch", {"command": f"*** Begin Patch\n*** {verb} File: {path}\n+x\n*** End Patch\n"}
        elif act_tool == "Read":
            tool, ti = "Bash", {"command": f"cat {act_input['file_path']}"}
        else:
            tool, ti = act_tool, act_input
        return {"session_id": "019f94e0-0000-7000-8000-00000000c0de", "turn_id": f"019f94e0-{n:04d}",
                "transcript_path": "/home/probe/.codex/sessions/rollout.jsonl", "cwd": cwd,
                "hook_event_name": "PreToolUse", "model": "gpt-probe", "permission_mode": "default",
                "tool_name": tool, "tool_input": ti, "tool_use_id": f"call_Contract{n:04d}"}
    if seat == "kimi":
        ti = dict(act_input)
        if "file_path" in ti:
            ti["path"] = ti.pop("file_path")
        if act_tool == "Bash":
            ti.setdefault("description", "contract probe")
        return {"hook_event_name": "PreToolUse", "session_id": "session_00000000-c0de-4000-8000-000000000001",
                "cwd": cwd, "tool_name": act_tool, "tool_input": ti, "tool_call_id": f"tool_Contract{n:04d}"}
    gtool = {"Read": "read_file", "Edit": "replace", "Write": "write_file",
             "Bash": "run_shell_command"}.get(act_tool, act_tool)
    return {"session_id": "gemini-contract-session", "transcript_path": "/home/probe/.gemini/tmp/chat.json",
            "cwd": cwd, "hook_event_name": "BeforeTool", "timestamp": "2026-10-01T00:00:00Z",
            "tool_name": gtool, "tool_input": dict(act_input)}


# ── contract arm (in-process) ─────────────────────────────────────────────────────────────────

class _Env:
    """Point the mechanism at a stub (or a dead port) for one test; restore after."""

    def __init__(self, m, url, home: pathlib.Path):
        self.m, self.url, self.home = m, url, home

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in ("HESTIA_ENDPOINT", "HESTIA_HOME", "HESTIA_WORKSPACE")}
        os.environ["HESTIA_ENDPOINT"] = self.url
        os.environ["HESTIA_HOME"] = str(self.home)
        os.environ["HESTIA_WORKSPACE"] = str(REPO.parent)
        self.m._POLICY_SNAPSHOT_CACHE.clear()
        self.saved_disc = self.m._discover_endpoint
        self.m._discover_endpoint = lambda: self.url
        return self

    def __exit__(self, *exc):
        self.m._discover_endpoint = self.saved_disc
        self.m._POLICY_SNAPSHOT_CACHE.clear()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _decide(g, seat, act_tool, act_input, home, n=1, rollout="enforce"):
    raw = native_event(seat, act_tool, act_input, str(REPO), n)
    return g.decide(to_event(g, seat, raw), profile_for(g, seat, home), rollout=rollout), raw


IN_SCOPE_EDIT = ("Edit", {"file_path": "{REPO}/core/src/server/state.rs", "old_string": "a", "new_string": "b"})


def _act(act):
    tool, ti = act
    return tool, json.loads(json.dumps(ti).replace("{REPO}", str(REPO)))


def test_c11_the_real_recorder_turns_an_uncommitted_permit_into_a_denial(m, g, wc, home):
    """GPT's #1140 HOLD as a falsifier: the stub refuses `allow` exactly as main's daemon does."""
    for mode in ("enforce", "warn"):
        for witness in ("refuse-allow", "old"):
            stub = Stub(Policy(witness=witness))
            try:
                with _Env(m, stub.url, home):
                    d, _ = _decide(g, "codex", *_act(IN_SCOPE_EDIT), home, rollout=mode)
                tag = f"c11-{mode}-{witness}"
                check(f"{tag}-denied", d.decision == "deny" and d.rule == "gate.evidence_uncommitted", d)
                check(f"{tag}-names-superseded", d.supersedes_uncommitted == "allow", d)
                check(f"{tag}-not-conduct", d.verdict_available is False and d.anomaly, d)
                sent = [a.get("decision") for a, _ in stub.named("hestia_witness_decision")]
                check(f"{tag}-recorded-permit-then-denial", sent == ["allow", "deny"], sent)
                second = stub.named("hestia_witness_decision")[-1][0]
                check(f"{tag}-denial-carries-rule", second.get("rule_id") == "gate.evidence_uncommitted", second)
                check(f"{tag}-denial-names-what-it-replaced",
                      "supersedes uncommitted allow" in (second.get("attempted") or ""), second)
            finally:
                stub.close()
    # A READ whose record does not commit keeps the ratified posture and says so (C11 text).
    stub = Stub(Policy(witness="refuse-allow"))
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "claude-code", "Read", {"file_path": str(REPO / "README.md")}, home)
        check("c11-read-stays-allowed", d.decision == "allow" and not d.evidence_committed and d.anomaly, d)
    finally:
        stub.close()


def test_the_key_from_the_raw_event_reaches_every_join(m, g, wc, home):
    cases = (("kimi", "Bash", {"command": "ls"}), ("gemini", "Bash", {"command": "ls"}),
             ("codex", "Bash", {"command": "ls"}), ("claude-code", "Bash", {"command": "ls"}))
    saved = wc.ACTIONS_DIR
    for seat, tool, ti in cases:
        stub = Stub()
        with tempfile.TemporaryDirectory() as actions:
            wc.ACTIONS_DIR = pathlib.Path(actions)
            try:
                with _Env(m, stub.url, home):
                    d, raw = _decide(g, seat, tool, ti, home, n=7)
                key = wc.correlation_key(raw)
                check(f"{seat}-allow", d.decision == "allow" and d.evidence_committed, d)
                check(f"{seat}-decision-carries-key", d.correlation_key == key, (d.correlation_key, key))
                begin = [a for a, _ in stub.named("hestia_begin_action")]
                check(f"{seat}-key-at-begin", [a.get("correlation_key") for a in begin] == [key], begin)
                rec = [a for a, _ in stub.named("hestia_witness_decision")]
                check(f"{seat}-key-at-record", [a.get("correlation_key") for a in rec] == [key], rec)
                check(f"{seat}-action-joined", rec and rec[0].get("action_id") == d.action_id, rec)
                check(f"{seat}-cache-written-by-the-mechanism",
                      (pathlib.Path(actions) / f"{key}.json").is_file(), sorted(os.listdir(actions)))
            finally:
                wc.ACTIONS_DIR = saved
                stub.close()
    check("kimi-key-is-tool_call_id", wc.correlation_key(native_event("kimi", "Bash", {}, "/", 7))
          == "tool_Contract0007")
    graw = native_event("gemini", "Bash", {"command": "ls"}, "/", 7)
    check("gemini-key-is-content-of-native-event", wc.correlation_key(graw).startswith("content-"))
    # The claim's invocation key is the same key (#1169).
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            d, raw = _decide(g, "kimi", "Write", {"file_path": str(SHARED / "hestia_gate_core.py"),
                                                  "content": "x"}, home, n=9)
        claims = [a for a, _ in stub.named("hestia_gate_escalation_claim")]
        check("closure-write-denied", d.decision == "deny" and d.rule == "gate.self_access" and d.innate, d)
        check("closure-claim-invocation-key", claims and claims[0].get("invocation_key")
              == wc.correlation_key(raw), claims)
        check("closure-claim-declares-hard-stop", claims and claims[0].get("supersession") == "hard_stop", claims)
        check("closure-escalation-surfaced", bool(d.escalation_id), d)
    finally:
        stub.close()


def test_the_gate_owns_no_cache_no_client_and_one_recorder(m, g, wc, home):
    src = gate_source_path().read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
               for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    for banned in ("urllib", "socket", "http", "requests", "subprocess"):
        check(f"no-import-{banned}", not any(i and i.split(".")[0] == banned for i in imports), imports)
    for banned in ("_McpHttp", "cache_authorized_action", "ACTIONS_DIR", "witness_decision_unified",
                   "call_tool", "globals"):
        check(f"no-use-of-{banned}", banned not in names and banned not in attrs)
    check("no-actions-dir-literal", "/tmp/hestia-actions" not in src and "hestia-actions" not in src)
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "open"]
    check("no-file-writes", not opens, len(opens))
    recorders = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "record_decision"]
    check("exactly-one-record_decision-call-site", len(recorders) == 1, len(recorders))
    soc_refs = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                and n.attr == "query_society_safety"]
    check("one-society-reference", len(soc_refs) == 1, len(soc_refs))
    bounded = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "id", None) == "_bounded" and len(n.args) >= 2
               and getattr(n.args[1], "attr", None) == "query_society_safety"]
    check("society-call-is-bounded", len(bounded) == 1, len(bounded))
    kws = {k.arg for k in bounded[0].keywords} if bounded else set()
    check("society-call-passes-the-raw-key", "correlation_key" in kws, kws)
    # Every mechanism call that can block runs under _bounded (record_decision takes the
    # deadline itself, stage A).
    for name in ("fetch_policy_snapshot", "claim_self_write", "witness_gate_self", "tally_scope"):
        direct = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == name]
        check(f"{name}-never-called-unbounded", not direct, len(direct))
    check("api-version", g.GATE_API_VERSION == "decide/1")
    check("deadline-under-shortest-clamp", 0 < g.GATE_DEADLINE_SECONDS < 4.0, g.GATE_DEADLINE_SECONDS)


def test_one_deadline_bounds_the_whole_invocation(m, g, wc, home):
    """Stage A measured a cold DEBUG daemon at 4.4 s for its first society-safety round trip.
    Under the 3 s invocation deadline that act is denied `society.unreachable` — explicit, not a
    hang — and the denial still commits from the reserved tail."""
    stub = Stub(Policy(delays={"hestia_begin_action": 4.4}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
            took = time.monotonic() - t0
        print(f"  cold-daemon decide: {d.decision} {d.rule} in {took:.2f}s "
              f"(deadline {g.GATE_DEADLINE_SECONDS}s, record {d.receipt_status})")
        check("cold-daemon-denied-unreachable", d.decision == "deny" and d.rule == "society.unreachable", d)
        check("cold-daemon-bounded", took < g.GATE_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("cold-daemon-denial-committed-from-the-reserve", d.evidence_committed, d)
    finally:
        stub.close()
    # Every exchange slow: nothing may run past the deadline, whatever the phase.
    stub = Stub(Policy(delays={"*": 0.9}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "kimi", *_act(IN_SCOPE_EDIT), home)
            took = time.monotonic() - t0
        check("slow-daemon-bounded", took < g.GATE_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("slow-daemon-not-a-permit", d.decision == "deny", d)
    finally:
        stub.close()
    # The seams run inside the bounded worker (C12b: each spy must be reached), and B passes
    # the deployed mechanism no `deadline=` it does not have (stage C adds it).
    seen = {}
    orig_q, orig_f = m.query_society_safety, m.fetch_policy_snapshot

    def spy_q(*a, **kw):
        seen["q"] = (threading.current_thread().name, sorted(kw))
        return orig_q(*a, **kw)

    def spy_f(*a, **kw):
        seen["f"] = (threading.current_thread().name, sorted(kw))
        return orig_f(*a, **kw)

    stub = Stub()
    m.query_society_safety, m.fetch_policy_snapshot = spy_q, spy_f
    try:
        with _Env(m, stub.url, home):
            _decide(g, "codex", "Bash", {"command": "ls"}, home)
        for k in ("q", "f"):
            check(f"spy-{k}-reached", k in seen, seen)
            name, kws = seen.get(k, ("", []))
            check(f"spy-{k}-ran-bounded", name == "hestia-decide-bounded", name)
            check(f"spy-{k}-no-deadline-kw-in-B", "deadline" not in kws, kws)
    finally:
        m.query_society_safety, m.fetch_policy_snapshot = orig_q, orig_f
        stub.close()
    # A snapshot fetch that would retry past the deadline (two 4 s attempts on a dead port in
    # the deployed helper) is abandoned at the phase bound, and the write is degraded-denied.
    stub = Stub(Policy(delays={"hestia_operating_law": 5.0}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "claude-code", *_act(IN_SCOPE_EDIT), home)
            took = time.monotonic() - t0
        check("slow-snapshot-bounded", took < g.GATE_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("slow-snapshot-degrades", d.decision == "deny" and d.rule == "gate.degraded", d)
    finally:
        stub.close()


def test_b_leaves_the_deployed_mechanism_untouched(m, g, wc, home):
    """dp, 2026-10-01: B must not modify the mechanism (sovereign bar). Its budgets are the
    deployed ones; decide() bounds them from outside until stage C threads `deadline=`."""
    import inspect
    for fn in (m.query_society_safety, m._fetch_policy_snapshot_once, m.gate_self_call):
        check(f"{fn.__name__}-has-no-deadline-in-B", "deadline" not in inspect.signature(fn).parameters)
    check("record_decision-takes-the-deadline", "deadline" in inspect.signature(m.record_decision).parameters)


def test_superseded_is_denied_in_every_mode(m, g, wc, home):
    for mode in ("enforce", "warn"):
        stub = Stub(Policy(superseded=True))
        try:
            with _Env(m, stub.url, home):
                d, _ = _decide(g, "kimi", "Bash", {"command": "touch x"}, home, rollout=mode)
            check(f"superseded-{mode}", d.decision == "deny" and d.rule == "invocation.superseded"
                  and d.innate, d)
        finally:
            stub.close()


def test_daemon_verdicts_and_the_warn_rollout(m, g, wc, home):
    deny_rm = Policy(query=lambda a: "deny" if "rm -rf" in json.dumps(a) else "allow")
    stub = Stub(deny_rm)
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "codex", "Bash", {"command": "rm -rf build"}, home)
            check("daemon-deny", d.decision == "deny" and d.rule == "society.safety" and d.action_id, d)
            check("daemon-deny-is-its-own-row", d.evidence_committed, d)
            rec = stub.named("hestia_witness_decision")[-1][0]
            check("daemon-deny-recorded-with-action", rec.get("action_id") == d.action_id, rec)
            d, _ = _decide(g, "codex", "Bash", {"command": "rm -rf build"}, home, rollout="warn")
            check("warn-rollout-society-deny-warns", d.decision == "warn" and d.action_id, d)
            check("warn-rollout-records-warn", stub.named("hestia_witness_decision")[-1][0].get("decision")
                  == "warn")
            d, _ = _decide(g, "kimi", "Write", {"file_path": "/etc/decide-probe", "content": "x"}, home,
                           rollout="warn")
            check("warn-rollout-scope-warns", d.decision == "warn" and d.rule.startswith("mrh."), d)
            d, _ = _decide(g, "kimi", "Write", {"file_path": "/etc/decide-probe", "content": "x"}, home)
            check("enforce-scope-denies", d.decision == "deny" and d.rule.startswith("mrh."), d)
            d, _ = _decide(g, "kimi", "Bash", {"command": "cat ~/.ssh/id_rsa"}, home, rollout="warn")
            check("warn-rollout-innate-still-denies", d.decision == "deny" and d.rule == "egress.secret", d)
            d, _ = _decide(g, "gemini", "WebFetch", {"url": "https://x.example/?q=.env"}, home)
            check("egress-precheck-web", d.decision == "deny" and d.rule == "egress.secret", d)
    finally:
        stub.close()
    stub = Stub(Policy(query=lambda a: "warn"))
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "claude-code", "Bash", {"command": "touch x"}, home)
        check("daemon-warn", d.decision == "warn" and d.rule == "society.safety.warn" and d.evidence_committed, d)
    finally:
        stub.close()


def test_degraded_posture(m, g, wc, home):
    dead = closed_port_url()
    with _Env(m, dead, home):
        d, _ = _decide(g, "claude-code", "Read", {"file_path": str(REPO / "README.md")}, home)
        check("degraded-read-allowed", d.decision == "allow" and d.rule == "gate.degraded.allow_read"
              and not d.verdict_available and not d.evidence_committed, d)
        d, _ = _decide(g, "claude-code", *_act(IN_SCOPE_EDIT), home)
        check("degraded-write-denied", d.decision == "deny" and d.rule == "gate.degraded"
              and not d.verdict_available, d)
        d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
        check("degraded-read-shell-still-asks-the-governor",
              d.decision == "deny" and d.rule == "society.unreachable", d)
        d, _ = _decide(g, "kimi", "Write", {"file_path": str(REPO / "x"), "content": "x"}, home, rollout="warn")
        check("warn-rollout-down-write-is-c11-denied", d.decision == "deny"
              and d.rule == "gate.evidence_uncommitted", d)
    # Snapshot refused but the governor up: degraded law, then the governor still decides.
    stub = Stub(Policy(snapshot=False))
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
        check("snapshot-down-governor-up", d.decision == "allow" and d.evidence_committed, d)
    finally:
        stub.close()


def test_closure_approval_lifts_only_the_closure_bar(m, g, wc, home):
    stub = Stub(Policy(claim="approve"))
    try:
        with _Env(m, stub.url, home):
            target = str(SHARED / "hestia_gate_core.py")
            d, _ = _decide(g, "claude-code", "Edit", {"file_path": target, "old_string": "a",
                                                       "new_string": "b"}, home)
            check("approved-then-ordinary-law-allows", d.decision == "allow", d)
            check("approved-notice", any("APPROVED" in n for n in d.notices), d.notices)
            check("approved-reached-society", len(stub.named("hestia_begin_action")) == 1, stub.calls)
            d, _ = _decide(g, "claude-code", "Write", {"file_path": str(SHARED / ".env"), "content": "x"}, home)
            check("approved-still-meets-innate-law", d.decision == "deny" and d.rule == "egress.secret", d)
    finally:
        stub.close()
    # A closure READ is allowed and witnessed as its own class.
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "kimi", "Read", {"file_path": str(SHARED / "hestia_gate_core.py")}, home)
        check("closure-read-allowed", d.decision == "allow", d)
        wit = [a for a, _ in stub.named("hestia_request_witness")]
        check("closure-read-witnessed", any(a.get("event_type") == "gate_self_read" for a in wit), wit)
    finally:
        stub.close()


def test_an_internal_error_fails_closed_through_the_one_recorder(m, g, wc, home):
    reached = []
    orig = g.normalized_event

    def boom(ev):
        reached.append(ev)
        raise RuntimeError("injected")

    stub = Stub()
    g.normalized_event = boom
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
            check("seam-reached", len(reached) == 1, reached)
            check("internal-error-denies", d.decision == "deny" and d.rule == "gate.internal_error"
                  and d.anomaly and not d.verdict_available, d)
            check("internal-error-recorded", d.evidence_committed, d)
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home, rollout="warn")
            check("internal-error-warn-rollout", d.decision == "warn" and d.evidence_committed, d)
        d = g.decide("not an event", profile_for(g, "codex", home))
        check("bad-input-denies", d.decision == "deny" and d.rule == "gate.internal_error", d)
    finally:
        g.normalized_event = orig
        stub.close()


def test_stage_b_is_unwired(m, g, wc, home):
    callers = []
    for root in ("plugins", "integrations", "hooks-gt"):
        base = REPO / root
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            # The certified template names the gate by design (stage C copies it); it is not a seat.
            if p.parent.name in ("_shared", "_template") or p.name.endswith("_test.py"):
                continue
            if "hestia_single_gate" in p.read_text(encoding="utf-8", errors="replace"):
                callers.append(str(p.relative_to(REPO)))
    check("no-seat-imports-the-common-gate-yet", callers == [], callers)
    manifest = (SHARED / "RUNTIME_MANIFEST.txt").read_text(encoding="utf-8")
    check("not-in-runtime-manifest-until-C", "hestia_single_gate" not in manifest)


#: Tests that measure the deadline run at the real GATE_DEADLINE_SECONDS. The others pin
#: behaviour, not latency: they run with a relaxed deadline so a loaded box (a transient
#: multi-second stall was measured here under `cargo -j2`, the #423 jitter class) cannot turn a
#: behaviour check into a timing flake. The real deadline is what the parity arm runs at.
RELAXED_DEADLINE_SECONDS = 15.0
DEADLINE_TESTS = {"test_one_deadline_bounds_the_whole_invocation",
                  "test_the_gate_owns_no_cache_no_client_and_one_recorder",
                  # The real daemon is where the cold-start caveat lives: it MUST run at 3 s.
                  "test_against_an_isolated_real_daemon"}

CONTRACT_TESTS = [
    test_c11_the_real_recorder_turns_an_uncommitted_permit_into_a_denial,
    test_the_key_from_the_raw_event_reaches_every_join,
    test_the_gate_owns_no_cache_no_client_and_one_recorder,
    test_one_deadline_bounds_the_whole_invocation,
    test_b_leaves_the_deployed_mechanism_untouched,
    test_superseded_is_denied_in_every_mode,
    test_daemon_verdicts_and_the_warn_rollout,
    test_degraded_posture,
    test_closure_approval_lifts_only_the_closure_bar,
    test_an_internal_error_fails_closed_through_the_one_recorder,
    test_stage_b_is_unwired,
]


# ── parity arm (subprocesses) ─────────────────────────────────────────────────────────────────

PROBE_HOME = "/home/gate-parity-probe"   # text the gates classify; never a path touched

# (case id, act tool, act input, stub policy name, rollout). {REPO}/{HOME}/{SELF} substituted.
PARITY_CASES = [
    ("read-in-repo", "Read", {"file_path": "{REPO}/README.md"}, "allow", "enforce"),
    ("edit-in-repo", "Edit", {"file_path": "{REPO}/core/src/server/state.rs", "old_string": "a",
                              "new_string": "b"}, "allow", "enforce"),
    ("bash-ls", "Bash", {"command": "ls {REPO}"}, "allow", "enforce"),
    ("closure-write-core", "Edit", {"file_path": "{REPO}/plugins/_shared/hestia_gate_core.py",
                                    "old_string": "a", "new_string": "b"}, "allow", "enforce"),
    ("closure-write-self-hook", "Edit", {"file_path": "{REPO}/plugins/{SELF}/hooks/{HOOK}",
                                         "old_string": "a", "new_string": "b"}, "allow", "enforce"),
    ("closure-read-cat", "Bash", {"command": "cat {REPO}/plugins/_shared/hestia_gate_core.py"},
     "allow", "enforce"),
    ("settings-write", "Edit", {"file_path": "{HOME}/.claude/settings.json", "old_string": "a",
                                "new_string": "b"}, "allow", "enforce"),
    ("secret-read-env", "Read", {"file_path": "{HOME}/.config/x/.env"}, "allow", "enforce"),
    ("secret-cat-id_rsa", "Bash", {"command": "cat {HOME}/.ssh/id_rsa"}, "allow", "enforce"),
    ("scope-write-etc", "Write", {"file_path": "/etc/decide-probe", "content": "x"}, "allow", "enforce"),
    ("daemon-denies-rm", "Bash", {"command": "rm -rf {REPO}/build"}, "deny-rm", "enforce"),
    ("daemon-warns", "Bash", {"command": "touch {REPO}/x"}, "warn", "enforce"),
    ("daemon-denies-read", "Read", {"file_path": "{REPO}/README.md"}, "deny-all", "enforce"),
    ("superseded", "Bash", {"command": "touch {REPO}/x"}, "superseded", "enforce"),
    ("down-read", "Read", {"file_path": "{REPO}/README.md"}, "down", "enforce"),
    ("down-edit", "Edit", {"file_path": "{REPO}/core/src/server/state.rs", "old_string": "a",
                           "new_string": "b"}, "down", "enforce"),
    ("down-bash-ls", "Bash", {"command": "ls {REPO}"}, "down", "enforce"),
    ("witness-refuses-allow", "Edit", {"file_path": "{REPO}/core/src/server/state.rs",
                                       "old_string": "a", "new_string": "b"}, "refuse-allow", "enforce"),
    ("warn-scope-write-etc", "Write", {"file_path": "/etc/decide-probe", "content": "x"}, "allow", "warn"),
    ("warn-daemon-denies-rm", "Bash", {"command": "rm -rf {REPO}/build"}, "deny-rm", "warn"),
    ("warn-down-edit", "Edit", {"file_path": "{REPO}/core/src/server/state.rs", "old_string": "a",
                                "new_string": "b"}, "down", "warn"),
]

POLICIES = {
    "allow": lambda: Policy(),
    "deny-rm": lambda: Policy(query=lambda a: "deny" if "rm -rf" in json.dumps(a) else "allow"),
    "deny-all": lambda: Policy(query=lambda a: "deny"),
    "warn": lambda: Policy(query=lambda a: "warn"),
    "superseded": lambda: Policy(superseded=True),
    "refuse-allow": lambda: Policy(witness="refuse-allow"),
    "down": None,
}

_ALL = ("claude-code", "codex", "kimi", "gemini")
#: Every cell where the verdict CLASS (allow / warn / deny) of decide() differs from the seat's
#: current gate. Each entry is a decision for dp, not an accident; the test fails if one is
#: missing from this table or no longer occurs.
DECLARED_DIVERGENCES = {
    **{(s, "witness-refuses-allow"): (
        "C11 (finding 5): a consequential permit whose decision record does not commit becomes "
        "gate.evidence_uncommitted. No seat records allows today, so none can see this.")
       for s in _ALL},
    **{(s, "warn-down-edit"): (
        "C11 in warn-rollout (finding 5): with the daemon down the warn-rollout used to let a write "
        "through unwitnessed; C11 admits no class, so it is denied in every mode. Behaviour change "
        "for dp.") for s in ("codex", "kimi", "gemini")},
    ("claude-code", "down-read"): (
        "Finding 3, LOOSENING, needs dp's ruling: claude-code asks the daemon about reads, so a "
        "degraded Read is a no-verdict deny today. decide() takes the ratified degraded posture "
        "(deny writes, allow reads), as kimi and codex already do."),
    ("claude-code", "daemon-denies-read"): (
        "Finding 3: read-class acts no longer reach daemon law on claude-code (the ratified "
        "READ_CLASS skip every other seat already has). Local innate egress still binds reads."),
    **{(s, "daemon-warns"): (
        "Legibility, not reach: the act is permitted either way. kimi and codex read only "
        "`verdict.allow`, and gemini's spawned governor exit code, so a daemon WARN reached those "
        "members as a silent allow; claude-code alone rendered it. decide() surfaces it on every "
        "seat (C10 capability parity).") for s in ("codex", "kimi", "gemini")},
}


def _classify_old(seat, rc, out, err):
    text = (err or "") + "\n" + (out or "")
    try:
        payload = json.loads((out or "").strip() or "null")
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("decision") == "deny":
        return "deny", text
    if rc == 0:
        return ("warn" if ("hestia: warn" in text or "would-deny" in text) else "allow"), text
    return "deny", text


def _old_rule(text):
    import re
    for pat in (r"governance-closure-[a-z-]+", r"\[gate-self(?:-access)?\]", r"gate\.self_access",
                r"egress\.secret", r"mrh\.(?:path|command|repo)", r"\[scope\]", r"\[degraded\]",
                r"gate\.degraded", r"\[fail-closed\]", r"\[safety\]", r"invocation-superseded",
                r"\[stub\.policy\]", r"hestia: warn \[[a-z.-]+\]"):
        mm = re.search(pat, text)
        if mm:
            return mm.group(0)
    return ""


def _render(value, mapping):
    s = json.dumps(value)
    for k, v in mapping.items():
        s = s.replace(k, v)
    return json.loads(s)


def _seat_home(root: pathlib.Path, seat: str, endpoint: str) -> pathlib.Path:
    home = root / f"{seat}-{abs(hash(endpoint)) % 10**8}"
    if home.is_dir():
        return home
    (home / "seats").mkdir(parents=True)
    values = {"HESTIA_HOME": str(home), "HESTIA_SHARED_DIR": str(SHARED),
              "HESTIA_WORKSPACE": str(REPO.parent), "HESTIA_ENDPOINT": endpoint}
    for member in {SEAT_MEMBER[seat], "claude-code"}:   # gemini's Gate 2 spawns claude-code's gate
        body = ["# rendered from the vault by hestia (decide-contract fixture)", f"# member: {member}"]
        body += [f"{k}={values[k]}" for k in sorted(values)]
        (home / "seats" / f"{member}.env").write_text("\n".join(body) + "\n", encoding="utf-8")
    (home / "identity.json").write_text(json.dumps({"plugin_id": SEAT_MEMBER[seat],
                                                    "role": "role:constellation:member",
                                                    "mrh": {"in_scope": []}}), encoding="utf-8")
    return home


def _seat_env(seat, home, endpoint, rollout):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({"HOME": str(home), "HESTIA_HOME": str(home), "HESTIA_SHARED_DIR": str(SHARED),
                "HESTIA_WORKSPACE": str(REPO.parent), "HESTIA_ENDPOINT": endpoint,
                "HESTIA_STATE_DIR": str(home / "state"), "HESTIA_OBSERVE_DIR": str(home / "observe"),
                "HESTIA_KIMI_IDENTITY": str(home / "identity.json"),
                "HESTIA_CODEX_IDENTITY": str(home / "identity.json"),
                "HESTIA_GEMINI_IDENTITY": str(home / "identity.json"),
                "HESTIA_KIMI_LAUNCH_CWD": str(REPO), "HESTIA_CODEX_LAUNCH_CWD": str(REPO),
                "HESTIA_GEMINI_LAUNCH_CWD": str(REPO),
                "HESTIA_SOCIETY_GATE": str(PLUGINS / SEAT_SHIM["claude-code"]),
                "PYTHONDONTWRITEBYTECODE": "1"})
    if seat in SEAT_MODE_ENV:
        env[SEAT_MODE_ENV[seat]] = rollout
    if OVERLAY:
        env["HESTIA_CONTRACT_OVERLAY"] = json.dumps(OVERLAY)
    env["HESTIA_CONTRACT_REPO"] = str(REPO)
    return env


def decide_probe() -> int:
    """`--decide-probe`: one decide() call in a fresh process (no cached module state), event on
    stdin as {seat, raw, rollout}; prints the GateDecision as JSON."""
    req = json.loads(sys.stdin.read())
    m, g, wc = load_engine()
    home = pathlib.Path(os.environ["HESTIA_HOME"])
    wc.ACTIONS_DIR = home / "actions"   # keep this arm's cache writes inside the fixture
    t0 = time.monotonic()
    d = g.decide(to_event(g, req["seat"], req["raw"]), profile_for(g, req["seat"], home),
                 rollout=req["rollout"])
    out = dataclasses.asdict(d)
    out["elapsed"] = round(time.monotonic() - t0, 3)
    print(json.dumps(out, default=str))
    return 0


def _probe_pair(stub, pol, seat, raw, env, rollout):
    """One seat's current gate and decide() on the same event, under the same stub policy."""
    if pol != "down":
        stub.policy = POLICIES[pol]()
    mark = len(stub.calls)
    old = subprocess.run([sys.executable, str(PLUGINS / SEAT_SHIM[seat])],
                         input=json.dumps(raw), capture_output=True, text=True,
                         cwd=str(REPO), env=env, timeout=60)
    old_v, old_text = _classify_old(seat, old.returncode, old.stdout, old.stderr)
    old_asked = sorted({p for t, a, p in stub.calls[mark:] if t == "hestia_begin_action"})
    if pol != "down":
        stub.policy = POLICIES[pol]()
    mark = len(stub.calls)
    new = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()), "--decide-probe"],
                         input=json.dumps({"seat": seat, "raw": raw, "rollout": rollout}),
                         capture_output=True, text=True, cwd=str(REPO), env=env, timeout=60)
    try:
        nd = json.loads(new.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        nd = {"decision": "CRASH", "rule": new.stderr.strip()[-300:]}
    new_asked = sorted({p for t, a, p in stub.calls[mark:] if t == "hestia_begin_action"})
    return {"old": old_v, "old_rule": _old_rule(old_text), "new": nd.get("decision"),
            "new_rule": nd.get("rule"), "old_asked_as": old_asked, "new_asked_as": new_asked,
            "elapsed": nd.get("elapsed"), "old_text": old_text.strip()[-400:]}


def run_parity(report: bool = False):
    rows = []
    with tempfile.TemporaryDirectory(prefix="decide-parity-") as tmp:
        root = pathlib.Path(tmp)
        stub = Stub()
        dead = closed_port_url()
        try:
            for n, (case, tool, tin, pol, rollout) in enumerate(PARITY_CASES, start=1):
                for seat in SEATS:
                    hook = "before_tool.py" if seat == "gemini" else "pre_tool_use.py"
                    # The SAME input means the seat's own posture: claude-code has no rollout knob
                    # and always enforces, so both arms run it at enforce.
                    seat_rollout = rollout if seat in SEAT_MODE_ENV else "enforce"
                    act = _render(tin, {"{REPO}": str(REPO), "{HOME}": PROBE_HOME,
                                        "{SELF}": seat, "{HOOK}": hook})
                    raw = native_event(seat, tool, act, str(REPO), n)
                    endpoint = dead if pol == "down" else stub.url
                    if pol != "down":
                        stub.policy = POLICIES[pol]()
                    home = _seat_home(root, seat, endpoint)
                    env = _seat_env(seat, home, endpoint, seat_rollout)
                    cell = _probe_pair(stub, pol, seat, raw, env, seat_rollout)
                    retried = False
                    if cell["old"] != cell["new"] and (seat, case) not in DECLARED_DIVERGENCES:
                        # A loaded box can stall a healthy loopback round trip past the
                        # deadline (#423 class). Retry the PAIR once; a real divergence repeats.
                        cell = _probe_pair(stub, pol, seat, raw, env, seat_rollout)
                        retried = True
                    rows.append({"case": case, "seat": seat, "retried": retried, **cell})
        finally:
            stub.close()
    found = {(r["seat"], r["case"]) for r in rows if r["old"] != r["new"]}
    undeclared = sorted(found - set(DECLARED_DIVERGENCES))
    stale = sorted(set(DECLARED_DIVERGENCES) - found)
    check("parity-no-undeclared-divergence", not undeclared,
          [(s, c, next((r["old"], r["old_rule"], r["new"], r["new_rule"], r["old_text"][-200:])
                       for r in rows if (r["seat"], r["case"]) == (s, c))) for s, c in undeclared])
    check("parity-no-stale-declaration", not stale, stale)
    check("parity-decide-never-crashed", not any(r["new"] == "CRASH" for r in rows),
          [r for r in rows if r["new"] == "CRASH"][:2])
    # Finding 1: gemini's governor asked the daemon AS claude-code; decide() asks as gemini.
    gem = [r for r in rows if r["seat"] == "gemini" and r["old_asked_as"]]
    check("finding-1-gemini-old-asked-as-claude-code",
          gem and all(r["old_asked_as"] == ["claude-code"] for r in gem), gem[:2])
    check("finding-1-gemini-decide-asks-as-gemini",
          all(r["new_asked_as"] in ([], ["gemini"]) for r in rows if r["seat"] == "gemini"))
    if report:
        print_report(rows)
    RAN.append(f"parity {len(PARITY_CASES)}x{len(SEATS)}")
    return rows


def print_report(rows):
    print("\n| case | " + " | ".join(SEATS) + " |")
    print("|---|" + "---|" * len(SEATS))
    for case, *_ in PARITY_CASES:
        cells = []
        for seat in SEATS:
            r = next(x for x in rows if x["case"] == case and x["seat"] == seat)
            same = r["old"] == r["new"]
            cell = (f"{r['old']} → {r['new']}" + ("" if same else " **DIVERGES**")
                    + f" <sub>{r['old_rule'] or '·'} / {r['new_rule'] or '·'}</sub>")
            cells.append(cell)
        print(f"| {case} | " + " | ".join(cells) + " |")
    print("\nsociety asked as (old → decide): " + "; ".join(
        f"{r['seat']}:{r['case']} {r['old_asked_as']}→{r['new_asked_as']}"
        for r in rows if r["old_asked_as"] != r["new_asked_as"]))
    again = [f"{r['seat']}:{r['case']}" for r in rows if r.get("retried")]
    print(f"\nretried once after a diverging first probe: {again or 'none'}")
    slow = max((r["elapsed"] or 0) for r in rows)
    print(f"\nslowest decide(): {slow:.2f}s")


# ── the real daemon (isolated only) ───────────────────────────────────────────────────────────

def test_against_an_isolated_real_daemon(m, g, wc, home):
    url = os.getenv("HESTIA_DECIDE_CONTRACT_ENDPOINT")
    if not url:
        print("  (real-daemon arm skipped: HESTIA_DECIDE_CONTRACT_ENDPOINT unset)")
        return
    if f":{LIVE_PORT}" in url:
        raise SystemExit(f"refusing {url}: :{LIVE_PORT} is the live daemon. Use an isolated one.")
    RAN.append("real-daemon")
    prof = g.GateProfile(member_id="decide-contract-test", identity_path=str(home / "identity.json"),
                         host_agent="decide-contract-test", observe_dir="")

    def run(tool, ti, n):
        raw = {"session_id": "decide-contract", "tool_name": tool, "tool_input": ti,
               "tool_use_id": f"toolu_decide_contract_{n}_{uuid.uuid4().hex[:8]}", "cwd": str(REPO)}
        t0 = time.monotonic()
        d = g.decide(g.GateEvent(tool=tool, tool_input=ti, cwd=str(REPO), session_id="decide-contract",
                                 tool_use_id=raw["tool_use_id"], raw=raw), prof)
        took = time.monotonic() - t0
        print(f"  real daemon: {tool} {json.dumps(ti)[:60]} -> {d.decision} {d.rule} "
              f"record={d.receipt_status} in {took:.2f}s")
        check(f"real-{n}-bounded", took < g.GATE_DEADLINE_SECONDS + 0.5, f"{took:.2f}s")
        return d

    with _Env(m, url, home):
        # The FIRST consequential act may meet a cold daemon (4.4 s measured on a DEBUG build):
        # it is then an explicit society.unreachable deny inside the deadline, never a hang.
        first = run("Bash", {"command": "ls -la"}, 1)
        check("real-first-is-allow-or-explicit-cold-deny",
              (first.decision == "allow" and first.evidence_committed)
              or (first.decision == "deny" and first.rule == "society.unreachable"), first)
        d = run("Bash", {"command": "ls -la"}, 2)
        check("real-allow-committed-as-policy_allow", d.decision == "allow" and d.evidence_committed
              and d.action_id, d)
        d = run("Bash", {"command": "rm -rf /home/user/data"}, 3)
        check("real-daemon-deny", d.decision == "deny" and d.rule == "society.safety", d)
        check("real-daemon-deny-one-row", d.evidence_committed, d)
        d = run("Read", {"file_path": str(REPO / "README.md")}, 4)
        check("real-read-allowed-and-recorded", d.decision == "allow" and d.evidence_committed, d)


def teardown_module(module=None):
    """pytest's channel for the accumulators (tools/ci_selfexec_test.py): a failure recorded in
    FAILS must fail a pytest run too, not only the bare `python3` run CI uses."""
    assert not FAILS, FAILS
    assert isinstance(RAN, list)


def main(argv) -> int:
    if "--decide-probe" in argv:
        return decide_probe()
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    m, g, wc = load_engine()
    with tempfile.TemporaryDirectory(prefix="decide-contract-home-") as h:
        home = pathlib.Path(h)
        (home / "identity.json").write_text(json.dumps({"role": "role:constellation:member"}))
        os.environ.setdefault("HESTIA_KIMI_LAUNCH_CWD", str(REPO))
        os.environ.setdefault("HESTIA_CODEX_LAUNCH_CWD", str(REPO))
        os.environ.setdefault("HESTIA_GEMINI_LAUNCH_CWD", str(REPO))
        tests = [] if only == "parity" else CONTRACT_TESTS + [test_against_an_isolated_real_daemon]
        real_deadline = g.GATE_DEADLINE_SECONDS
        for t in tests:
            g.GATE_DEADLINE_SECONDS = (real_deadline if t.__name__ in DEADLINE_TESTS
                                       else RELAXED_DEADLINE_SECONDS)
            try:
                t(m, g, wc, home)
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001 — a crashing test is a failing test, never a skip
                import traceback
                FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
            finally:
                g.GATE_DEADLINE_SECONDS = real_deadline
        if only != "contract":
            try:
                run_parity(report="--report" in argv)
            except Exception as e:  # noqa: BLE001
                import traceback
                FAILS.append(f"parity raised {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        return 1
    extra = f" (+ {', '.join(RAN)})" if RAN else ""
    print(f"PASS: {len(tests)} decide() contract tests{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
