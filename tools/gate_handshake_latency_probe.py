#!/usr/bin/env python3
"""Time the gate's per-tool-call daemon handshake, step by step, against the live daemon.

WHY: every fail-closed deny on this seat carries `cause=timeout` (73/73 as of 2026-08-06),
and the gate's message tells the member "the daemon is ALIVE BUT LOADED -- back off and
retry". That advice is only correct if the nominal handshake fits comfortably inside
TOTAL_BUDGET_MS (800) and the observed failures are excursions. If the nominal cost is
already a large fraction of the budget, the class is a MISPRICED BUDGET, not load, and
"back off and retry" is the wrong remedy -- retrying pays the same five round trips.

The gate does FIVE sequential round trips per tool call (pre_tool_use.py:2211-2270):
  initialize -> initialized -> hestia_connect -> hestia_begin_action -> hestia_query_policy
plus re-polls while status == "evaluating". This probe replays exactly that sequence with
the same payload shapes and reports per-step and total wall time.

POLICY-NEUTRAL, and it drains what it creates: it opens a session and begins an action
for a synthetic `Read` of a path under /tmp, queries policy (Allow -> the query itself
appends nothing), then CLOSES the action with `hestia_record_outcome` -- `s.actions` has
no other remover, so an unclosed probe action sits in the map the global lock protects
and every later run measures a more loaded daemon than the last (#316 review, Note A).
The close appends one "outcome" entry per run to the witness chain: honest accounting
for an action that was begun.

The session connects `synthetic: true` under a probe-specific plugin id, so trust
bookkeeping lands in a synthetic grain, no member LCT is minted, and no reputation
delta reaches the hub (state.rs: unmapped plugins never emit). The id is HARDCODED on
purpose -- `synthetic: true` durably persists a synthetic exclusion for whatever id it
rides with, so it must never be paired with a real member id like "claude-code". One
fidelity cost, stated: a synthetic connect persists that exclusion doc (a vault write)
on every connect, so `connect` reads heavier here than the real gate's member-registry
short-circuit; initialize/begin_action/query_policy are unchanged in shape.
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"


def endpoint() -> str:
    env = os.environ.get("HESTIA_MCP_ENDPOINT")
    if env:
        return env
    return ENDPOINT_FILE.read_text().strip()


class Client:
    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url
        self.timeout = timeout
        self.session = None
        self._id = 0

    def _post(self, method: str, params=None, notify: bool = False):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = self._id
        data = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            raw = resp.read().decode()
        if not raw.strip():
            return {}
        # the daemon may answer as SSE; take the last data: line
        if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
            payloads = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
            raw = payloads[-1] if payloads else "{}"
        return json.loads(raw)

    def call_tool(self, name: str, args: dict):
        return self._post("tools/call", {"name": name, "arguments": args})


def unwrap(resp):
    """Tool results arrive as content[0].text holding JSON."""
    try:
        content = resp["result"]["content"][0]["text"]
        return json.loads(content)
    except Exception:
        return resp.get("result", resp)


def one_run(url: str, role: str, plugin_id: str) -> dict:
    c = Client(url)
    steps = {}
    t_all = time.monotonic()

    t = time.monotonic()
    init = c._post("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "gate-handshake-probe", "version": "0"},
    })
    steps["initialize"] = (time.monotonic() - t) * 1000
    if "result" not in init:
        return {"error": f"initialize failed: {init}", "steps": steps}

    t = time.monotonic()
    c._post("notifications/initialized", {}, notify=True)
    steps["initialized"] = (time.monotonic() - t) * 1000

    t = time.monotonic()
    connect = unwrap(c.call_tool("hestia_connect", {
        "plugin_id": plugin_id,
        "plugin_version": "probe",
        "host_agent": "claude-code",
        "host_agent_version": "claude-code",
        "requested_role": "citizen",
        "protocol_version": PROTOCOL_VERSION,
        "role": role,
        "synthetic": True,
    }))
    steps["connect"] = (time.monotonic() - t) * 1000
    session_id = connect.get("sessionId") if isinstance(connect, dict) else None

    t = time.monotonic()
    begin = unwrap(c.call_tool("hestia_begin_action", {
        "tool_name": "Read",
        "target": "/tmp/gate-handshake-probe-target",
        "parameters": {"file_path": "/tmp/gate-handshake-probe-target"},
        **({"session_id": session_id} if session_id else {}),
    }))
    steps["begin_action"] = (time.monotonic() - t) * 1000
    action_id = begin.get("actionId") if isinstance(begin, dict) else None
    if not action_id:
        return {"error": f"begin_action gave no actionId: {begin}", "steps": steps}

    t = time.monotonic()
    polls = 0
    decision = None
    while polls < 4:
        polls += 1
        body = unwrap(c.call_tool("hestia_query_policy", {
            "action_id": action_id,
            **({"session_id": session_id} if session_id else {}),
        }))
        status = body.get("status", "decided") if isinstance(body, dict) else "decided"
        if status != "evaluating":
            decision = body
            break
        time.sleep(0.05)
    steps["query_policy"] = (time.monotonic() - t) * 1000
    steps["_polls"] = polls

    total = (time.monotonic() - t_all) * 1000

    # Close the action (untimed -- cleanup is not part of the gate sequence
    # under test, so it lands after `total` is taken). Best-effort: a failed
    # close must not turn a successful measurement into an error row.
    try:
        res = unwrap(c.call_tool("hestia_record_outcome", {
            "action_id": action_id, "success": True, "magnitude": 0.0,
        }))
        # A daemon rejection arrives as a parsed error envelope, not an
        # exception -- only the witness entry hash proves the action closed.
        steps["_outcome_recorded"] = isinstance(res, dict) and "witnessEntryHash" in res
    except Exception:  # noqa: BLE001
        steps["_outcome_recorded"] = False

    return {
        "total_ms": total,
        "steps": steps,
        "decision": (decision or {}).get("decision") if isinstance(decision, dict) else None,
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    url = endpoint()
    role = os.environ.get("HESTIA_ROLE", "role:constellation:member")
    # Hardcoded, not env-overridable: this id rides with `synthetic: true`,
    # which persists a durable synthetic EXCLUSION for it. An env override
    # (HESTIA_MESH_PLUGIN is "claude-code" on live seats) would let the probe
    # mark a real member synthetic. See the docstring.
    plugin_id = "gate-handshake-probe"
    print(f"endpoint={url} role={role} plugin={plugin_id} runs={n}")
    print(f"gate TOTAL_BUDGET_MS = {os.environ.get('HESTIA_PRE_TOTAL_BUDGET_MS', '800')}"
          f" (the deadline this whole sequence must fit inside)")
    rows = []
    for i in range(n):
        try:
            r = one_run(url, role, plugin_id)
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            r = {"error": f"{type(e).__name__}: {e}"}
        rows.append(r)
        if "error" in r:
            print(f"run {i+1}: ERROR {r['error']}")
        else:
            s = r["steps"]
            print(f"run {i+1}: total={r['total_ms']:7.1f}ms  "
                  f"init={s['initialize']:6.1f} inited={s['initialized']:6.1f} "
                  f"conn={s['connect']:6.1f} begin={s['begin_action']:6.1f} "
                  f"policy={s['query_policy']:6.1f} (polls={s['_polls']}) "
                  f"-> {r['decision']}")
    ok = [r for r in rows if "error" not in r]
    if ok:
        totals = sorted(r["total_ms"] for r in ok)
        budget = int(os.environ.get("HESTIA_PRE_TOTAL_BUDGET_MS", "800"))
        over = [t for t in totals if t > budget]
        print()
        print(f"n={len(totals)} min={totals[0]:.1f} median={totals[len(totals)//2]:.1f} "
              f"max={totals[-1]:.1f} ms")
        print(f"OVER the {budget}ms gate budget: {len(over)}/{len(totals)}")
        for step in ("initialize", "initialized", "connect", "begin_action", "query_policy"):
            vals = sorted(r["steps"][step] for r in ok)
            print(f"  {step:>13}: median {vals[len(vals)//2]:7.1f}ms  max {vals[-1]:7.1f}ms")
    print(f"errors: {len(rows) - len(ok)}/{len(rows)}")


if __name__ == "__main__":
    main()
