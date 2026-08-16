#!/usr/bin/env python3
"""Minimal MCP-over-HTTP client for the local hestia daemon.

A mesh-woken non-interactive session has no `hestia_*` tool in its harness surface. That
is not the same as the channel being unreachable: every daemon tool answers over plain
urllib at HESTIA_ENDPOINT. This is the transport, factored out of the probes that kept
re-inlining it (ref_daemon_reachable_urllib).

Do NOT use this for the four verbs the member-mesh CLI already wraps (connect,
member_inbox, member_notify, member_unanswered) -- the CLI carries hardcoded key names
and refusal-echo parsing that an inline send silently loses. Use it for the other 27.

    from claude_daemon_client import call
    call("hestia_gate_pending_escalations", {})
"""
from __future__ import annotations

import json
import os
import urllib.request

ENDPOINT = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
_session_id = None


def _post(body, extra_headers=None):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers)
    resp = urllib.request.urlopen(req, timeout=60)
    return resp, resp.read().decode()


def _unwrap(raw):
    """Responses are SSE. Keep-alive frames emit a BARE `data:` with no payload -- json
    them and you get 'Expecting value: line 1 column 1', which reads as a dead daemon."""
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload:
            continue
        obj = json.loads(payload)
        if "error" in obj:
            raise RuntimeError(obj["error"])
        content = (obj.get("result") or {}).get("content")
        if content and content[0].get("text"):
            try:
                return json.loads(content[0]["text"])
            except ValueError:
                return content[0]["text"]
        return obj.get("result", obj)
    raise RuntimeError(f"no data frame in response: {raw[:200]!r}")


def init():
    global _session_id
    if _session_id:
        return _session_id
    resp, _ = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "claude-probe", "version": "1"}}})
    _session_id = resp.headers.get("mcp-session-id")
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"},
          {"mcp-session-id": _session_id})
    return _session_id


def call(name, arguments=None):
    init()
    _, raw = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}}},
                   {"mcp-session-id": _session_id})
    return _unwrap(raw)


if __name__ == "__main__":
    import sys
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(call(sys.argv[1], args), indent=1))
