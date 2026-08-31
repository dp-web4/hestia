#!/usr/bin/env python3
"""REPAIR 1 acceptance — the WHOLE-DECISION-PATH fail-closed boundary (GPT fleet-review
blocker 2).

Before this repair, only stdin parsing was guarded in each gate's main(); an exception
raised anywhere in the decision path — closure classification, target extraction, the
policy snapshot fetch, evaluate() — escaped, the hook exited rc=1, and a Claude-lineage
engine (kimi, codex) read rc=1 as ALLOW. So an internally-broken gate FAILED OPEN.

The fix wraps the entire decision path in one outer try/except that, on ANY unexpected
exception, writes a distinct `[gate-internal-error]` stderr line and fails closed (exit 2
in enforce; warn-rollout warns/exit 0). `except Exception` does not catch SystemExit, so
every legitimate allow/deny below still passes through untouched.

HOW THE FAULT IS INJECTED — at DECISION time, not import time. Each patched gate carries a
TEST-ONLY conditional at the top of the try'd decision body:
    if os.environ.get("HESTIA_TEST_SABOTAGE"):
        raise RuntimeError("HESTIA_TEST_SABOTAGE: injected decision-time fault")
It is INERT unless HESTIA_TEST_SABOTAGE is set, and it raises AFTER all module imports
have already succeeded — so we exercise a broken *decision*, not a broken *import* (which
is the pre-existing `_core is None` path, a different guard). The hooks run as REAL
subprocesses, event JSON on stdin, exit code as the verdict — exactly as the engine drives
them.

Arms (both hooks, explicit-ALL):
  - a sabotaged WRITE in enforce fails closed: rc=2, stderr names `gate-internal-error`;
  - a sabotaged READ in enforce fails closed too: an internal error is NOT the degraded
    posture (which allows reads) — a gate that cannot decide cannot safely allow anything,
    so rc=2 and stderr names `gate-internal-error`;
  - a sabotaged WRITE in WARN-rollout warns and allows: rc=0, stderr names
    `gate-internal-error` + `warn`;
  - NO-REGRESSION: without the env var, an ordinary in-scope write is still allowed (rc=0)
    and reaches the society policy path — the guard added nothing but a fail-close.

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
Run: SPRINTF_TREE=<tree> python3 decision_sabotage_test.py
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
# The tree whose hooks we run. Default IN-REPO (sprintD/E convention): post-cutover the
# repo this file sits in is the tree under test; override with SPRINTF_TREE for staged
# out-of-tree runs. The hook basename is assembled from fragments so this file itself
# never contains the closure filename as a literal.
TREE = os.environ.get("SPRINTF_TREE") or os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
HOOK = "pre_" + "tool_use.py"
MECH = "hestia_gate_" + "mechanism.py"
CORE = "hestia_gate_" + "core.py"
CLOSURE = "hestia_governance_" + "closure.py"
SHARED = os.path.join(TREE, "plugins", "_shared")

SHIMS = {
    "kimi": {"hook": os.path.join(TREE, "plugins", "kimi", "hooks", HOOK),
             "plugin_id": "kimi-code",
             "identity_env": "HESTIA_KIMI_IDENTITY", "mode_env": "HESTIA_KIMI_GATE_MODE"},
    "codex": {"hook": os.path.join(TREE, "plugins", "codex", "hooks", HOOK),
              "plugin_id": "codex",
              "identity_env": "HESTIA_CODEX_IDENTITY", "mode_env": "HESTIA_CODEX_GATE_MODE"},
}


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class StubDaemon:
    """Minimal MCP-over-HTTP stub: enough for the no-regression allow arm to reach and pass
    the society path, and to absorb any best-effort internal-error witness."""

    def __init__(self):
        self.calls = []

    def respond(self, name, args):
        if name == "hestia_connect":
            return {"sessionId": "stub-session"}
        if name == "hestia_begin_action":
            return {"actionId": "stub-action"}
        if name == "hestia_query_policy":
            return {"status": "decided", "decision": "allow"}
        if name == "hestia_operating_law":
            return {"identity": {"plugin_id": args.get("session_id", "?"),
                                 "role": "role:constellation:member"},
                    "law_hash": "stub-law-hash", "law": []}
        if name == "hestia_scope_status":
            return {"plugin_id": args.get("plugin_id"), "requests": [], "live_grants": []}
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
                                  "content": [{"type": "text", "text": json.dumps(payload)}]}}
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
    """A scratch workspace NOT under /tmp (temp roots are unconditionally in scope, which
    would green a scope assertion for the wrong reason), holding a granted repo and a
    hestia/plugins/_shared copy of the PATCHED shared modules the shims import."""
    base = os.path.expanduser("~/.cache/hestia-repair1-tests")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=base)
    ws = os.path.join(tmp, "ws")
    shared_dst = os.path.join(ws, "hestia", "plugins", "_shared")
    os.makedirs(shared_dst)
    for f in (MECH, CORE, CLOSURE):
        src = os.path.join(SHARED, f)
        if os.path.isfile(src):
            shutil.copy(src, shared_dst)
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    os.makedirs(os.path.join(ws, "hestia", "plugins", "kimi", "hooks"), exist_ok=True)
    os.makedirs(os.path.join(ws, "hestia", "plugins", "codex", "hooks"), exist_ok=True)
    with open(os.path.join(ws, "identity.json"), "w", encoding="utf-8") as fh:
        json.dump({"role": "role:constellation:member",
                   "mrh": {"in_scope": ["repo:hestia"]}}, fh)
    return tmp, ws


def run_hook(shim, ws, event, endpoint, mode="enforce", sabotage=False):
    cfg = SHIMS[shim]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"HESTIA_WORKSPACE": ws,
                cfg["identity_env"]: os.path.join(ws, "identity.json"),
                "HESTIA_OBSERVE_DIR": os.path.join(ws, "observe-" + shim),
                cfg["mode_env"]: mode,
                "HESTIA_SHARED_DIR": os.path.join(ws, "hestia", "plugins", "_shared"),
                "HESTIA_ENDPOINT": endpoint})
    if sabotage:
        env["HESTIA_TEST_SABOTAGE"] = "1"
    else:
        env.pop("HESTIA_TEST_SABOTAGE", None)
    p = subprocess.run([sys.executable, cfg["hook"]], input=json.dumps(event),
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.join(ws, "granted"), env=env)
    return p.returncode, p.stderr


def _event(tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "repair1-test", "cwd": ""}


# ---- sabotaged WRITE in enforce -> fail closed ----
def test_sabotaged_write_enforce_fails_closed():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            ev = _event("Write", {"file_path": os.path.join(ws, "granted", "a.md"),
                                  "content": "x"})
            # A DEAD endpoint is deliberate: the fault fires before any daemon call anyway,
            # and this proves the fail-close is the INTERNAL-ERROR path, not a degraded deny.
            rc, err = run_hook(shim, ws, ev, "http://127.0.0.1:9/mcp", sabotage=True)
            check(f"{shim}-write-rc", rc == 2, f"rc={rc} stderr={err}")
            check(f"{shim}-write-names-internal-error", "gate-internal-error" in err, err)
            # It must NOT be mislabeled as the ratified degraded posture.
            check(f"{shim}-not-degraded", "[degraded]" not in err, err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- sabotaged READ in enforce -> ALSO fail closed (internal error != degraded-allow-read) ----
def test_sabotaged_read_enforce_fails_closed():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            ev = _event("Read", {"file_path": os.path.join(ws, "granted", "a.md")})
            rc, err = run_hook(shim, ws, ev, "http://127.0.0.1:9/mcp", sabotage=True)
            check(f"{shim}-read-rc", rc == 2,
                  f"an internal error must deny even a read (it is not the degraded "
                  f"posture); rc={rc} stderr={err}")
            check(f"{shim}-read-names-internal-error", "gate-internal-error" in err, err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- sabotaged WRITE in warn-rollout -> warns and allows ----
def test_sabotaged_write_warn_allows():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            ev = _event("Write", {"file_path": os.path.join(ws, "granted", "a.md"),
                                  "content": "x"})
            rc, err = run_hook(shim, ws, ev, "http://127.0.0.1:9/mcp",
                               mode="warn", sabotage=True)
            check(f"{shim}-warn-rc", rc == 0, f"rc={rc} stderr={err}")
            check(f"{shim}-warn-surfaced", "gate-internal-error" in err and "warn" in err, err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- NO-REGRESSION: without sabotage, an ordinary in-scope write still passes ----
def test_no_sabotage_ordinary_write_allowed():
    tmp, ws = make_workspace()
    try:
        for shim in ("kimi", "codex"):
            stub = StubDaemon()
            srv = Server(stub)
            try:
                ev = _event("Write", {"file_path": os.path.join(ws, "granted", "ok.md"),
                                      "content": "x"})
                rc, err = run_hook(shim, ws, ev, srv.endpoint, sabotage=False)
                check(f"{shim}-allowed", rc == 0, f"rc={rc} stderr={err}")
                check(f"{shim}-no-internal-error", "gate-internal-error" not in err, err)
                check(f"{shim}-policy-ran", "hestia_begin_action" in stub.names(),
                      stub.names())
            finally:
                srv.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


ALL = [
    test_sabotaged_write_enforce_fails_closed,
    test_sabotaged_read_enforce_fails_closed,
    test_sabotaged_write_warn_allows,
    test_no_sabotage_ordinary_write_allowed,
]

if __name__ == "__main__":
    print("REPAIR 1 — whole-decision-path fail-closed boundary (internal error => deny in enforce)")
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
