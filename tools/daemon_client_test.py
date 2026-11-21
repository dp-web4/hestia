#!/usr/bin/env python3
"""The tracked generic daemon client reaches tools, and failures reach its caller (#603).

Runs the real client against an in-process MCP stub. No live daemon is contacted and no
petition is opened. Success, a daemon refusal, an absent listener, and a malformed reply
are all distinct outcomes.
"""
from __future__ import annotations

import contextlib
import http.server
import io
import json
import os
import socket
import threading
import time
os.environ.setdefault("HESTIA_MESH_PLUGIN", "claude-code")

import daemon_client


class Stub:
    def __init__(self, payload=None, *, mode="ok", delay=0.0):
        self.payload = payload or {"sessionId": "s-603"}
        self.mode = mode
        self.delay = delay
        self.calls = []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = body.get("method")
                if method == "initialize":
                    return self._direct(body, {"protocolVersion": "2024-11-05"})
                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                if stub.delay:
                    time.sleep(stub.delay)
                params = body.get("params") or {}
                stub.calls.append((params.get("name"), params.get("arguments") or {}))
                if params.get("name") == "hestia_connect":
                    return self._sse(body, {"sessionId": "s-603"})
                if stub.mode == "no_frame":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b": keepalive\n\n")
                    return
                if stub.mode == "refusal":
                    return self._sse(body, {"_hestia_error": {
                        "code": "hestia.test.refusal", "message": "deliberate refusal"}})
                return self._sse(body, stub.payload)

            def _direct(self, body, result):
                raw = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "stub-session")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _sse(self, body, payload):
                result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                          "structuredContent": payload}
                raw = ("event: message\ndata: " + json.dumps({
                    "jsonrpc": "2.0", "id": body["id"], "result": result}) + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("mcp-session-id", "stub-session")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def invoke(tool: str, arguments: dict, url: str) -> tuple[int, dict, list]:
    env = dict(os.environ)
    os.environ.update({"HESTIA_MESH_PLUGIN": "claude-code", "HESTIA_ENDPOINT": url})
    old_ep = daemon_client._mesh.EP
    daemon_client._mesh.EP = url
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            rc = daemon_client.main([tool, json.dumps(arguments)])
    finally:
        daemon_client._mesh.EP = old_ep
        os.environ.clear()
        os.environ.update(env)
    return rc, json.loads(stdout.getvalue()), list(getattr(invoke, "calls", []))


def closed_url() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/mcp"


def test_generic_call_reaches_the_tool():
    stub = Stub({"ruling": "accepted"})
    try:
        rc, out, _ = invoke("hestia_appeal", {"deny_hash": "h", "reason": "false positive"}, stub.url)
        assert rc == 0, (rc, out)
        assert out == {"ruling": "accepted"}, out
        names = [name for name, _args in stub.calls]
        assert names == ["hestia_connect", "hestia_appeal"], names
        assert stub.calls[1][1]["reason"] == "false positive", stub.calls
        assert stub.calls[1][1]["session_id"] == "s-603", stub.calls
    finally:
        stub.close()


def test_refusal_reaches_the_caller_as_rc3():
    stub = Stub(mode="refusal")
    try:
        rc, out, _ = invoke("hestia_appeal", {"deny_hash": "h", "reason": "false positive"}, stub.url)
        assert rc == 3, (rc, out)
        assert out["_hestia_error"]["code"] == "hestia.test.refusal", out
    finally:
        stub.close()


def test_unreachable_is_rc1_not_a_traceback():
    rc, out, _ = invoke("hestia_appeal", {"deny_hash": "h", "reason": "false positive"}, closed_url())
    assert rc == 1, (rc, out)
    assert out["_hestia_error"]["code"] == "unreachable", out


def test_empty_reply_is_not_success():
    stub = Stub(mode="no_frame")
    try:
        rc, out, _ = invoke("hestia_appeal", {"deny_hash": "h", "reason": "false positive"}, stub.url)
        assert rc == 3, (rc, out)
        assert out["_hestia_error"]["code"] == "hestia_mesh.no_data_frame", out
    finally:
        stub.close()


if __name__ == "__main__":
    test_generic_call_reaches_the_tool()
    test_refusal_reaches_the_caller_as_rc3()
    test_unreachable_is_rc1_not_a_traceback()
    test_empty_reply_is_not_success()
    print("ok: tracked generic client reaches tools and exposes every failure class")
