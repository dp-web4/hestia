#!/usr/bin/env python3
"""The outcome witness counts an outcome as recorded ONLY on a validated daemon receipt (#1149 review).

GPT reproduced, against the real `witness_one` with a cached action id, three transport-shaped
replies to `hestia_record_outcome` that the witness reported as "recorded":
  (1) an outer JSON-RPC error (-32603);
  (2) `result.isError = true` with a text error;
  (3) an empty result `{}`.
`_unwrap_tool_result` reduced each to `{}`, and the absence of `_hestia_error` read as success.
`run()` then retired the correlation file, and `spool_drain()` unlinked the queued row, so the
only evidence of the act was destroyed while the witness claimed it had landed.

The contract pinned here, end to end through `run()` and `spool_drain()` against a stub daemon (no
mocks of `witness_one` alone):
  - RECORDED means the daemon returned its receipt: a non-empty `witnessEntryHash`
    (`handler.rs` `tool_record_outcome`: `{"witnessEntryHash", "updatedTrustState"}`);
  - REJECTED means the daemon RULED: a structured `_hestia_error` carrying a `code`. Only then
    is the row dropped, because replaying a ruling never succeeds;
  - everything else (outer RPC error, MCP isError, empty or unreadable) is TRANSIENT: the act's
    identity survives in a spool row, and a queued row stays queued;
  - a connect that yields no `sessionId` records nothing and spools the act.

Negative control: every arm below is red on the head before this change (9795962).

Run:  python3 plugins/_shared/hestia_witness_receipt_test.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hestia_witness_core as core  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


class Daemon:
    """A stub daemon whose reply to record_outcome (and to connect) is chosen per case."""

    def __init__(self) -> None:
        self.record_mode = "ok"
        self.connect_mode = "ok"
        self.calls: list[tuple[str, dict]] = []
        daemon = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                method = body.get("method")
                if method == "initialize":
                    reply = {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2024-11-05"}}
                else:
                    name, args = body["params"]["name"], body["params"]["arguments"]
                    daemon.calls.append((name, args))
                    reply = daemon.reply(name, body["id"])
                out = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "M-1")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/mcp"

    def reply(self, name: str, rid) -> dict:
        def ok(payload):
            return {"jsonrpc": "2.0", "id": rid, "result": {"structuredContent": payload}}
        if name == "hestia_connect":
            if self.connect_mode == "no_session":
                return ok({"assignedRole": "citizen"})
            return ok({"sessionId": "S-1"})
        if name == "hestia_begin_action":
            return ok({"actionId": "COLD-1"})
        if name == "hestia_record_outcome":
            m = self.record_mode
            if m == "rpc_error":
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "internal error"}}
            if m == "is_error":
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "isError": True, "content": [{"type": "text", "text": "Tool hestia_record_outcome failed: disk full"}]}}
            if m == "empty":
                return {"jsonrpc": "2.0", "id": rid, "result": {}}
            if m == "ruled":
                return ok({"_hestia_error": {"code": "hestia.bad_request", "message": "no"}})
            return ok({"witnessEntryHash": "abc123", "updatedTrustState": {}})
        return ok({})

    def named(self, name: str) -> list[dict]:
        return [a for n, a in self.calls if n == name]


def spool_rows() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(core.SPOOL_DIR.glob("*.json"))]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["HESTIA_STATE_DIR"] = str(Path(tmp) / "state")
        os.environ.pop("HESTIA_HOME", None)
        os.environ["HESTIA_WITNESS_TIMEOUT_S"] = "2"
        core.configure(plugin_id="claude-code")
        core.ACTIONS_DIR = Path(tmp) / "actions"
        daemon = Daemon()
        os.environ["HESTIA_ENDPOINT"] = daemon.endpoint

        def reset():
            daemon.calls.clear()
            for p in core.SPOOL_DIR.glob("*.json") if core.SPOOL_DIR.exists() else []:
                p.unlink()

        def post(tu):
            return {"hook_event_name": "PostToolUse", "session_id": "host-1", "tool_name": "Bash",
                    "tool_input": {"command": "ls"}, "tool_use_id": tu, "tool_response": {}}

        print("A. run(): a non-receipt reply never discards the act's identity")
        for mode in ("rpc_error", "is_error", "empty"):
            reset()
            daemon.record_mode = mode
            tu = f"tu-{mode}"
            core.cache_authorized_action(tu, f"GATED-{mode}", "Bash")
            core.run(post(tu))
            rows = spool_rows()
            cached = core.cached_action_id(tu)
            spooled = [r.get("action_id") for r in rows]
            check(f"A {mode}: the record_outcome was attempted", len(daemon.named("hestia_record_outcome")) == 1,
                  json.dumps(daemon.calls))
            check(f"A {mode}: the authorized action id survives (cache or spool)",
                  cached == f"GATED-{mode}" or f"GATED-{mode}" in spooled, f"cache={cached} spool={spooled}")
            check(f"A {mode}: the act is queued for retry, not reported recorded",
                  f"GATED-{mode}" in spooled, f"spool={spooled}")

        print("B. run(): a validated receipt, and only that, retires the correlation file")
        reset()
        daemon.record_mode = "ok"
        core.cache_authorized_action("tu-ok", "GATED-ok", "Bash")
        core.run(post("tu-ok"))
        check("B ok: the correlation file is retired", core.cached_action_id("tu-ok") is None)
        check("B ok: nothing is spooled", spool_rows() == [], json.dumps(spool_rows()))
        reset()
        daemon.record_mode = "ruled"
        core.cache_authorized_action("tu-ruled", "GATED-ruled", "Bash")
        core.run(post("tu-ruled"))
        check("B ruled: a structured daemon ruling is final (retired, not spooled)",
              core.cached_action_id("tu-ruled") is None and spool_rows() == [], json.dumps(spool_rows()))

        print("C. spool_drain(): a queued row leaves the queue only on a receipt or a ruling")
        for mode in ("rpc_error", "is_error", "empty"):
            reset()
            daemon.record_mode = mode
            core.spool_save({"tool_name": "Bash", "target": "ls", "success": True, "magnitude": 0.8,
                             "error": None, "host_session_id": "host-1", "client_ts": 1.0,
                             "action_id": f"Q-{mode}"})
            client = core._McpHttp(daemon.endpoint)
            client.initialize()
            core.spool_drain(client, "S-1")
            check(f"C {mode}: the queued row is still queued",
                  [r.get("action_id") for r in spool_rows()] == [f"Q-{mode}"], json.dumps(spool_rows()))
        reset()
        daemon.record_mode = "ok"
        core.spool_save({"tool_name": "Bash", "target": "ls", "success": True, "magnitude": 0.8,
                         "error": None, "host_session_id": "host-1", "client_ts": 1.0, "action_id": "Q-ok"})
        client = core._McpHttp(daemon.endpoint)
        client.initialize()
        core.spool_drain(client, "S-1")
        check("C ok: a receipted row leaves the queue", spool_rows() == [], json.dumps(spool_rows()))

        print("D. connect: no sessionId, no witnessing")
        reset()
        daemon.record_mode = "ok"
        daemon.connect_mode = "no_session"
        core.cache_authorized_action("tu-nosess", "GATED-nosess", "Bash")
        core.run(post("tu-nosess"))
        check("D the act is not recorded without a session", daemon.named("hestia_record_outcome") == [],
              json.dumps(daemon.calls))
        check("D the act is spooled with its identity",
              "GATED-nosess" in [r.get("action_id") for r in spool_rows()], json.dumps(spool_rows()))
        daemon.connect_mode = "ok"
        daemon.server.shutdown()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
