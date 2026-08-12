#!/usr/bin/env python3
"""Shared in-process daemon-query mechanism — the society-safety verdict path.

PRD gate-consolidation §6.E (the shared TRANSPORT / mechanism module). Extracted from the
claude-code adapter's tested client so every harness can obtain a society-safety verdict
IN-PROCESS — no subprocess spawn, no cross-mount re-import of a 2760-line gate. This is what
lets a shim be *thin* and closes the criterion-10 timeout asymmetry: kimi/codex were reaching
the verdict by forking the whole claude gate off the slow /mnt/c mount, cold, every call, and
that path could not complete inside budget (issue: kimi still timed out 2026-08-12).

This is the MECHANISM, deliberately distinct from the LAW core (hestia_gate_core, which is
transport-free and must never open a socket). The mechanism MAY talk to the daemon; the law
may not. Keep that boundary: scope/egress/policy predicates belong in the core, the daemon
round-trip belongs here.

FAIL-CLOSED CONTRACT (load-bearing — read before editing):
  query_society_safety NEVER returns allow on an error, timeout, malformed response, or any
  exception. On any failure it returns SafetyVerdict(allow=False, decided=False, cause=...),
  and the caller fails closed (exit 2). Every Claude-lineage hook engine (Claude, Kimi, Codex,
  Cursor) fails OPEN on a hook crash, so a mechanism that returned allow-on-error — or that let
  an exception escape — would silently UN-GOVERN the member. Every path that could fail resolves
  to "not allowed, no verdict"; the top-level entry catches everything.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ── Budget / timeout contract (env-overridable; shared by every adopting shim) ───────────────
# Same knobs and defaults as the claude adapter, ON PURPOSE: raising the budget now raises it
# fleet-wide instead of in one copy (the #353 drift this consolidation removes).
TOTAL_BUDGET_MS = int(os.environ.get("HESTIA_PRE_TOTAL_BUDGET_MS", "800"))
REQUEST_TIMEOUT_S = float(os.environ.get("HESTIA_PRE_REQUEST_TIMEOUT_S", "5.0"))
MAX_POLLS = 5
MIN_POLL_SLEEP_MS = 50
PROTOCOL_VERSION = 1
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"


@dataclass
class SafetyVerdict:
    """Result of a society-safety query. `allow` is the ONLY field a caller acts on to proceed.

    allow=True   -> daemon returned allow, warn, or audit-only-deny: the act may proceed.
    allow=False  -> an enforced daemon deny (decided=True) OR no verdict at all
                    (decided=False, an infrastructure failure). The caller fails closed either way.
    `decided` distinguishes a real verdict from infra failure so the caller can render the two
    differently and so infra failures are never scored as member conduct.
    """
    allow: bool
    decided: bool
    message: str
    cause: str = "unknown"   # when not decided: "timeout" | "refused" | "unknown"


# ── MCP-over-HTTP client (in-process; MAY open a socket — mechanism, not law) ─────────────────
def _parse_json_or_sse(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if body and body.startswith("{"):
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    continue
    return {}


def _unwrap_tool_result(rpc_response: dict) -> dict:
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                return json.loads(block.get("text", ""))
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


class _McpHttp:
    def __init__(self, endpoint: str, deadline: float) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0
        self.deadline = deadline  # monotonic time after which we give up

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _remaining_s(self) -> float:
        return max(0.05, self.deadline - time.monotonic())

    def _request(self, body: dict, *, is_notification: bool = False) -> Optional[dict]:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        timeout = min(REQUEST_TIMEOUT_S, self._remaining_s())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not self.session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            if is_notification:
                return None
            payload = resp.read().decode("utf-8", errors="replace")
        return _parse_json_or_sse(payload)

    def initialize(self) -> dict:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "hestia-shared-gate", "version": "1"}},
        }) or {}

    def initialized(self) -> None:
        self._request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                      is_notification=True)

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def _discover_endpoint() -> Optional[str]:
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    try:
        v = (home / "endpoint").read_text().strip()
        return v or None
    except OSError:
        return None


def _extract_target(tool_input: Any, tool_name: str) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    if tool_name in {"Bash", "Shell"}:
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            return cmd.split()[0]
    return None


def _poll_policy(client: _McpHttp, action_id: str, session_id: Optional[str],
                 deadline: float) -> Optional[dict]:
    """Call hestia_query_policy, honoring the wait protocol. Returns the decided payload or
    None (ran out of polls / budget / error). None -> caller fails closed."""
    for _ in range(MAX_POLLS):
        if time.monotonic() >= deadline:
            return None
        args: dict = {"action_id": action_id}
        if session_id:
            args["session_id"] = session_id
        body = _unwrap_tool_result(client.call_tool("hestia_query_policy", args))
        if "_hestia_error" in body:
            return None
        status = body.get("status", "decided")
        if status == "decided":
            return body
        if status != "evaluating":
            return body  # unknown status -> treat as decided (matches the claude adapter)
        next_poll_ms = body.get("nextPollMs")
        if not isinstance(next_poll_ms, int) or next_poll_ms < 0:
            next_poll_ms = 200
        sleep_ms = max(MIN_POLL_SLEEP_MS, next_poll_ms)
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        sleep_ms = min(sleep_ms, remaining_ms)
        if sleep_ms <= 0:
            return None
        time.sleep(sleep_ms / 1000.0)
    return None


def _interpret(decision: dict) -> SafetyVerdict:
    """Map a daemon PolicyResult dict to a SafetyVerdict. Mirrors the claude adapter's
    emit_decision EXACTLY — the verdict field is decision['decision'] (NOT 'verdict'/'effect')."""
    verdict = decision.get("decision", "allow")
    enforced = bool(decision.get("enforced", True))
    reason = decision.get("reason", "")
    rule_name = decision.get("ruleName")
    label = f" [{rule_name}]" if rule_name else ""
    if verdict == "deny" and enforced:
        guidance = decision.get("guidance")
        return SafetyVerdict(allow=False, decided=True,
                             message=(guidance or f"hestia: deny{label} — {reason}"))
    if verdict == "warn":
        return SafetyVerdict(allow=True, decided=True, message=f"hestia: warn{label} — {reason}")
    if verdict == "deny" and not enforced:
        return SafetyVerdict(allow=True, decided=True,
                             message=f"hestia: would-deny (audit-only){label} — {reason}")
    return SafetyVerdict(allow=True, decided=True, message="")


def _no_verdict(plugin_id: str, tool_name: str, cause: str, detail: str) -> SafetyVerdict:
    """Compose the fail-closed 'no verdict' result and record the infra failure (never scored as
    member conduct). NEVER raises."""
    remedy = {
        "timeout": ("The daemon did not answer within the gate's budget — most likely ALIVE BUT "
                    "LOADED, not down. Wait and retry with backoff; if it persists across "
                    "minutes, report to your operator."),
        "refused": ("Nothing is listening on the daemon endpoint, so no action can be approved. "
                    "Report this to your operator and wait — retrying will not help."),
    }.get(cause, ("The gate could not obtain a verdict and cannot tell whether the daemon is down "
                  "or slow. Retry once with backoff; if it repeats, report to your operator."))
    msg = (f"hestia: no verdict [fail-closed] — the policy daemon did not return a decision "
           f"({detail}; cause={cause}). This is NOT a policy boundary and NOT a tool failure — the "
           f"referee is unreachable, so the gate fails closed for safety. {remedy}")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from hestia_gate_core import record_gate_unavailable  # type: ignore
        record_gate_unavailable(plugin_id, tool_name, cause, detail, home=str(DEFAULT_HESTIA_HOME))
    except Exception:
        pass
    return SafetyVerdict(allow=False, decided=False, message=msg, cause=cause)


def query_society_safety(event: dict, *, plugin_id: str, host_agent: str,
                         host_session_id: Optional[str] = None) -> SafetyVerdict:
    """Obtain the daemon's society-safety verdict for a write/exec act, IN-PROCESS.

    This replaces "spawn the claude gate as a subprocess" for a thin shim. Returns a
    SafetyVerdict; NEVER raises; on any failure yields allow=False, decided=False (fail-closed).
    """
    tool_name = event.get("tool_name") or "?"
    tool_input = event.get("tool_input") or {}
    try:
        endpoint = _discover_endpoint()
        if endpoint is None:
            return _no_verdict(plugin_id, tool_name, "refused", "no daemon endpoint discovered")
        deadline = time.monotonic() + (TOTAL_BUDGET_MS / 1000.0)
        target = _extract_target(tool_input, tool_name)
        client = _McpHttp(endpoint, deadline)
        init = client.initialize()
        if "result" not in init:
            return _no_verdict(plugin_id, tool_name, "unknown", "initialize failed")
        client.initialized()
        connect_args: dict = {
            "plugin_id": plugin_id,
            "plugin_version": "shared-mechanism",
            "host_agent": host_agent,
            "host_agent_version": host_agent,
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
        }
        role = os.environ.get("HESTIA_ROLE")
        if role:
            connect_args["role"] = role
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        connect = _unwrap_tool_result(client.call_tool("hestia_connect", connect_args))
        if "_hestia_error" in connect:
            return _no_verdict(plugin_id, tool_name, "unknown", "connect rejected")
        session_id = connect.get("sessionId")
        begin_args: dict = {
            "tool_name": tool_name,
            "target": target,
            "parameters": dict(tool_input) if isinstance(tool_input, dict) else {},
        }
        if session_id:
            begin_args["session_id"] = session_id
        if host_session_id:
            begin_args["host_session_id"] = host_session_id
        begin = _unwrap_tool_result(client.call_tool("hestia_begin_action", begin_args))
        if "_hestia_error" in begin:
            return _no_verdict(plugin_id, tool_name, "unknown", "begin_action rejected")
        action_id = begin.get("actionId")
        if not action_id:
            return _no_verdict(plugin_id, tool_name, "unknown", "begin_action missing actionId")
        decision = _poll_policy(client, action_id, session_id, deadline)
        if decision is None:
            return _no_verdict(plugin_id, tool_name, "timeout",
                               "query_policy never decided within budget")
        return _interpret(decision)
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(e, socket.timeout):
            cause = "timeout"
        elif isinstance(reason, ConnectionRefusedError):
            cause = "refused"
        else:
            cause = "unknown"
        return _no_verdict(plugin_id, tool_name, cause, f"network: {type(e).__name__}")
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED: any unexpected error is no-verdict, never allow
        return _no_verdict(plugin_id, tool_name, "unknown", f"unexpected: {type(e).__name__}")
