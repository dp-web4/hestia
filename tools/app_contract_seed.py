#!/usr/bin/env python3
"""Give an ISOLATED daemon one witnessed member action, so the app contract has trust to read.

app/src-tauri/tests/operator_live.rs asserts the TrustView fields the app renders
(`legacy_level`, `derived_temperament`, `adjudicated_counts`, `derivation`). A daemon fresh
from `hestia init` has no trust grains, so that assertion would have nothing to check, and the
test refuses to pass vacuously. This drives one real member path through MCP, the way a gate
hook does: connect as a registered orchestrator (claude-code), begin a Read, query policy,
record the outcome. Used by ci.yml's `app-daemon contract (live)` job.

Refuses port 7711 (the live daemon): this writes a member session and chain entries.

Run: python3 tools/app_contract_seed.py --endpoint http://127.0.0.1:7797/mcp
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2025-06-18"


def parse_rpc(payload: str):
    payload = payload.strip()
    if payload.startswith("{"):
        return json.loads(payload)
    for line in payload.splitlines():
        if line.startswith("data:") and line[5:].strip().startswith("{"):
            return json.loads(line[5:].strip())
    return None


class Mcp:
    def __init__(self, endpoint: str):
        self.endpoint, self.sid, self.n = endpoint, None, 0

    def post(self, body: dict, notify: bool = False):
        hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            hdrs["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.endpoint, json.dumps(body).encode(), hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            self.sid = self.sid or r.headers.get("mcp-session-id")
            return None if notify else parse_rpc(r.read().decode("utf-8", "replace"))

    def tool(self, name: str, args: dict) -> dict:
        self.n += 1
        r = self.post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}) or {}
        res = r.get("result") or {}
        if isinstance(res.get("structuredContent"), dict):
            return res["structuredContent"]
        try:
            return json.loads(res["content"][0]["text"])
        except Exception:  # noqa: BLE001
            return {"_raw": r}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--member", default="claude-code")
    a = ap.parse_args(argv)
    if urllib.parse.urlparse(a.endpoint).port == 7711:
        print("refusing :7711 -- that is the live daemon; seed an isolated one", file=sys.stderr)
        return 2

    c = Mcp(a.endpoint)
    c.n += 1
    c.post({"jsonrpc": "2.0", "id": c.n, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "app-contract-seed", "version": "1"}}})
    c.post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, notify=True)
    conn = c.tool("hestia_connect", {
        "plugin_id": a.member, "host_agent": "app-contract-seed", "requested_role": "citizen",
        "protocol_version": PROTOCOL_VERSION, "instance_name": "app-contract",
        "host_session_id": f"app-contract-{int(time.time())}"})
    sid = conn.get("sessionId")
    if not sid:
        print(f"connect gave no sessionId: {str(conn)[:300]}", file=sys.stderr)
        return 1
    begun = c.tool("hestia_begin_action", {
        "session_id": sid, "tool_name": "Read", "target": "/tmp/app-contract/seed.txt",
        "parameters": {"file_path": "/tmp/app-contract/seed.txt"}})
    aid = begun.get("actionId")
    if not aid:
        print(f"begin_action gave no actionId: {str(begun)[:300]}", file=sys.stderr)
        return 1
    c.tool("hestia_query_policy", {"action_id": aid})
    out = c.tool("hestia_record_outcome", {"action_id": aid, "success": True, "magnitude": 0.1})
    print(f"seeded one witnessed {a.member} action (session {sid}, action {aid}): {str(out)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
