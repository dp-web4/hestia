#!/usr/bin/env python3
"""Exercise #1450's daemon-side gate evaluation through real MCP on a disposable daemon."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def unwrap(payload: dict) -> dict:
    result = payload.get("result") or {}
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = (result.get("content") or [{}])[0].get("text")
    if not text:
        raise RuntimeError(f"tool returned no content: {payload}")
    return json.loads(text)


def main(binary: str) -> int:
    with tempfile.TemporaryDirectory(prefix="hestia-gate-evaluate-") as tmp:
        home = Path(tmp)
        env = dict(os.environ, HESTIA_HOME=tmp, HESTIA_PASSPHRASE=secrets.token_hex(16))
        init = subprocess.run([binary, "init", "--ai"], env=env, capture_output=True, text=True, timeout=90)
        if init.returncode:
            raise RuntimeError(f"init failed: {init.stdout}\n{init.stderr}")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = (home / "daemon.log").open("w")
        daemon = subprocess.Popen([binary, "serve", "--bind", f"127.0.0.1:{port}"],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                if daemon.poll() is not None:
                    raise RuntimeError(f"daemon exited: {(home / 'daemon.log').read_text()}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=0.2):
                        break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("daemon did not become ready")
            spec = importlib.util.spec_from_file_location(
                "gate_evaluate_mechanism", ROOT / "plugins" / "_shared" / "hestia_gate_mechanism.py")
            mechanism = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mechanism
            spec.loader.exec_module(mechanism)
            mcp = mechanism._McpHttp(f"http://127.0.0.1:{port}/mcp", time.monotonic() + 90, request_cap=None)
            if "result" not in mcp.initialize():
                raise RuntimeError("initialize failed")
            mcp.initialized()
            tools = mcp._request({"jsonrpc": "2.0", "id": mcp._id(), "method": "tools/list", "params": {}})
            names = {t["name"] for t in (tools.get("result") or {}).get("tools") or []}
            if "hestia_gate_evaluate" not in names:
                raise RuntimeError("hestia_gate_evaluate is not advertised")
            connected = unwrap(mcp.call_tool("hestia_connect", {
                "plugin_id": "fixture-member", "host_agent": "gate-evaluate-mcp-test",
                "requested_role": "citizen",
            }))
            session = connected["sessionId"]
            denied = unwrap(mcp.call_tool("hestia_gate_evaluate", {
                "tool_name": "Bash", "command": "rm -rf /home/user/data", "session_id": session,
            }))
            if denied.get("decision") is not False or denied.get("context", {}).get("verdict") != "deny":
                raise RuntimeError(f"unexpected destructive-command verdict: {denied}")
            effects = denied["context"]["side_effects"]
            if any(effects.values()) or denied.get("permits") is not False:
                raise RuntimeError(f"query claims a side effect or permission: {denied}")
            if denied["context"].get("not_evaluated") != ["local_mrh_scope", "governance_closure", "egress"]:
                raise RuntimeError(f"unevaluated stages are not explicit: {denied}")
            allowed = unwrap(mcp.call_tool("hestia_gate_evaluate", {
                "tool_name": "Read", "target": "/fixture/book.txt", "session_id": session,
            }))
            if (allowed.get("decision") is not False
                    or allowed.get("society_law_allows") is not True
                    or allowed.get("context", {}).get("complete") is not False
                    or allowed.get("permits") is not False):
                raise RuntimeError(f"unexpected ordinary-read verdict: {allowed}")
            missing = unwrap(mcp.call_tool("hestia_gate_evaluate", {
                "tool_name": "Read", "target": "/fixture/book.txt",
            }))
            if missing.get("_hestia_error", {}).get("code") != "hestia.gate_evaluate_unattributed":
                raise RuntimeError(f"missing session was not refused by name: {missing}")
        finally:
            if daemon.poll() is None:
                daemon.terminate()
                try:
                    daemon.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait(timeout=5)
            log.close()
    print("gate-evaluate-mcp: ok")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: gate_evaluate_mcp_smoke.py <hestia-binary>")
    sys.exit(main(sys.argv[1]))
