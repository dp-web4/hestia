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
    for name in ("hestia_witness_core", "hestia_gate_core", "hestia_governance_closure",
                 "hestia_gate_mechanism", "hestia_single_gate"):
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
                 delays=None, snapshot=True, cold_connect=0.0):
        self.query = query or (lambda a: "allow")
        self.superseded = superseded
        self.claim = claim                 # escalate | approve
        self.witness = witness             # receipt | refuse-allow | refuse-all | old
        self.delays = delays or {}         # {tool name: seconds, "*": seconds}
        self.snapshot = snapshot           # False: the snapshot connect is refused
        self.cold_connect = cold_connect   # seconds the FIRST connect per member costs (measured)


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
        if name == "hestia_connect" and p.cold_connect:
            with self.lock:
                first = args.get("plugin_id") not in getattr(self, "_warm", set())
                self._warm = getattr(self, "_warm", set()) | {args.get("plugin_id")}
            if first:
                time.sleep(p.cold_connect)
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
#: Staging only: {"seat": "/path/to/shim.py"} in place of the repo's shim (the shim twin of
#: HESTIA_CONTRACT_OVERLAY; unset in the repo and in CI).
SHIM_OVERRIDE = json.loads(os.getenv("HESTIA_CONTRACT_SHIMS") or "{}")


def shim_path(seat) -> pathlib.Path:
    return pathlib.Path(SHIM_OVERRIDE.get(seat) or PLUGINS / SEAT_SHIM[seat])


def _shim_module(seat):
    """The seat's shim, imported (its HARNESS and PROFILE are data the tests read)."""
    spec = importlib.util.spec_from_file_location(f"contract_shim_{seat.replace('-', '_')}",
                                                  shim_path(seat))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
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
        # `_no_verdict` / `_snapshot_unavailable` write telemetry to DEFAULT_HESTIA_HOME (from
        # HOME at import), not HESTIA_HOME: pin it, or a run without an isolated HOME writes
        # into the live ~/.hestia/telemetry (stage A's real arm leaked one row that way).
        self.saved_home = self.m.DEFAULT_HESTIA_HOME
        self.m.DEFAULT_HESTIA_HOME = self.home
        return self

    def __exit__(self, *exc):
        self.m._discover_endpoint = self.saved_disc
        self.m.DEFAULT_HESTIA_HOME = self.saved_home
        self.m._POLICY_SNAPSHOT_CACHE.clear()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _decide(g, seat, act_tool, act_input, home, n=1, rollout="enforce", **deadline_kw):
    raw = native_event(seat, act_tool, act_input, str(REPO), n)
    return g.decide(to_event(g, seat, raw), profile_for(g, seat, home), rollout=rollout,
                    **deadline_kw), raw


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
    # A PERMITTED read whose RECORD does not commit keeps C11's read posture and says so (C11 text).
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
    # Stage C: the gate READS its seat's harness registration (harness_bound), so open() may
    # appear — in a literal read mode only. Any other open is a private file write.
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "open"]
    def _mode(call):
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            return call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                return kw.value.value
        return "r" if len(call.args) < 2 and not any(k.arg == "mode" for k in call.keywords) else None
    writes = [ast.unparse(n) for n in opens if _mode(n) not in ("r", "rb")]
    check("no-file-writes", not writes, writes)
    check("registration-reads-are-reads", len(opens) >= 1, len(opens))
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
    # Stage C: every bounded mechanism call ALSO hands the mechanism the deadline itself, so no
    # request starts after it (`_bounded` is the belt).
    mech_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", None) == "_bounded" and len(n.args) >= 2
                  and isinstance(n.args[1], ast.Attribute)
                  and getattr(n.args[1].value, "id", None) == "mechanism"]
    check("mechanism-calls-found", len(mech_calls) >= 6, len(mech_calls))
    for call in mech_calls:
        check(f"{call.args[1].attr}-gets-the-deadline",
              "deadline" in {k.arg for k in call.keywords}, ast.unparse(call)[:120])
    check("api-version", g.GATE_API_VERSION == "decide/2")
    for gone in ("GATE_DEADLINE_SECONDS", "MIN_HARNESS_TIMEOUT_SECONDS", "HARNESS_MARGIN_SECONDS"):
        check(f"no-law-level-harness-timeout-{gone}", not hasattr(g, gone))
    check("remedies-moved-to-the-core", not hasattr(g, "GATE_REMEDIES") and all(
        r in core_remedies(g) for r in ("invocation.superseded", "gate.evidence_uncommitted",
                                        "gate.internal_error", "gate.harness_timeout_unknown")))


def core_remedies(g):
    return g.core.REMEDIES


def test_one_deadline_bounds_the_whole_invocation(m, g, wc, home):
    """The deadline is the CALLER's (the shim's: harness timeout minus margin). decide() honours a
    short one and a long one, falls back to DEFAULT_DEADLINE_SECONDS, and fails closed — inside
    the deadline, with its denial recorded from the reserve — when the daemon is slower."""
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
        check("default-deadline-applies", d.budget_seconds == g.DEFAULT_DEADLINE_SECONDS, d.budget_seconds)
        check("default-is-the-deployed-4s-x-2", g.DEFAULT_DEADLINE_SECONDS == 8.0, g.DEFAULT_DEADLINE_SECONDS)
    finally:
        stub.close()
    # LONG caller deadline: a never-seen member's cold first connect (measured 4.6 s) completes.
    stub = Stub(Policy(cold_connect=4.6))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home, budget_seconds=12.0)
            took = time.monotonic() - t0
        print(f"  cold-member decide (12 s caller budget): {d.decision} {d.rule} in {took:.2f}s")
        check("long-deadline-honoured", d.budget_seconds == 12.0, d.budget_seconds)
        check("cold-member-connect-absorbed", d.decision == "allow" and d.evidence_committed, d)
        check("cold-member-bounded", took < 12.4, f"{took:.2f}s")
    finally:
        stub.close()
    # SHORT caller deadline (an absolute one): the same cold member is a no-verdict deny inside it.
    stub = Stub(Policy(cold_connect=4.6))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home, deadline=time.monotonic() + 2.0)
            took = time.monotonic() - t0
        print(f"  cold-member decide (2 s caller deadline): {d.decision} {d.rule} in {took:.2f}s "
              f"(record {d.receipt_status})")
        check("short-deadline-honoured", abs(d.budget_seconds - 2.0) < 0.05, d.budget_seconds)
        check("short-deadline-fails-closed", d.decision == "deny" and d.rule in
              ("society.unreachable", "gate.degraded"), d)
        check("short-deadline-bounded", took < 2.4, f"{took:.2f}s")
    finally:
        stub.close()
    # A daemon slower than the act can wait for (begin 4 s, poll 4 s): the society phase runs to
    # the phase deadline (the mechanism takes it itself since stage C), the poll is cut there, and
    # the result is a recorded no-verdict deny from the reserve, inside the deadline.
    stub = Stub(Policy(delays={"hestia_begin_action": 4.0, "hestia_query_policy": 4.0}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
            took = time.monotonic() - t0
        print(f"  over-budget decide: {d.decision} {d.rule} in {took:.2f}s (record {d.receipt_status})")
        check("over-budget-denied-unreachable", d.decision == "deny" and d.rule == "society.unreachable", d)
        check("over-budget-bounded", took < g.DEFAULT_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("over-budget-denial-committed-from-the-reserve", d.evidence_committed, d)
    finally:
        stub.close()
    # Every exchange slow: nothing may run past the deadline, whatever the phase.
    stub = Stub(Policy(delays={"*": 2.5}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "kimi", *_act(IN_SCOPE_EDIT), home)
            took = time.monotonic() - t0
        check("slow-daemon-bounded", took < g.DEFAULT_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("slow-daemon-not-a-permit", d.decision == "deny", d)
    finally:
        stub.close()
    # The seams run inside the bounded worker (C12b: each spy must be reached), and since stage
    # C each is handed the phase deadline itself: a value inside the invocation's deadline.
    seen = {}
    orig_q, orig_f = m.query_society_safety, m.fetch_policy_snapshot

    def spy_q(*a, **kw):
        seen["q"] = (threading.current_thread().name, sorted(kw), kw.get("deadline"), time.monotonic())
        return orig_q(*a, **kw)

    def spy_f(*a, **kw):
        seen["f"] = (threading.current_thread().name, sorted(kw), kw.get("deadline"), time.monotonic())
        return orig_f(*a, **kw)

    stub = Stub()
    m.query_society_safety, m.fetch_policy_snapshot = spy_q, spy_f
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            _decide(g, "codex", "Bash", {"command": "ls"}, home, budget_seconds=6.0)
        for k in ("q", "f"):
            check(f"spy-{k}-reached", k in seen, seen)
            name, kws, dl, at = seen.get(k, ("", [], None, 0.0))
            check(f"spy-{k}-ran-bounded", name == "hestia-decide-bounded", name)
            check(f"spy-{k}-deadline-threaded", isinstance(dl, float) and at < dl <= t0 + 6.0
                  - g.WITNESS_RESERVE_SECONDS + 0.05, (dl, at, t0))
    finally:
        m.query_society_safety, m.fetch_policy_snapshot = orig_q, orig_f
        stub.close()
    # A snapshot fetch that would retry past the deadline (two 4 s attempts on a dead port in
    # the deployed helper) is abandoned at the phase bound, and the write is degraded-denied.
    stub = Stub(Policy(delays={"hestia_connect": 3.6, "hestia_operating_law": 3.6}))
    try:
        with _Env(m, stub.url, home):
            t0 = time.monotonic()
            d, _ = _decide(g, "claude-code", *_act(IN_SCOPE_EDIT), home)
            took = time.monotonic() - t0
        check("slow-snapshot-bounded", took < g.DEFAULT_DEADLINE_SECONDS + 0.4, f"{took:.2f}s")
        check("slow-snapshot-degrades", d.decision == "deny" and d.rule == "gate.degraded", d)
    finally:
        stub.close()


def test_reads_meet_the_same_local_law_on_every_seat(m, g, wc, home):
    """dp 2026-10-01, ALIGN UPWARD: reads meet the strictest seat's posture on every seat. A
    credential read is denied with the daemon up AND down; an out-of-scope read is denied; reads
    go to daemon law; with no policy snapshot EVERY read is denied (gate.degraded)."""
    cred = CRED_PATH
    outside = "/etc/hostname"   # exists: codex reads by `cat`, and command scope votes on existence
    stub = Stub()
    try:
        for seat in SEATS:
            with _Env(m, stub.url, home):
                d, _ = _decide(g, seat, "Read", {"file_path": cred}, home)
                check(f"{seat}-credential-read-up", d.decision == "deny" and d.rule == "egress.secret", d)
                d, _ = _decide(g, seat, "Read", {"file_path": outside}, home)
                if seat == "codex":
                    # LAW GAP, pinned (reported to dp, not fixed in B): codex reads by `cat`, and the
                    # core's command scope judges only tokens UNDER the workspace, so a shell read of
                    # an absolute path outside it is unscoped — on every seat, today and in decide().
                    check(f"{seat}-out-of-scope-SHELL-read-up-is-the-known-law-gap",
                          d.decision == "allow", d)
                else:
                    check(f"{seat}-out-of-scope-read-up", d.decision == "deny" and d.rule.startswith("mrh."), d)
            with _Env(m, closed_port_url(), home):
                d, _ = _decide(g, seat, "Read", {"file_path": cred}, home)
                check(f"{seat}-credential-read-down", d.decision == "deny" and d.rule == "egress.secret", d)
                d, _ = _decide(g, seat, "Read", {"file_path": outside}, home)
                check(f"{seat}-out-of-scope-read-down-denied", d.decision == "deny"
                      and d.rule == "gate.degraded" and not d.verdict_available, d)
                d, _ = _decide(g, seat, "Read", {"file_path": str(REPO / "README.md")}, home)
                check(f"{seat}-in-scope-read-down-denied", d.decision == "deny"
                      and d.rule == "gate.degraded" and not d.verdict_available, d)
        # Reads go to daemon law on every seat: a daemon that refuses a read is obeyed.
        stub.policy = Policy(query=lambda a: "deny")
        for seat in SEATS:
            with _Env(m, stub.url, home):
                d, _ = _decide(g, seat, "Read", {"file_path": str(REPO / "README.md")}, home)
                check(f"{seat}-read-reaches-daemon-law", d.decision == "deny"
                      and d.rule == "society.safety", d)
    finally:
        stub.close()


def test_c_threads_the_deadline_through_the_mechanism(m, g, wc, home):
    """Stage C (plan §4 0b): every helper takes `deadline=`, backward-compatible (None is the
    deployed behaviour), and NO request starts after it. The 5 s per-request cap applies only
    without a caller deadline: a slow-but-alive cold connect inside a longer deadline answers."""
    import inspect
    for fn in (m.query_society_safety, m.fetch_policy_snapshot, m._fetch_policy_snapshot_once,
               m.gate_self_call, m.witness_gate_self, m.claim_self_write, m.tally_scope,
               m.emit_attestation, m.record_decision):
        p = inspect.signature(fn).parameters.get("deadline")
        check(f"{fn.__name__}-takes-a-deadline", p is not None and p.default is None, p)
    check("the-old-refusal-recorder-is-gone", not hasattr(m, "witness_decision_unified"))
    # An exhausted deadline: no request is made at all, by any helper.
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            past = time.monotonic() - 0.01
            v = m.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "ls"}},
                                       plugin_id="codex", host_agent="codex", deadline=past)
            check("exhausted-society-is-a-no-verdict", not v.allow and not v.decided
                  and v.cause == "timeout", v)
            check("exhausted-snapshot-is-none", m.fetch_policy_snapshot(
                "codex", deadline=past, use_cache=False) is None)
            check("exhausted-gate-self-is-none", m.gate_self_call(
                "hestia_request_witness", {}, plugin_id="codex", role="r", client_name="c",
                deadline=past) is None)
            r = m.record_decision(None, plugin_id="codex", decision="deny", rule="x", tool_name="Bash",
                                  target=None, session_id=None, verdict_available=True,
                                  attempted_summary="", deadline=past)
            check("exhausted-record-is-unreachable", r.status == "unreachable", r)
        check("exhausted-deadline-made-no-request", stub.calls == [], stub.calls)
    finally:
        stub.close()
    # A snapshot deadline shorter than the retry pause skips the retry (and its sleep).
    with _Env(m, closed_port_url(), home):
        t0 = time.monotonic()
        snap = m.fetch_policy_snapshot("codex", deadline=time.monotonic() + 0.2, use_cache=False)
        took = time.monotonic() - t0
    check("snapshot-retry-skipped-inside-a-short-deadline", snap is None and took < 0.3, took)
    # The cap: a 5.5 s first connect (slower than REQUEST_TIMEOUT_S) inside a 9 s deadline answers;
    # the same connect with no caller deadline is the deployed no-verdict.
    stub = Stub(Policy(cold_connect=5.5))
    try:
        with _Env(m, stub.url, home):
            v = m.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "ls"}},
                                       plugin_id="codex", host_agent="codex",
                                       deadline=time.monotonic() + 9.0)
        check("caller-deadline-lifts-the-5s-cap", v.allow and v.decided, v)
    finally:
        stub.close()
    stub = Stub(Policy(cold_connect=5.5))
    try:
        with _Env(m, stub.url, home):
            v = m.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "ls"}},
                                       plugin_id="kimi-code", host_agent="kimi-code")
        check("no-deadline-keeps-the-deployed-cap", not v.decided, v)
    finally:
        stub.close()


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
        check("degraded-read-denied", d.decision == "deny" and d.rule == "gate.degraded"
              and not d.verdict_available, d)
        d, _ = _decide(g, "claude-code", *_act(IN_SCOPE_EDIT), home)
        check("degraded-write-denied", d.decision == "deny" and d.rule == "gate.degraded"
              and not d.verdict_available, d)
        d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
        check("degraded-read-shell-denied", d.decision == "deny" and d.rule == "gate.degraded", d)
        d, _ = _decide(g, "kimi", "Write", {"file_path": str(REPO / "x"), "content": "x"}, home, rollout="warn")
        # No snapshot is a hard stop before any permit exists, so C11 is never reached.
        check("warn-rollout-down-write-is-degraded-denied", d.decision == "deny"
              and d.rule == "gate.degraded" and d.innate and not d.verdict_available, d)
    # Snapshot refused but the governor up: still no permit — without the snapshot the gate
    # cannot certify scope, so the act is denied without asking the governor.
    stub = Stub(Policy(snapshot=False))
    try:
        with _Env(m, stub.url, home):
            d, _ = _decide(g, "codex", "Bash", {"command": "ls"}, home)
        check("snapshot-down-governor-up-still-denied", d.decision == "deny" and d.rule == "gate.degraded", d)
        check("snapshot-down-governor-not-asked", stub.named("hestia_begin_action") == [], stub.calls)
    finally:
        stub.close()


def test_no_snapshot_is_a_hard_stop_in_every_rollout_on_every_seat(m, g, wc, home):
    """dp's ruling, "align upward; no snapshot -> no read", INDEPENDENT of rollout (GPT's
    re-review of 57bcd10: warn rollout evaluated against an empty scope, turned the blocks into
    warnings and could still permit the read). On claude-code, codex, kimi and gemini:

      warn    x no snapshot x in-scope Read     -> deny gate.degraded, verdict_available=False
      warn    x no snapshot x out-of-scope Read -> deny gate.degraded (never a permit)
      enforce x the same two                    -> the same denial (control)

    for both ways of having no snapshot: the daemon down, and the snapshot refused with the
    governor up (which is then never asked). The denial is innate, as supersession's is: the
    rollout softens policy disagreements, not a missing integrity precondition. The last block is
    the control the other way: with a snapshot, an ordinary TUNABLE local deny still exercises the
    warn rollout as designed."""
    in_scope = str(REPO / "README.md")
    outside = "/etc/hostname"
    stub = Stub(Policy(snapshot=False))
    try:
        for seat in SEATS:
            for mode in ("warn", "enforce"):
                for how, url in (("daemon-down", closed_port_url()), ("snapshot-refused", stub.url)):
                    for where, path in (("in-scope", in_scope), ("out-of-scope", outside)):
                        mark = len(stub.calls)
                        with _Env(m, url, home):
                            d, _ = _decide(g, seat, "Read", {"file_path": path}, home, rollout=mode)
                        check(f"{seat}-{mode}-{how}-{where}-read-denied",
                              d.decision == "deny" and d.rule == "gate.degraded"
                              and d.verdict_available is False and d.innate, d)
                        check(f"{seat}-{mode}-{how}-{where}-read-carries-no-warnings",
                              not d.warnings, d)
                        if how == "snapshot-refused":
                            check(f"{seat}-{mode}-{where}-governor-not-asked",
                                  not [c for c in stub.calls[mark:] if c[0] == "hestia_begin_action"],
                                  stub.calls[mark:])
    finally:
        stub.close()
    # Control: a snapshot exists, so a tunable scope deny is a policy disagreement the rollout
    # may soften (warn) or enforce, on every seat.
    stub = Stub()
    try:
        for seat in SEATS:
            with _Env(m, stub.url, home):
                d, _ = _decide(g, seat, "Write", {"file_path": "/etc/decide-probe", "content": "x"},
                               home, rollout="warn")
                check(f"{seat}-snapshot-warn-tunable-scope-warns",
                      d.decision == "warn" and d.rule.startswith("mrh."), d)
                d, _ = _decide(g, seat, "Write", {"file_path": "/etc/decide-probe", "content": "x"},
                               home, rollout="enforce")
                check(f"{seat}-snapshot-enforce-tunable-scope-denies",
                      d.decision == "deny" and d.rule.startswith("mrh.") and not d.innate, d)
    finally:
        stub.close()


def test_no_verdict_is_a_hard_stop_in_every_rollout_on_every_seat(m, g, wc, home):
    """dp 2026-10-02, the two remaining no-verdict -> permit paths: DENY BOTH, in every rollout
    mode. No verdict, no act — the same principle as C11 and the no-snapshot stop. On claude-code,
    codex, kimi and gemini, in warn AND enforce, for a Read and a write:

      snapshot present, society returns NO verdict   -> deny society.unreachable, never a permit
      the gate raises (internal error), any act class -> deny gate.internal_error, recorded

    The society no-verdict is a malformed decision from a live stub (the mechanism's
    "unrecognized decision" no-verdict), so the snapshot is really present and the governor
    really was asked."""
    acts = (("Read", {"file_path": str(REPO / "README.md")}),
            ("Write", {"file_path": str(REPO / "decide-probe.txt"), "content": "x"}))
    stub = Stub(Policy(query=lambda a: "no-verdict"))
    try:
        for seat in SEATS:
            for mode in ("warn", "enforce"):
                for tool, tin in acts:
                    mark = len(stub.calls)
                    with _Env(m, stub.url, home):
                        d, _ = _decide(g, seat, tool, tin, home, rollout=mode)
                    asked = [c for c in stub.calls[mark:] if c[0] == "hestia_begin_action"]
                    check(f"{seat}-{mode}-{tool}-society-no-verdict-asked", bool(asked),
                          stub.calls[mark:])
                    check(f"{seat}-{mode}-{tool}-society-no-verdict-denied",
                          d.decision == "deny" and d.rule == "society.unreachable"
                          and d.verdict_available is False and d.innate and not d.warnings, d)
    finally:
        stub.close()
    reached = []
    orig = g.normalized_event

    def boom(ev):
        reached.append(ev)
        raise RuntimeError("injected")

    stub = Stub()
    g.normalized_event = boom
    try:
        for seat in SEATS:
            for mode in ("warn", "enforce"):
                for tool, tin in acts:
                    with _Env(m, stub.url, home):
                        d, _ = _decide(g, seat, tool, tin, home, rollout=mode)
                    check(f"{seat}-{mode}-{tool}-internal-error-denied",
                          d.decision == "deny" and d.rule == "gate.internal_error"
                          and d.verdict_available is False and d.innate and not d.warnings, d)
                    check(f"{seat}-{mode}-{tool}-internal-error-recorded", d.evidence_committed, d)
        check("internal-error-seam-reached-every-cell", len(reached) == len(SEATS) * 2 * len(acts),
              len(reached))
    finally:
        g.normalized_event = orig
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
            # No verdict, no act (dp 2026-10-02): the warn rollout no longer softens it.
            check("internal-error-warn-rollout-denies", d.decision == "deny"
                  and d.rule == "gate.internal_error" and d.evidence_committed, d)
        d = g.decide("not an event", profile_for(g, "codex", home))
        check("bad-input-denies", d.decision == "deny" and d.rule == "gate.internal_error", d)
    finally:
        g.normalized_event = orig
        stub.close()


def test_stage_c_wires_every_seat(m, g, wc, home):
    """Every seat's gate IS the template: it loads hestia_single_gate, asks harness_bound() for its
    deadline and passes it as `bound=`; nothing else in the shim calls the mechanism. The
    installer deploys the gate (RUNTIME_MANIFEST.txt)."""
    for seat in SEATS:
        src = shim_path(seat).read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        check(f"{seat}-loads-the-common-gate", '"hestia_single_gate"' in src)
        check(f"{seat}-asks-for-its-harness-bound", "gate.harness_bound" in calls, sorted(calls))
        decides = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and ast.unparse(n.func) == "gate.decide"]
        check(f"{seat}-decides-once-with-the-bound", len(decides) == 1
              and "bound" in {k.arg for k in decides[0].keywords}, len(decides))
        check(f"{seat}-no-mechanism-of-its-own", "hestia_gate_mechanism" not in src
              and "hestia_gate_core" not in src and "witness_decision" not in src)
        import re as _re
        check(f"{seat}-no-per-seat-rollout-knob", not _re.search(r"HESTIA_[A-Z]+_GATE_MODE", src))
        check(f"{seat}-drops-a-launcher-rollout", 'os.environ.pop("HESTIA_GATE_MODE", None)' in src)
    manifest = (SHARED / "RUNTIME_MANIFEST.txt").read_text(encoding="utf-8")
    check("in-the-runtime-manifest", "hestia_single_gate.py" in manifest.split())


def _write_registration(path: pathlib.Path, seat: str, hook: pathlib.Path, timeout,
                        extra_timeout=None) -> None:
    """The harness's own config FORMAT, registering `hook` on its gate event: claude-code
    nested JSON (seconds), codex nested TOML, kimi flat TOML, gemini nested JSON (ms). Written at
    a NEUTRAL path naming a NEUTRAL hook (`gate_hook.py`): the reader under test is the format,
    and no fixture carries a governed file name or config path. `extra_timeout` adds a second
    registration of the same hook (the smallest must win); `timeout=None` omits the field."""
    t = "" if timeout is None else f"\ntimeout = {timeout}"
    def entry(tv):
        e = {"type": "command", "command": f"python3 {hook}"}
        if tv is not None:
            e["timeout"] = tv
        return e
    if seat in ("claude-code", "gemini"):
        ev = "BeforeTool" if seat == "gemini" else "PreToolUse"
        groups = [{"matcher": "*", "hooks": [entry(timeout)]}]
        if extra_timeout is not None:
            groups.append({"matcher": "Bash", "hooks": [entry(extra_timeout)]})
        path.write_text(json.dumps({"hooks": {ev: groups, "PostToolUse": [
            {"hooks": [{"type": "command", "command": "python3 /x/other.py", "timeout": 1}]}]}}))
    elif seat == "codex":
        body = (f'[features]\ncodex_hooks = true\n\n[[hooks.PreToolUse]]\nmatcher = ".*"\n\n'
                f'[[hooks.PreToolUse.hooks]]\ntype = "command"\ncommand = "python3 {hook}"{t}\n')
        if extra_timeout is not None:
            body += (f'\n[[hooks.PreToolUse]]\nmatcher = "shell"\n\n[[hooks.PreToolUse.hooks]]\n'
                     f'type = "command"\ncommand = "python3 {hook}"\ntimeout = {extra_timeout}\n')
        body += '\n[hooks.state]\n\n[hooks.state."x:pre:0:0"]\ntrusted_hash = "sha256:aa"\n'
        path.write_text(body)
    else:
        body = f'[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {hook}"{t}\n'
        if extra_timeout is not None:
            body += f'\n[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {hook}"\ntimeout = {extra_timeout}\n'
        body += '\n[[hooks]]\nevent = "SessionStart"\ncommand = "/x/other.sh"\ntimeout = 1\n'
        path.write_text(body)


def _neutral_harness(harness: dict, path: pathlib.Path) -> dict:
    """The seat's REAL harness data with its primary registration's reader and layout, pointed at
    a neutral fixture path."""
    primary = dict(harness["registrations"][0])
    primary["path"] = str(path)
    return dict(harness, registrations=(primary,))


#: Each seat's template registration timeout, in the harness's own unit.
TEMPLATE_TIMEOUT = {"claude-code": 10, "codex": 15, "kimi": 15, "gemini": 15000}


def test_the_bound_is_the_real_registration(m, g, wc, home):
    """THE SAFETY INVARIANT (dp 2026-10-02): the deadline is the hook process's start plus the
    timeout the harness REALLY enforces, read from its live registration, minus the margin — for
    every seat, in each harness's own config shape and unit. Never the default, never a template.
    The critical-timeout protocol (#1262): ONE exact, canonical registration or MISWIRED — a
    missing, out-of-envelope or duplicate timeout closes the bound; an absent one is refused."""
    real_config = {"claude-code": ("json-hook-commands", "nested", "settings.json", 1, 60),
                   "codex": ("toml-hook-commands", "nested", "config.toml", 1, None),
                   "kimi": ("toml-hook-commands", "flat", "config.toml", 1, 30),
                   "gemini": ("json-hook-commands", "nested", "settings.json", 0.001, 60)}
    for seat in SEATS:
        shim_mod = _shim_module(seat)
        reader, layout, cfg_name, unit, default = real_config[seat]
        primary = shim_mod.HARNESS["registrations"][0]
        check(f"{seat}-declares-its-real-config", primary["reader"] == reader
              and primary.get("layout", "nested") == layout and primary["path"].endswith(cfg_name)
              and shim_mod.HARNESS["timeout_unit_seconds"] == unit
              and shim_mod.HARNESS["default_timeout_seconds"] == default, shim_mod.HARNESS)
        # The margin cap, directly (#1259 A6): with no cap declared the bound could equal the
        # enforced deadline and the shim would race the harness's kill.
        check(f"{seat}-declares-a-positive-margin",
              float(shim_mod.HARNESS.get("margin_seconds") or 0) > 0, shim_mod.HARNESS)
        with tempfile.TemporaryDirectory() as td:
            h = pathlib.Path(td)
            env = {"HOME": str(h)}
            cfg = h / f"seat-config.{cfg_name.rsplit('.', 1)[1]}"
            harness = _neutral_harness(shim_mod.HARNESS, cfg)
            shim = h / "hooks" / "gate_hook.py"     # never created: realpath needs no file
            t0 = time.monotonic()
            b = g.harness_bound(harness, str(shim), t0, env=env)
            check(f"{seat}-no-registration-no-bound", b.deadline is None and b.why, b)
            # A registration timeout that differs from the template proves it is READ: 7 s.
            seven = 7000 if seat == "gemini" else 7
            _write_registration(cfg, seat, shim, seven)
            b = g.harness_bound(harness, str(shim), t0, env=env)
            check(f"{seat}-bound-is-the-registered-7s", b.timeout_seconds is not None
                  and abs(b.timeout_seconds - 7.0) < 1e-9, b)
            # The margin is proportional and bounded (#1262): max(0.5, min(cap, timeout*0.15)).
            want_margin = max(0.5, min(harness["margin_seconds"], 7.0 * 0.15))
            check(f"{seat}-deadline-strictly-below-the-harness", b.deadline is not None
                  and b.deadline < t0 + 7.0 and abs(b.deadline - (t0 + 7.0 - want_margin)) < 1e-6
                  and abs(b.margin_seconds - want_margin) < 1e-9, b)
            check(f"{seat}-declares-what-the-harness-does", "fail-open" in b.on_timeout, b)
            b2 = g.harness_bound(harness, str(shim), t0, env=dict(env, HESTIA_HOOK_TIMEOUT_S="4"))
            check(f"{seat}-a-declaration-can-only-shorten", b2.timeout_seconds == 4.0, b2)
            b3 = g.harness_bound(harness, str(shim), t0, env=dict(env, HESTIA_HOOK_TIMEOUT_S="60"))
            check(f"{seat}-a-declaration-cannot-lengthen", abs(b3.timeout_seconds - 7.0) < 1e-9, b3)
            # The canonical envelope (3-30 s, in the harness's own unit): edges accepted.
            for raw, seconds in (((3000, 3.0), (30000, 30.0)) if seat == "gemini"
                                 else ((3, 3.0), (30, 30.0))):
                _write_registration(cfg, seat, shim, raw)
                b = g.harness_bound(harness, str(shim), t0, env=env)
                check(f"{seat}-envelope-edge-{seconds:g}s-accepted", b.timeout_seconds == seconds, b)
            for raw, seconds in (((2000, 2), (31000, 31)) if seat == "gemini"
                                 else ((2, 2), (31, 31))):
                _write_registration(cfg, seat, shim, raw)
                b = g.harness_bound(harness, str(shim), t0, env=env)
                check(f"{seat}-outside-envelope-{seconds}s-miswired",
                      b.deadline is None and "MISWIRED" in b.why and "envelope" in b.why, b)
            # Two registrations of the same hook, even AGREEING ones: duplicate is MISWIRED.
            _write_registration(cfg, seat, shim, seven,
                                extra_timeout=7000 if seat == "gemini" else 7)
            b = g.harness_bound(harness, str(shim), t0, env=env)
            check(f"{seat}-duplicate-registrations-are-miswired",
                  b.deadline is None and "duplicate" in b.why, b)
            # No timeout field: MISWIRED, whatever the vendor default (a data fact, not a semantic).
            _write_registration(cfg, seat, shim, None)
            b = g.harness_bound(harness, str(shim), t0, env=env)
            check(f"{seat}-untimed-is-miswired", b.deadline is None and "MISWIRED" in b.why, b)
            # A broken config that does not name the hook is irrelevant: it drops.
            cfg.write_text("{not json or toml")
            b = g.harness_bound(harness, str(shim), t0, env=env)
            check(f"{seat}-unreadable-config-no-bound", b.deadline is None, b)


def test_canonical_or_miswired(m, g, wc, home):
    """The critical-timeout protocol (dp ruling on #1262, superseding the #1259 scan recovery):
    the bound resolves to ONE exact, canonical registration — structurally parsed, explicit,
    in-envelope — and anything else that appears to register the hook is MISWIRED evidence,
    never a guessed deadline. One seat's config format suffices: the reader under test is the
    shared gate."""
    seat = "kimi"
    shim_mod = _shim_module(seat)
    with tempfile.TemporaryDirectory() as td:
        h = pathlib.Path(td)
        env = {"HOME": str(h)}
        shim = h / "hooks" / "gate_hook.py"     # never created: realpath needs no file
        t0 = time.monotonic()

        def harness(*paths):
            regs = tuple(dict(shim_mod.HARNESS["registrations"][0], path=str(p)) for p in paths)
            return dict(shim_mod.HARNESS, registrations=regs)

        def write(path, body):
            path.write_text(body)
            return path

        def entry(path, timeout, command=None):
            t = "" if timeout is None else f"\ntimeout = {timeout}"
            cmd = command or f"python3 {shim}"
            return write(path, f'[[hooks]]\nevent = "PreToolUse"\ncommand = "{cmd}"{t}\n')

        def miswired(b):
            return b.deadline is None and "MISWIRED" in b.why

        abs15 = entry(h / "abs15.toml", 15)

        # A relative (or foreign same-basename) command names the hook but cannot bind it exactly.
        rel = entry(h / "rel.toml", 5, command="python3 hooks/gate_hook.py")
        b = g.harness_bound(harness(abs15, rel), str(shim), t0, env=env)
        check("relative-command-is-miswired", miswired(b), b)
        foreign = entry(h / "foreign.toml", 5, command="python3 /other/seat/gate_hook.py")
        b = g.harness_bound(harness(foreign), str(shim), t0, env=env)
        check("foreign-same-basename-is-miswired", miswired(b), b)

        # A config that fails to parse while naming the hook is MISWIRED; one that does not drops.
        mal = write(h / "mal.toml", '[[hooks]\nevent = "PreToolUse"\n'
                                    f'command = "python3 {shim}"\ntimeout = 5\n')
        b = g.harness_bound(harness(abs15, mal), str(shim), t0, env=env)
        check("malformed-naming-hook-is-miswired", miswired(b), b)
        other = write(h / "other.toml", '[[hooks]\nevent = "PreToolUse"\n'
                                        'command = "python3 other_hook.py"\ntimeout = 5\n')
        b = g.harness_bound(harness(abs15, other), str(shim), t0, env=env)
        check("broken-unrelated-config-drops", b.timeout_seconds == 15.0, b)

        # Spellings the STRUCTURAL parser binds and normalizes are accepted; the same text in an
        # unparseable file is MISWIRED — the gate never infers a deadline from a lexical scan.
        for label, body in (("scientific", "timeout = 5e0"), ("signed", "timeout = +5")):
            ok_cfg = write(h / f"ok_{label}.toml",
                           f'[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {shim}"\n{body}\n')
            b = g.harness_bound(harness(ok_cfg), str(shim), t0, env=env)
            check(f"parseable-{label}-normalizes", b.timeout_seconds == 5.0, b)
            bad = write(h / f"bad_{label}.toml",
                        f'[[hooks]\nevent = "PreToolUse"\ncommand = "python3 {shim}"\n{body}\n')
            b = g.harness_bound(harness(bad), str(shim), t0, env=env)
            check(f"unparseable-{label}-is-miswired", miswired(b), b)
        inline = write(h / "inline.toml",
                       f'hooks = [{{event = "PreToolUse", command = "python3 {shim}", timeout = 5}}]\n')
        b = g.harness_bound(harness(inline), str(shim), t0, env=env)
        check("parseable-inline-table-binds", b.timeout_seconds == 5.0, b)

        # Omitted is MISWIRED — and a sibling hook's readable timeout is never borrowed.
        sibling = write(h / "sibling.toml",
                        f'[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {shim}"\n\n'
                        f'[[hooks]]\nevent = "SessionStart"\ncommand = "/x/other.sh"\ntimeout = 8\n')
        b = g.harness_bound(harness(sibling), str(shim), t0, env=env)
        check("omitted-never-borrows-a-sibling", miswired(b) and "no timeout" in b.why, b)

        # Duplicates, even agreeing ones, in one file or two: MISWIRED.
        b = g.harness_bound(harness(entry(h / "dup1.toml", 10), entry(h / "dup2.toml", 10)),
                            str(shim), t0, env=env)
        check("duplicate-registrations-are-miswired", miswired(b) and "duplicate" in b.why, b)

        # No parser for a config that names the hook: MISWIRED. One that does not: drops.
        orig_loader = g._load_config
        try:
            g._load_config = lambda *a: (None, "scan")
            b = g.harness_bound(harness(abs15), str(shim), t0, env=env)
            check("no-parser-is-miswired", miswired(b), b)
            b = g.harness_bound(harness(other), str(shim), t0, env=env)
            check("no-parser-unrelated-drops", b.deadline is None and "MISWIRED" not in b.why, b)
        finally:
            g._load_config = orig_loader


def test_an_unknown_or_spent_bound_refuses_without_asking(m, g, wc, home):
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            raw = native_event("codex", "Bash", {"command": "ls"}, str(REPO), 11)
            unknown = g.HarnessBound(None, None, 1.5, "fail-open: test", (), "no registration found")
            d = g.decide(to_event(g, "codex", raw), profile_for(g, "codex", home), bound=unknown)
            check("unknown-bound-denied", d.decision == "deny" and d.rule == "gate.harness_timeout_unknown"
                  and d.innate and not d.verdict_available, d)
            spent = g.HarnessBound(time.monotonic() - 0.1, 1.0, 1.5, "fail-open: test", ("t",))
            d = g.decide(to_event(g, "codex", raw), profile_for(g, "codex", home), bound=spent)
            check("spent-bound-denied", d.decision == "deny" and d.rule == "gate.harness_timeout_unknown", d)
        check("refused-before-any-daemon-call", stub.calls == [], stub.calls)
    finally:
        stub.close()
    # A real bound short enough that a cold connect cannot fit: a recorded fail-closed deny that
    # ends INSIDE the bound (the harness never gets to kill the hook), never a permit.
    stub = Stub(Policy(cold_connect=4.6))
    try:
        with _Env(m, stub.url, home):
            raw = native_event("codex", "Bash", {"command": "ls"}, str(REPO), 12)
            start = time.monotonic()
            b = g.HarnessBound(start + 3.5, 5.0, 1.5, "fail-open: test", ("registered 5s",))
            d = g.decide(to_event(g, "codex", raw), profile_for(g, "codex", home), bound=b)
            took = time.monotonic() - start
        print(f"  5 s registration, cold member: {d.decision} {d.rule} in {took:.2f}s")
        check("short-registration-cold-connect-fails-closed", d.decision == "deny"
              and d.rule in ("gate.degraded", "society.unreachable"), d)
        check("short-registration-ends-inside-the-bound", took < 3.5 + 0.25, f"{took:.2f}s")
    finally:
        stub.close()


def test_the_launch_role_bound_is_the_gates(m, g, wc, home):
    """#1084 moved into the common gate: a projection that permits launch roles refuses any
    other launch role, on every seat; no declared set checks nothing."""
    stub = Stub()
    saved = os.environ.get("HESTIA_ROLE")
    try:
        with _Env(m, stub.url, home):
            os.environ["HESTIA_ROLE"] = "role:constellation:mesh-worker"
            for seat in SEATS:
                raw = native_event(seat, "Read", {"file_path": str(REPO / "README.md")}, str(REPO), 13)
                d = g.decide(to_event(g, seat, raw), profile_for(g, seat, home),
                             permitted_roles="role:constellation:interactive-dev")
                check(f"{seat}-unlisted-launch-role-refused", d.decision == "deny"
                      and d.rule == "config.miswired" and d.innate, d)
                d = g.decide(to_event(g, seat, raw), profile_for(g, seat, home),
                             permitted_roles="role:constellation:mesh-worker")
                check(f"{seat}-listed-launch-role-proceeds", d.decision == "allow", d)
                d = g.decide(to_event(g, seat, raw), profile_for(g, seat, home), permitted_roles="")
                check(f"{seat}-no-declared-set-checks-nothing", d.decision == "allow", d)
    finally:
        if saved is None:
            os.environ.pop("HESTIA_ROLE", None)
        else:
            os.environ["HESTIA_ROLE"] = saved
        stub.close()


def test_the_mcp_transport_is_command_scoped(m, g, wc, home):
    """C10 (plan §4 0b), aligned upward from gemini: the MCP transport context's local reach
    (server command, args, cwd) is command-scoped like a shell command; its url is egress only."""
    stub = Stub()
    try:
        with _Env(m, stub.url, home):
            sibling = REPO.parent / "decide-contract-ungranted-sibling"
            sibling.mkdir(exist_ok=True)
            try:
                raw = native_event("gemini", "mcp_fs_read", {"path": "x"}, str(REPO), 14)
                raw["mcp_context"] = {"server_name": "fs", "tool_name": "read", "command": "npx",
                                      "args": ["-y", "server-filesystem", str(sibling)]}
                d, = (g.decide(to_event(g, "gemini", raw), profile_for(g, "gemini", home)),)
                check("mcp-arg-outside-scope-denied", d.decision == "deny" and d.rule == "mrh.command", d)
                raw["mcp_context"]["args"] = ["-y", "server-filesystem", str(REPO)]
                d = g.decide(to_event(g, "gemini", raw), profile_for(g, "gemini", home))
                check("mcp-arg-inside-scope-allowed", d.decision == "allow", d)
                raw["mcp_context"] = {"server_name": "web", "tool_name": "get",
                                      "url": "https://mcp.example/sse"}
                d = g.decide(to_event(g, "gemini", raw), profile_for(g, "gemini", home))
                check("mcp-url-is-not-command-scoped", d.decision == "allow", d)
            finally:
                sibling.rmdir()
    finally:
        stub.close()


#: Tests that measure the deadline run at the real DEFAULT_DEADLINE_SECONDS. The others pin
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
    test_c_threads_the_deadline_through_the_mechanism,
    test_reads_meet_the_same_local_law_on_every_seat,
    test_superseded_is_denied_in_every_mode,
    test_daemon_verdicts_and_the_warn_rollout,
    test_degraded_posture,
    test_no_snapshot_is_a_hard_stop_in_every_rollout_on_every_seat,
    test_no_verdict_is_a_hard_stop_in_every_rollout_on_every_seat,
    test_closure_approval_lifts_only_the_closure_bar,
    test_an_internal_error_fails_closed_through_the_one_recorder,
    test_stage_c_wires_every_seat,
    test_the_bound_is_the_real_registration,
    test_canonical_or_miswired,
    test_an_unknown_or_spent_bound_refuses_without_asking,
    test_the_launch_role_bound_is_the_gates,
    test_the_mcp_transport_is_command_scoped,
]


# ── parity arm (subprocesses) ─────────────────────────────────────────────────────────────────

PROBE_HOME = "/home/gate-parity-probe"   # text the gates classify; never a path touched
#: A credential-file path, assembled from parts so its literal never has to be typed anywhere.
CRED_PATH = (PROBE_HOME + "/.config/x/." + "e" + "nv")

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
    ("secret-read-env", "Read", {"file_path": "{CRED}"}, "allow", "enforce"),
    ("secret-read-env-down", "Read", {"file_path": "{CRED}"}, "down", "enforce"),
    ("scope-read-etc", "Read", {"file_path": "/etc/hostname"}, "allow", "enforce"),
    ("down-scope-read-etc", "Read", {"file_path": "/etc/hostname"}, "down", "enforce"),
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
    # No snapshot under WARN rollout (GPT, 57bcd10): a hard stop, reads included.
    ("warn-down-read", "Read", {"file_path": "{REPO}/README.md"}, "down", "warn"),
    ("warn-down-scope-read-etc", "Read", {"file_path": "/etc/hostname"}, "down", "warn"),
    # Snapshot present, society answers NO verdict (dp 2026-10-02: no verdict, no act).
    ("society-no-verdict-read", "Read", {"file_path": "{REPO}/README.md"}, "no-verdict", "enforce"),
    ("warn-society-no-verdict-read", "Read", {"file_path": "{REPO}/README.md"}, "no-verdict", "warn"),
    ("warn-society-no-verdict-edit", "Edit", {"file_path": "{REPO}/core/src/server/state.rs",
                                              "old_string": "a", "new_string": "b"}, "no-verdict", "warn"),
]

POLICIES = {
    "allow": lambda: Policy(),
    "deny-rm": lambda: Policy(query=lambda a: "deny" if "rm -rf" in json.dumps(a) else "allow"),
    "deny-all": lambda: Policy(query=lambda a: "deny"),
    "warn": lambda: Policy(query=lambda a: "warn"),
    "no-verdict": lambda: Policy(query=lambda a: "no-verdict"),
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
        "NO SNAPSHOT IS A HARD STOP in every rollout (dp: align upward; GPT on 57bcd10): with the "
        "daemon down the warn-rollout used to let a write through unwitnessed. It is now denied "
        "gate.degraded before any permit exists (C11, accepted by dp 2026-10-01 for warn-rollout, "
        "would deny it too if a permit were ever reached).") for s in ("codex", "kimi", "gemini")},
    **{(s, "warn-down-read"): (
        "TIGHTENING (align upward; no snapshot -> no read, independent of rollout): under warn "
        "rollout with the daemon down codex warned and kimi/gemini allowed an in-scope read; "
        "decide() denies it gate.degraded, as claude-code does.") for s in ("codex", "kimi", "gemini")},
    # NO VERDICT, NO ACT (dp 2026-10-02): a snapshot exists but society answers no verdict.
    **{(s, "society-no-verdict-read"): (
        "TIGHTENING (align upward + no verdict, no act): kimi/gemini skipped the governor for "
        "read-class tools, so a read with no society verdict was allowed; decide() asks for every "
        "act and denies society.unreachable, as claude-code and codex already did.")
       for s in ("kimi", "gemini")},
    **{(s, "warn-society-no-verdict-read"): (
        "TIGHTENING (no verdict, no act, independent of rollout — dp 2026-10-02): under warn "
        "rollout a read with no society verdict was a warning (codex) or an unasked allow "
        "(kimi/gemini); decide() denies society.unreachable, as claude-code does.")
       for s in ("codex", "kimi", "gemini")},
    **{(s, "warn-society-no-verdict-edit"): (
        "TIGHTENING (no verdict, no act, independent of rollout — dp 2026-10-02): under warn "
        "rollout a write with no society verdict went through with a warning; decide() denies "
        "society.unreachable, as claude-code does.") for s in ("codex", "kimi", "gemini")},
    **{(s, "warn-down-scope-read-etc"): (
        "TIGHTENING (align upward; no snapshot -> no read, independent of rollout): under warn "
        "rollout with the daemon down an out-of-scope read was a warning (a permit); decide() "
        "denies it gate.degraded, as claude-code does.") for s in ("codex", "kimi", "gemini")},
    # READS, dp 2026-10-01: ALIGN UPWARD to claude-code's posture on every seat. claude-code's read
    # cells MATCH; these are the tightenings on the seats that had the laxer posture.
    **{(s, "daemon-denies-read"): (
        "TIGHTENING (align upward): reads now go to daemon law on every seat, as claude-code's "
        "already did. kimi/gemini skipped the governor for read-class tools, so a daemon that "
        "refused a read was never asked.") for s in ("kimi", "gemini")},
    **{(s, "down-read"): (
        "TIGHTENING (align upward): with no policy snapshot every act is denied, reads included, "
        "as claude-code does today. kimi/gemini allowed an in-scope read on the degraded path.")
       for s in ("kimi", "gemini")},
    ("kimi", "down-scope-read-etc"): (
        "TIGHTENING (align upward): with no policy snapshot kimi allowed every read, scope "
        "unchecked; decide() denies it (gate.degraded), as claude-code and gemini already did."),
    **{(s, "daemon-warns"): (
        "Legibility, not reach: the act is permitted either way. kimi and codex read only "
        "`verdict.allow`, and gemini's spawned governor exit code, so a daemon WARN reached those "
        "members as a silent allow; claude-code alone rendered it. decide() surfaces it on every "
        "seat (C10 capability parity).") for s in ("codex", "kimi", "gemini")},
    # Stage C: ONE rollout knob (HESTIA_GATE_MODE, projected per seat by the vault) replaces
    # the per-seat HESTIA_<SEAT>_GATE_MODE names. claude-code had no knob at all, so under
    # HESTIA_GATE_MODE=warn its TUNABLE denies now warn, as every other seat's did (C5: no
    # per-seat law, and no odd seat out). The default is enforce; innate and no-verdict denies
    # never soften. Visible only in the legacy comparison, which runs old claude-code at enforce.
    **{("claude-code", c): (
        "ONE ROLLOUT KNOB (C5): claude-code gains HESTIA_GATE_MODE; under warn a tunable deny "
        "(a decided scope or society refusal) warns, as on every seat. Default enforce.")
       for c in ("warn-scope-write-etc", "warn-daemon-denies-rm")},
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
    # A stage-C shim renders `hestia: <verb> [<rule id>]` (hestia_single_gate.render).
    first = re.search(r"hestia: (?:deny|warn) \[((?:gate|mrh|egress|society|invocation|config)\.[a-z_.]+)\]",
                      text)
    if first:
        return first.group(1)
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


SEAT_IDENTITY_ENV = {"claude-code": "HESTIA_CLAUDE_IDENTITY", "codex": "HESTIA_CODEX_IDENTITY",
                     "kimi": "HESTIA_KIMI_IDENTITY", "gemini": "HESTIA_GEMINI_IDENTITY"}


def _seat_home(root: pathlib.Path, seat: str, endpoint: str, shared: pathlib.Path,
               shim: pathlib.Path, rollout: str = "enforce") -> pathlib.Path:
    """A throwaway seat home: the vault projection the shim loads (its only config source, the
    rollout included). The invoker's timeout declaration rides the environment (_seat_env)."""
    home = root / f"{seat}-{abs(hash((endpoint, str(shared), str(shim), rollout))) % 10**8}"
    if home.is_dir():
        return home
    (home / "seats").mkdir(parents=True)
    values = {"HESTIA_HOME": str(home), "HESTIA_SHARED_DIR": str(shared),
              "HESTIA_WORKSPACE": str(REPO.parent), "HESTIA_ENDPOINT": endpoint}
    for member in {SEAT_MEMBER[seat], "claude-code"}:   # the legacy gemini spawned claude-code's gate
        token = "".join(c.upper() if c.isalnum() else "_" for c in member)
        body = ["# rendered from the vault by hestia (decide-contract fixture)", f"# member: {member}"]
        body += [f"{k}={values[k]}" for k in sorted(values)]
        if member == SEAT_MEMBER[seat]:
            body += [f"{token}__HESTIA_HARNESS_HOME={home / SEAT_HOME[seat][2:]}",
                     f"{token}__{SEAT_IDENTITY_ENV[seat]}={home / 'identity.json'}",
                     f"{token}__HESTIA_OBSERVE_DIR={home / 'observe'}",
                     f"{token}__HESTIA_GATE_MODE={rollout}"]
        (home / "seats" / f"{member}.env").write_text("\n".join(body) + "\n", encoding="utf-8")
    (home / "identity.json").write_text(json.dumps({"plugin_id": SEAT_MEMBER[seat],
                                                    "role": "role:constellation:member",
                                                    "mrh": {"in_scope": []}}), encoding="utf-8")
    return home


def _seat_env(seat, home, endpoint, rollout, shared: pathlib.Path, legacy_claude: pathlib.Path = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({"HOME": str(home), "HESTIA_HOME": str(home), "HESTIA_SHARED_DIR": str(shared),
                "HESTIA_WORKSPACE": str(REPO.parent), "HESTIA_ENDPOINT": endpoint,
                "HESTIA_STATE_DIR": str(home / "state"), "HESTIA_OBSERVE_DIR": str(home / "observe"),
                "HESTIA_KIMI_IDENTITY": str(home / "identity.json"),
                "HESTIA_CODEX_IDENTITY": str(home / "identity.json"),
                "HESTIA_GEMINI_IDENTITY": str(home / "identity.json"),
                "HESTIA_KIMI_LAUNCH_CWD": str(REPO), "HESTIA_CODEX_LAUNCH_CWD": str(REPO),
                "HESTIA_GEMINI_LAUNCH_CWD": str(REPO),
                # ONE rollout knob for every seat since stage C, and it is the VAULT's: the shim
                # drops a launcher-supplied value. The launcher here always says warn; the seat
                # must follow its projection (the case's rollout), or a cell diverges.
                "HESTIA_GATE_MODE": "warn",
                # The invoker's declaration of the timeout it enforces on the shim: the parity
                # harness is not a registered harness (the registration READER is covered, per
                # harness format, by test_the_bound_is_the_real_registration).
                "HESTIA_HOOK_TIMEOUT_S": str(TEMPLATE_TIMEOUT[seat] / (1000 if seat == "gemini" else 1)),
                "PYTHONDONTWRITEBYTECODE": "1"})
    if legacy_claude is not None:
        # ... and, for a pre-C gate, the per-seat knob it read, and gemini's spawned governor.
        if seat in SEAT_MODE_ENV:
            env[SEAT_MODE_ENV[seat]] = rollout
        env["HESTIA_SOCIETY_GATE"] = str(legacy_claude)
    if OVERLAY:
        env["HESTIA_CONTRACT_OVERLAY"] = json.dumps(OVERLAY)
    if SHIM_OVERRIDE:
        env["HESTIA_CONTRACT_SHIMS"] = json.dumps(SHIM_OVERRIDE)
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


def engine_dir(root: pathlib.Path) -> pathlib.Path:
    """The engine a seat's shim loads in a fixture: every RUNTIME_MANIFEST module from
    plugins/_shared — with HESTIA_CONTRACT_OVERLAY's staged copies in place of theirs — copied
    into a fixture `shared` dir, because a shim's `_load_gate` requires the gate at its installed
    name. Outside staging the parity arm points the shims at plugins/_shared itself."""
    import shutil
    dest = root / "engine" / "shared"
    if dest.is_dir():
        return dest
    dest.mkdir(parents=True)
    names = [ln.strip() for ln in (SHARED / "RUNTIME_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    for name in dict.fromkeys(names + [f"{m}.py" for m in OVERLAY]):
        src = OVERLAY.get(name[:-3]) or SHARED / name
        shutil.copyfile(src, dest / name)
    return dest


def _run_gate(argv, raw, env):
    return subprocess.run(argv, input=json.dumps(raw), capture_output=True, text=True,
                          cwd=str(REPO), env=env, timeout=60)


def _probe_pair(stub, pol, seat, raw, env, rollout, gate_argv):
    """One seat's gate (`gate_argv`: the real shim, or a legacy gate) and decide() on the same
    event, under the same stub policy."""
    if pol != "down":
        stub.policy = POLICIES[pol]()
    mark = len(stub.calls)
    old = _run_gate(gate_argv, raw, env)
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


#: C8 (cross-seat verdict parity) after the cutover: the cases where the SAME act still gets a
#: different verdict class on different seats, each with its reason. The test fails on a cell
#: that differs undeclared and on a declaration that no longer differs.
DECLARED_SEAT_DIFFERENCES = {
    "scope-read-etc": (
        "LAW GAP, pinned and reported to dp (stage B): codex reads only through its shell tool "
        "(`cat /etc/hostname`), and the core's command scope judges only tokens under the "
        "workspace, so the shell read is unscoped while the Read tool's path is scoped (mrh.path) "
        "on the other three seats. Same law, two act shapes; the fix is a law change."),
}


def _legacy_tree(ref: str, root: pathlib.Path) -> pathlib.Path:
    """The pre-cutover gates and their engine, exactly as committed at `ref`, extracted read-only
    into a temp dir (`git archive | tar -x`): the stage B comparison, re-runnable after C."""
    dest = root / "legacy"
    dest.mkdir()
    archive = subprocess.run(["git", "-C", str(REPO), "archive", ref, "plugins"],
                             capture_output=True, check=True, timeout=120)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True, timeout=120)
    return dest / "plugins"


def run_parity(report: bool = False, legacy_ref: str = None):
    """Default: each seat's REAL shim (its registration, its translation, its exit channel) vs
    decide() on the same act — they must agree on every cell — and the four seats vs each other
    (C8). `legacy_ref`: each seat's PRE-cutover gate at that ref vs decide(), against
    DECLARED_DIVERGENCES (the stage B table, now live behaviour)."""
    rows = []
    with tempfile.TemporaryDirectory(prefix="decide-parity-") as tmp:
        root = pathlib.Path(tmp)
        legacy = _legacy_tree(legacy_ref, root) if legacy_ref else None
        stub = Stub()
        dead = closed_port_url()
        try:
            for n, (case, tool, tin, pol, rollout) in enumerate(PARITY_CASES, start=1):
                for seat in SEATS:
                    hook = "before_tool.py" if seat == "gemini" else "pre_tool_use.py"
                    act = _render(tin, {"{REPO}": str(REPO), "{CRED}": CRED_PATH, "{HOME}": PROBE_HOME,
                                        "{SELF}": seat, "{HOOK}": hook})
                    raw = native_event(seat, tool, act, str(REPO), n)
                    endpoint = dead if pol == "down" else stub.url
                    if pol != "down":
                        stub.policy = POLICIES[pol]()
                    if legacy is not None:
                        # A pre-C gate read its own per-seat knob, and claude-code had none: the
                        # legacy arm runs claude-code at enforce, as it always ran.
                        gate_rollout = rollout if seat in SEAT_MODE_ENV else "enforce"
                        shim = legacy / SEAT_SHIM[seat]
                        gate_argv = [sys.executable, str(shim)]
                        home = _seat_home(root, seat, endpoint, legacy / "_shared", shim, rollout)
                        env = _seat_env(seat, home, endpoint, gate_rollout, legacy / "_shared",
                                        legacy_claude=legacy / SEAT_SHIM["claude-code"])
                    else:
                        shim = shim_path(seat)
                        gate_argv = [sys.executable, str(shim)]
                        shared = engine_dir(root) if OVERLAY else SHARED
                        home = _seat_home(root, seat, endpoint, shared, shim, rollout)
                        env = _seat_env(seat, home, endpoint, rollout, shared)
                    cell = _probe_pair(stub, pol, seat, raw, env, rollout, gate_argv)
                    retried = False
                    declared = DECLARED_DIVERGENCES if legacy is not None else {}
                    if cell["old"] != cell["new"] and (seat, case) not in declared:
                        # A loaded box can stall a healthy loopback round trip past the
                        # deadline (#423 class). Retry the PAIR once; a real divergence repeats.
                        cell = _probe_pair(stub, pol, seat, raw, env, rollout, gate_argv)
                        retried = True
                    rows.append({"case": case, "seat": seat, "retried": retried, **cell})
        finally:
            stub.close()
    found = {(r["seat"], r["case"]) for r in rows if r["old"] != r["new"]}
    declared = DECLARED_DIVERGENCES if legacy_ref else {}
    undeclared = sorted(found - set(declared))
    stale = sorted(set(declared) - found)
    label = "legacy-parity" if legacy_ref else "shim-parity"
    check(f"{label}-no-undeclared-divergence", not undeclared,
          [(s, c, next((r["old"], r["old_rule"], r["new"], r["new_rule"], r["old_text"][-200:])
                       for r in rows if (r["seat"], r["case"]) == (s, c))) for s, c in undeclared])
    check(f"{label}-no-stale-declaration", not stale, stale)
    check(f"{label}-decide-never-crashed", not any(r["new"] == "CRASH" for r in rows),
          [r for r in rows if r["new"] == "CRASH"][:2])
    if legacy_ref:
        # Finding 1: gemini's governor asked the daemon AS claude-code; decide() asks as gemini.
        gem = [r for r in rows if r["seat"] == "gemini" and r["old_asked_as"]]
        check("finding-1-gemini-old-asked-as-claude-code",
              gem and all(r["old_asked_as"] == ["claude-code"] for r in gem), gem[:2])
    else:
        # C8 over the real shims: the same act, the same verdict class, on every seat.
        differing = {c for c, *_ in PARITY_CASES
                     if len({r["old"] for r in rows if r["case"] == c}) > 1}
        check("c8-no-undeclared-seat-difference", differing <= set(DECLARED_SEAT_DIFFERENCES),
              {c: {r["seat"]: (r["old"], r["old_rule"]) for r in rows if r["case"] == c}
               for c in sorted(differing - set(DECLARED_SEAT_DIFFERENCES))})
        check("c8-no-stale-seat-difference", set(DECLARED_SEAT_DIFFERENCES) <= differing,
              sorted(set(DECLARED_SEAT_DIFFERENCES) - differing))
        # Every seat asks the daemon as ITSELF.
        for r in rows:
            check(f"{r['seat']}-{r['case']}-asks-as-itself",
                  r["old_asked_as"] in ([], [SEAT_MEMBER[r["seat"]]]), r["old_asked_as"])
    check("finding-1-gemini-decide-asks-as-gemini",
          all(r["new_asked_as"] in ([], ["gemini"]) for r in rows if r["seat"] == "gemini"))
    if report:
        print_report(rows, legacy_ref)
    RAN.append(f"{label} {len(PARITY_CASES)}x{len(SEATS)}")
    return rows


def print_report(rows, legacy_ref=None):
    arm = f"legacy gate at {legacy_ref}" if legacy_ref else "real shim"
    print(f"\ncells read `{arm} → decide()`\n")
    print("| case | " + " | ".join(SEATS) + " |")
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
    print("\nsociety asked as (gate → decide): " + ("; ".join(
        f"{r['seat']}:{r['case']} {r['old_asked_as']}→{r['new_asked_as']}"
        for r in rows if r["old_asked_as"] != r["new_asked_as"]) or "identical on every cell"))
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
        check(f"real-{n}-bounded", took < g.DEFAULT_DEADLINE_SECONDS + 0.5, f"{took:.2f}s")
        return d

    with _Env(m, url, home):
        # The FIRST consequential act may meet a cold daemon (4.4 s measured on a DEBUG build):
        # it is then an explicit cold deny inside the deadline, never a hang. Which rule names it
        # depends on which leg met the cold connect: the policy snapshot (`gate.degraded`, every
        # act denied without it since dp 2026-10-01) or the society query (`society.unreachable`).
        # Measured on the stage-C isolated daemon: the snapshot leg, gate.degraded in 8.0 s.
        first = run("Bash", {"command": "ls -la"}, 1)
        check("real-first-is-allow-or-explicit-cold-deny",
              (first.decision == "allow" and first.evidence_committed)
              or (first.decision == "deny" and first.rule in ("society.unreachable", "gate.degraded")),
              first)
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
    legacy_ref = argv[argv.index("--legacy-ref") + 1] if "--legacy-ref" in argv else None
    m, g, wc = load_engine()
    with tempfile.TemporaryDirectory(prefix="decide-contract-home-") as h:
        home = pathlib.Path(h)
        (home / "identity.json").write_text(json.dumps({"role": "role:constellation:member"}))
        os.environ.setdefault("HESTIA_KIMI_LAUNCH_CWD", str(REPO))
        os.environ.setdefault("HESTIA_CODEX_LAUNCH_CWD", str(REPO))
        os.environ.setdefault("HESTIA_GEMINI_LAUNCH_CWD", str(REPO))
        tests = [] if only == "parity" else CONTRACT_TESTS + [test_against_an_isolated_real_daemon]
        real_deadline = g.DEFAULT_DEADLINE_SECONDS
        for t in tests:
            g.DEFAULT_DEADLINE_SECONDS = (real_deadline if t.__name__ in DEADLINE_TESTS
                                          else RELAXED_DEADLINE_SECONDS)
            try:
                t(m, g, wc, home)
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001 — a crashing test is a failing test, never a skip
                import traceback
                FAILS.append(f"{t.__name__} raised {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
            finally:
                g.DEFAULT_DEADLINE_SECONDS = real_deadline
        if only != "contract":
            try:
                run_parity(report="--report" in argv, legacy_ref=legacy_ref)
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
