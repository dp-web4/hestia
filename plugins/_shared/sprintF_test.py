#!/usr/bin/env python3
"""Sprint F acceptance — the §6.F cutover (PRD §7.1 criteria 2, 5, 9).

Runs the PATCHED kimi and codex hooks from the staged tree (env SPRINTF_TREE, default
./tree beside this file) as SUBPROCESSES, the way the engines do — event JSON on stdin,
exit code as the verdict — against a stub MCP daemon, inside a synthetic workspace that
is deliberately NOT under /tmp (the temp roots are unconditionally in scope, so a /tmp
workspace greens every scope assertion for the wrong reason).

Arms (explicit-ALL convention):
  (5)   policy unavailable in enforce -> the ratified DEGRADED mode: a Write is denied, a
        Read is allowed, and a plain allow of the Write is impossible (criterion 5 — the
        test injects an unreachable daemon, which is exactly `policy=None` at the
        evaluate() seam: the shim must not fall back to any local replica);
  (9c)  every degraded deny is RECORDED: the per-shim diagnostic log gains a row with
        verdict_available=False, and the gate-availability telemetry gains a row;
  (2)   the §3.3 differential inputs get the SAME verdict from the kimi and codex paths
        (convergence pre-proof; the full fleet convergence proof is Sprint G's);
  (no-regression) an ordinary in-scope write is allowed with a live (stubbed) policy
        snapshot, and the society policy path actually ran;
  (fetch) fetch_policy_snapshot composes the snapshot from what the daemon can certify
        (role via hestia_operating_law, live path grants via hestia_scope_status), yields
        a THIN snapshot from a reachable daemon lacking those surfaces, and None from an
        unreachable one;
  (order) a governance-surface write with the daemon DOWN is still refused as gate-self
        (Gate 1c precedes the policy stage), never blurred into the degraded class.

check() RAISES so pytest sees each case; the __main__ runner collects.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Default IN-REPO: this file sits at <repo>/plugins/_shared/, and post-cutover the repo
# tree IS the tree under test (sprintD/E convention). SPRINTF_TREE remains the override
# for out-of-tree staged verification; the old ./tree default was an uncommitted staging
# dir that exists in no checkout, so the bare CI invocation red-lit every arm.
TREE = os.environ.get("SPRINTF_TREE") or os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
HOOK = "pre_" + "tool_use.py"          # named as data, never a write destination
CORE = "hestia_gate_" + "core.py"
MECH = "hestia_gate_" + "mechanism.py"
CLOSURE = "hestia_governance_" + "closure.py"
SHARED = os.path.join(TREE, "plugins", "_shared")
KIMI_HOOK = os.path.join(TREE, "plugins", "kimi", "hooks", HOOK)
CODEX_HOOK = os.path.join(TREE, "plugins", "codex", "hooks", HOOK)
DEAD = "http://127.0.0.1:9/mcp"        # port 9 (discard) is closed by convention

SHIMS = {
    "claude": {"hook": os.path.join(TREE, "plugins", "claude-code", "hooks", HOOK),
               "plugin_id": "claude-code", "bash_tool": "Bash",
               "identity_env": "HESTIA_CLAUDE_IDENTITY",
               "mode_env": "HESTIA_PRE_FAIL_CLOSED", "mode_value": "1"},
    "kimi": {"hook": KIMI_HOOK, "plugin_id": "kimi-code", "bash_tool": "Bash",
             "identity_env": "HESTIA_KIMI_IDENTITY", "mode_env": "HESTIA_KIMI_GATE_MODE"},
    "codex": {"hook": CODEX_HOOK, "plugin_id": "codex", "bash_tool": "bash",
              "identity_env": "HESTIA_CODEX_IDENTITY", "mode_env": "HESTIA_CODEX_GATE_MODE"},
}


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class StubDaemon:
    """Scripted MCP-over-HTTP daemon; records calls; scripts verdicts. Extends the
    boundary-test stub with the two policy-snapshot surfaces Sprint F consumes."""

    def __init__(self, policy=None, law=None, scope_status=None, thin=False):
        self.policy = policy if policy is not None else {"status": "decided",
                                                         "decision": "allow"}
        self.law = law
        self.scope_status = scope_status
        self.thin = thin       # emulate an older daemon: unknown tools answer {}
        self.calls = []

    def respond(self, name, args):
        if name == "hestia_connect":
            return {"sessionId": "stub-session"}
        if name == "hestia_begin_action":
            return {"actionId": "stub-action"}
        if name == "hestia_query_policy":
            return self.policy
        if name == "hestia_operating_law":
            if self.thin:
                return {}
            if self.law is not None:
                return self.law
            return {"identity": {"plugin_id": args.get("session_id", "?"),
                                 "role": "role:constellation:member"},
                    "law_hash": "stub-law-hash", "law": []}
        if name == "hestia_scope_status":
            if self.thin:
                return {}
            if self.scope_status is not None:
                return self.scope_status
            return {"plugin_id": args.get("plugin_id"), "requests": [], "live_grants": []}
        if name == "hestia_gate_escalation_claim":
            return {"claimed": False, "permits_write": False,
                    "escalation_id": "esc-stub-1",
                    "how_to_decide": "hestia gate approve esc-stub-1"}
        if name in ("hestia_request_witness", "hestia_witness_decision"):
            return {"ok": True}
        return {}

    def names(self):
        return [n for n, _ in self.calls]


def _make_handler(stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                req = {}
            method = req.get("method")
            if method == "initialize":
                obj = {"jsonrpc": "2.0", "id": req.get("id"),
                       "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "serverInfo": {"name": "stub", "version": "0"}}}
                sid = "stub-mcp"
            elif method == "tools/call":
                params = req.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                stub.calls.append((name, args))
                payload = stub.respond(name, args)
                obj = {"jsonrpc": "2.0", "id": req.get("id"),
                       "result": {"structuredContent": payload,
                                  "content": [{"type": "text",
                                               "text": json.dumps(payload)}]}}
                sid = None
            else:
                obj, sid = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}, None
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if sid:
                self.send_header("mcp-session-id", sid)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class Server:
    def __init__(self, stub):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(stub))
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_workspace():
    """A scratch workspace NOT under /tmp, holding granted/notgranted repos and a
    hestia/plugins/_shared copy of the PATCHED shared modules (what the shims import)."""
    base = os.path.expanduser("~/.cache/hestia-sprintF-tests")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=base)
    ws = os.path.join(tmp, "ws")
    shared_dst = os.path.join(ws, "hestia", "plugins", "_shared")
    os.makedirs(shared_dst)
    for f in (MECH, CORE, CLOSURE):
        src = os.path.join(SHARED, f)
        if os.path.isfile(src):
            shutil.copy(src, shared_dst)
    for d in ("granted", "notgranted"):
        os.makedirs(os.path.join(ws, d), exist_ok=True)
    os.makedirs(os.path.join(ws, "hestia", "plugins", "kimi", "hooks"), exist_ok=True)
    os.makedirs(os.path.join(ws, "hestia", "plugins", "codex", "hooks"), exist_ok=True)
    with open(os.path.join(ws, "identity.json"), "w", encoding="utf-8") as fh:
        json.dump({"role": "role:constellation:member",
                   "mrh": {"in_scope": ["repo:hestia"]}}, fh)
    return tmp, ws


def run_hook(shim, ws, event, endpoint, home=None, cwd=None):
    cfg = SHIMS[shim]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"HESTIA_WORKSPACE": ws,
                cfg["identity_env"]: os.path.join(ws, "identity.json"),
                "HESTIA_OBSERVE_DIR": os.path.join(ws, "observe-" + shim),
                cfg["mode_env"]: cfg.get("mode_value", "enforce"),
                # Exercise the tree under test, never an installed or per-vendor copy.
                "HESTIA_SHARED_DIR": SHARED,
                "HESTIA_ENDPOINT": endpoint})
    if home:
        env["HESTIA_HOME"] = home
    p = subprocess.run([sys.executable, cfg["hook"]], input=json.dumps(event),
                       capture_output=True, text=True, timeout=60,
                       cwd=cwd or os.path.join(ws, "granted"), env=env)
    return p.returncode, p.stderr


def _event(tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "sprintF-test", "cwd": ""}


# ---- criterion 5: unreachable policy authority -> degraded, NEVER plain allow ----
def test_criterion5_daemon_down_degrades_deny_write_allow_read():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            rc, err = run_hook(shim, ws,
                               _event("Write", {"file_path": os.path.join(ws, "granted", "a.md"),
                                                "content": "x"}), DEAD)
            check(f"{shim}-write-denied", rc == 2, f"rc={rc} stderr={err}")
            check(f"{shim}-degraded-class", "[degraded]" in err, err)
            check(f"{shim}-names-the-trigger", "unreachable" in err, err)
            rc, err = run_hook(shim, ws,
                               _event("Read", {"file_path": os.path.join(ws, "granted", "a.md")}),
                               DEAD)
            check(f"{shim}-read-allowed", rc == 0, f"rc={rc} stderr={err}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_criterion5_degraded_never_relaxes_egress():
    """The innate egress invariant binds even in degraded mode — including on the READ path
    the mode otherwise allows."""
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            rc, err = run_hook(shim, ws,
                               _event("Read", {"file_path": os.path.join(ws, "granted", ".env")}),
                               DEAD)
            check(f"{shim}-egress-still-denied", rc == 2, f"rc={rc} stderr={err}")
            check(f"{shim}-egress-class", "forbidden path" in err, err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- criterion 9(c): degraded denies are RECORDED ----
def test_degraded_denies_are_recorded():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            home = os.path.join(tmp, "home-" + shim)
            os.makedirs(home, exist_ok=True)
            rc, err = run_hook(shim, ws,
                               _event("Write", {"file_path": os.path.join(ws, "granted", "b.md"),
                                                "content": "x"}), DEAD, home=home)
            check(f"{shim}-denied", rc == 2, f"rc={rc} stderr={err}")
            deny_log = os.path.join(home, "telemetry",
                                    f"gate-denies-{SHIMS[shim]['plugin_id']}.jsonl")
            check(f"{shim}-diagnostic-log-exists", os.path.isfile(deny_log),
                  f"missing {deny_log}; stderr={err}")
            row = json.loads(open(deny_log, encoding="utf-8").readlines()[-1])
            check(f"{shim}-row-not-conduct", row.get("verdict_available") is False, str(row))
            check(f"{shim}-row-is-deny", row.get("decision") == "deny", str(row))
            avail_log = os.path.join(home, "telemetry", "gate-unavailable.jsonl")
            check(f"{shim}-availability-row", os.path.isfile(avail_log),
                  f"missing {avail_log}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- criterion 2 pre-proof: §3.3 differential inputs, same verdict via both shims ----
def test_differential_inputs_converge():
    tmp, ws = make_workspace()
    stub = StubDaemon()
    srv = Server(stub)
    try:
        cases = [
            ("dotdot-path",
             lambda shim: _event("Write",
                                 {"file_path": f"{ws}/granted/../notgranted/secret",
                                  "content": "x"}),
             "'notgranted' is not granted"),
            ("dotdot-command",
             lambda shim: _event(SHIMS[shim]["bash_tool"],
                                 {"command": f"cat {ws}/granted/../notgranted/secret"}),
             "'notgranted' is not granted"),
            ("temp-sibling",
             lambda shim: _event("Write", {"file_path": "/tmp-other/x", "content": "x"}),
             "outside the workspace"),
            ("egress-in-granted",
             lambda shim: _event("Write", {"file_path": f"{ws}/granted/.env",
                                           "content": "x"}),
             "forbidden path"),
        ]
        for name, mk, marker in cases:
            outs = {}
            for shim in ("kimi", "codex"):
                rc, err = run_hook(shim, ws, mk(shim), srv.endpoint)
                outs[shim] = (rc, err)
                check(f"{name}-{shim}-denied", rc == 2, f"rc={rc} stderr={err}")
                check(f"{name}-{shim}-names-trigger", marker in err, err)
            check(f"{name}-same-verdict",
                  outs["kimi"][0] == outs["codex"][0] == 2, str(outs))
    finally:
        srv.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ---- no-regression: ordinary in-scope write allowed with a live (stubbed) snapshot ----
def test_ordinary_in_scope_write_allowed_with_live_snapshot():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            stub = StubDaemon()
            srv = Server(stub)
            try:
                rc, err = run_hook(shim, ws,
                                   _event("Write",
                                          {"file_path": os.path.join(ws, "granted", "ok.md"),
                                           "content": "x"}), srv.endpoint)
                check(f"{shim}-allowed", rc == 0, f"rc={rc} stderr={err}")
                check(f"{shim}-policy-ran", "hestia_begin_action" in stub.names(),
                      stub.names())
                check(f"{shim}-snapshot-fetched", "hestia_operating_law" in stub.names(),
                      stub.names())
                check(f"{shim}-no-escalation", "hestia_gate_escalation_claim"
                      not in stub.names(), stub.names())
            finally:
                srv.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_claude_workspace_root_standing_grant_admits_absolute_bash_path():
    """#596 / post-#517 regression. Drive Claude's actual shim as a subprocess.

    A workspace-root standing grant is faithfully represented as ``path:<absolute>``.
    Before #596 the parser erased that type and the segment-keyed matcher denied the very
    next Bash call, so the seat could neither work nor pull its own repair. Requiring the
    downstream policy call distinguishes a genuine scope allow from an early hook exit.
    """
    tmp, ws = make_workspace()
    stub = StubDaemon(scope_status={
        "plugin_id": "claude-code", "requests": [], "live_grants": [],
        "standing_grants": [{"path": ws, "granted_by": "operator",
                              "reason": "workspace root", "expires_at": None}],
        "generation": 1,
    })
    srv = Server(stub)
    try:
        target = os.path.join(ws, "granted", "ok.md")
        rc, err = run_hook("claude", ws,
                           _event("Bash", {"command": f"cat {target}"}),
                           srv.endpoint)
        check("claude-root-grant-allows", rc == 0, f"rc={rc} stderr={err}")
        check("claude-continued-to-policy", "hestia_begin_action" in stub.names(),
              stub.names())
        check("claude-fetched-standing-scope", "hestia_scope_status" in stub.names(),
              stub.names())
    finally:
        srv.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ---- the fetch itself: composition, thin daemon, unreachable daemon ----
def _load_mechanism_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sprintF_mech", os.path.join(SHARED, MECH))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_fetch_policy_snapshot_composes_from_daemon_surfaces():
    m = _load_mechanism_module()
    stub = StubDaemon(
        law={"identity": {"plugin_id": "kimi-code", "role": "role:constellation:pilot"},
             "law_hash": "h1", "operator_grant": {"preset": "safety"}},
        scope_status={"plugin_id": "kimi-code", "requests": [],
                      "live_grants": [{"path": "/mnt/x/y", "expires_at": 1}]})
    srv = Server(stub)
    try:
        m._discover_endpoint = lambda: srv.endpoint
        snap = m.fetch_policy_snapshot("kimi-code", use_cache=False)
        check("snap-present", isinstance(snap, dict), repr(snap))
        check("snap-role", snap["role"] == "role:constellation:pilot", str(snap))
        check("snap-law-hash", snap["law_hash"] == "h1", str(snap))
        check("snap-grant", snap["operator_grant"] == {"preset": "safety"}, str(snap))
        check("snap-in-scope", snap["in_scope"] == ["path:/mnt/x/y"], str(snap))
        check("snap-scope-grants", snap["scope_grants"] == ["/mnt/x/y"], str(snap))
        check("snap-source", snap["source"] == "daemon-live", str(snap))
        check("snap-in-scope-is-list", isinstance(snap["in_scope"], list), str(snap))
    finally:
        srv.close()


def test_fetch_policy_snapshot_thin_daemon_is_not_degraded_trigger():
    m = _load_mechanism_module()
    stub = StubDaemon(thin=True)
    srv = Server(stub)
    try:
        m._discover_endpoint = lambda: srv.endpoint
        snap = m.fetch_policy_snapshot("codex", use_cache=False)
        check("thin-present", isinstance(snap, dict),
              "a REACHABLE daemon lacking the surface must yield a THIN snapshot, not "
              "degraded — the ratified trigger is unreachability")
        check("thin-grants-nothing", snap["in_scope"] == [] and snap["role"] is None,
              str(snap))
    finally:
        srv.close()


def test_fetch_policy_snapshot_unreachable_is_none():
    m = _load_mechanism_module()
    m._discover_endpoint = lambda: DEAD
    check("dead-none", m.fetch_policy_snapshot("codex", use_cache=False) is None)
    m._discover_endpoint = lambda: None
    check("no-endpoint-none", m.fetch_policy_snapshot("codex", use_cache=False) is None)


# ---- ordering: gate-self classification survives the daemon being down ----
def test_gate_self_write_daemon_down_stays_gate_self():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            target = os.path.join(ws, "hestia", "plugins", shim, "hooks", HOOK)
            rc, err = run_hook(shim, ws, _event("Write", {"file_path": target,
                                                          "content": "x"}), DEAD)
            check(f"{shim}-refused", rc == 2, f"rc={rc} stderr={err}")
            check(f"{shim}-gate-self-not-degraded", "gate-self" in err, err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


ALL = [
    test_criterion5_daemon_down_degrades_deny_write_allow_read,
    test_criterion5_degraded_never_relaxes_egress,
    test_degraded_denies_are_recorded,
    test_differential_inputs_converge,
    test_ordinary_in_scope_write_allowed_with_live_snapshot,
    test_claude_workspace_root_standing_grant_admits_absolute_bash_path,
    test_fetch_policy_snapshot_composes_from_daemon_surfaces,
    test_fetch_policy_snapshot_thin_daemon_is_not_degraded_trigger,
    test_fetch_policy_snapshot_unreachable_is_none,
    test_gate_self_write_daemon_down_stays_gate_self,
]

if __name__ == "__main__":
    print("Sprint F — cutover: evaluate() from an authenticated path, or ratified degraded mode")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
