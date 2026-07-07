#!/usr/bin/env python3
"""Hestia PreToolUse hook for Claude Code — synchronous policy gate.

Wired from .claude-plugin/plugin.json as the PreToolUse hook. Reads the
hook event JSON from stdin, asks the local Hestia daemon for a policy
decision, and exits with the appropriate code to allow / warn / deny
the tool call.

DESIGN
- **Synchronous on Claude Code's critical path.** Unlike the
  PostToolUse witness hook (fire-and-forget), this one MUST block until
  the daemon answers, because Claude Code uses the exit code to decide
  whether to run the tool.
- **Short budget.** Total deadline is `TOTAL_BUDGET_MS` (default 800 ms).
  If the daemon hasn't returned a `decided` verdict by then, we fall
  back to the local heuristic engine (the legacy `web4-governance`
  plugin's pre_tool_use.py).
- **Wait protocol (spec §3.4.1).** If the daemon returns
  `status: "evaluating"` with `nextPollMs: N`, we sleep N ms and
  re-query — up to `MAX_POLLS` times. Useful when (future) LLM-backed
  policy entities need a moment.
- **Action cache.** On a decision we store the action_id under
  /tmp/hestia-actions/<tool_use_id>.json so the PostToolUse hook can
  pair the outcome to the begin_action.
- **Exit semantics for Claude Code:**
    - `exit 0` (silent)               — allow, no message
    - `exit 0` with stderr message    — warn, surfaced to the agent
    - `exit 2` with stderr message    — DENY, Claude Code blocks the tool

ENV
  HESTIA_HOOK_DEBUG=1            log to ~/.hestia-claude/hook.log
  HESTIA_PRE_FAIL_CLOSED=1       fail-CLOSED profile for governed roles:
                                  any path that cannot get a daemon verdict
                                  (daemon unreachable, budget exhausted,
                                  unexpected error) DENIES the tool instead
                                  of allowing. The legacy fallback is skipped
                                  entirely — the daemon is the law.
  HESTIA_PRE_NO_FALLBACK=1       disable the legacy-engine fallback
                                  (deny-on-daemon-unreachable instead)
  HESTIA_PRE_TOTAL_BUDGET_MS     override TOTAL_BUDGET_MS
  HESTIA_ENDPOINT                override endpoint discovery
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple

# ---- Config -----------------------------------------------------------

PLUGIN_ID = "claude-code"
HOST_AGENT = "claude-code"
PROTOCOL_VERSION = 1
HOOK_VERSION = "0.0.2"

STATE_DIR = Path.home() / ".hestia-claude"
ACTIONS_DIR = Path("/tmp/hestia-actions")
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"
DEFAULT_ENDPOINT = "http://127.0.0.1:7711/mcp"

# Total time budget across all daemon round-trips + re-polls.
TOTAL_BUDGET_MS = int(os.environ.get("HESTIA_PRE_TOTAL_BUDGET_MS", "800"))
# Per-request HTTP timeout.
REQUEST_TIMEOUT_S = 0.5
# Cap on re-poll iterations during the "evaluating" wait protocol.
MAX_POLLS = 5
# Floor on poll sleep to avoid busy loops if daemon misbehaves.
MIN_POLL_SLEEP_MS = 50

# Path to the legacy fallback hook. Sourced from the same code we ported,
# but kept in-place under claude-code/plugins/ for fallback robustness.
LEGACY_FALLBACK = (
    "/mnt/c/exe/projects/ai-agents/claude-code/plugins/web4-governance/hooks/pre_tool_use.py"
)


def debug_log(msg: str) -> None:
    if os.environ.get("HESTIA_HOOK_DEBUG") != "1":
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "hook.log").open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} pre  {msg}\n")
    except OSError:
        pass


def discover_endpoint() -> Optional[str]:
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    try:
        v = (home / "endpoint").read_text().strip()
        return v or None
    except OSError:
        return None


def extract_target(tool_input: Any, tool_name: str) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    if tool_name in {"Bash", "Shell"}:
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            # First token = the executable
            return cmd.split()[0]
    return None


# ---- Tiny MCP-over-HTTP client (same shape as the witness hook) -------

class McpHttp:
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

    def _request(self, body: dict[str, Any], *, is_notification: bool = False) -> Optional[dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
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
        return parse_json_or_sse(payload)

    def initialize(self) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": PLUGIN_ID, "version": HOOK_VERSION},
            },
        }) or {}

    def initialized(self) -> None:
        self._request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            is_notification=True,
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def parse_json_or_sse(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
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


def unwrap_tool_result(rpc_response: dict[str, Any]) -> dict[str, Any]:
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    return {}


# ---- Daemon path ------------------------------------------------------

def ask_daemon(
    tool_name: str,
    tool_input: Any,
    tool_use_id: str,
    host_session_id: Optional[str] = None,
) -> Optional[Tuple[dict[str, Any], str]]:
    """Returns (decision_dict, action_id) on success, None on any failure
    or timeout. decision_dict has the shape from spec §3.4."""
    endpoint = discover_endpoint()
    if endpoint is None:
        debug_log("no endpoint discovered; daemon path skipped")
        return None

    deadline = time.monotonic() + (TOTAL_BUDGET_MS / 1000.0)
    target = extract_target(tool_input, tool_name)
    full_command: Optional[str] = None
    if tool_name in {"Bash", "Shell"} and isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            full_command = cmd

    client = McpHttp(endpoint, deadline)
    try:
        init = client.initialize()
        if "result" not in init:
            debug_log(f"initialize failed: {init}")
            return None
        client.initialized()

        # connect
        connect_args: dict[str, Any] = {
            "plugin_id": PLUGIN_ID,
            "plugin_version": HOOK_VERSION,
            "host_agent": HOST_AGENT,
            "host_agent_version": "claude-code",
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
        }
        # Optional constellation role. Absent env → omit → daemon defaults to
        # role:constellation:member. (Distinct from the legacy requested_role.)
        role = os.environ.get("HESTIA_ROLE")
        if role:
            connect_args["role"] = role
        connect_resp = client.call_tool("hestia_connect", connect_args)
        connect = unwrap_tool_result(connect_resp)
        if "_hestia_error" in connect:
            debug_log(f"connect rejected: {connect['_hestia_error']}")
            return None
        session_id = connect.get("sessionId")

        # begin_action — daemon stores parameters so query_policy can use full_command
        parameters: dict[str, Any] = {}
        if isinstance(tool_input, dict):
            parameters = dict(tool_input)
        begin_args: dict[str, Any] = {
            "tool_name": tool_name,
            "target": target,
            "parameters": parameters,
            **({"session_id": session_id} if session_id else {}),
        }
        # Thread Claude Code's own session id as the audit grain. The daemon
        # records it on the witnessed outcome/policy_decision events.
        if host_session_id:
            begin_args["host_session_id"] = host_session_id
        begin_resp = client.call_tool("hestia_begin_action", begin_args)
        begin = unwrap_tool_result(begin_resp)
        if "_hestia_error" in begin:
            debug_log(f"begin_action rejected: {begin['_hestia_error']}")
            return None
        action_id = begin.get("actionId")
        if not action_id:
            debug_log(f"begin_action missing actionId: {begin}")
            return None

        # query_policy with wait-protocol re-poll
        decision = poll_policy(client, action_id, session_id, deadline)
        if decision is None:
            debug_log("query_policy never reached 'decided' within budget")
            return None
        return (decision, action_id)
    except urllib.error.URLError as e:
        debug_log(f"network: {e}")
        return None
    except Exception as e:  # noqa: BLE001 — fail-open path; legacy fallback will catch
        debug_log(f"unexpected: {type(e).__name__}: {e}")
        return None


def poll_policy(
    client: McpHttp,
    action_id: str,
    session_id: Optional[str],
    deadline: float,
) -> Optional[dict[str, Any]]:
    """Call hestia_query_policy and handle the wait protocol. Returns the
    final `decided` payload, or None if we ran out of polls / budget."""
    for poll in range(MAX_POLLS):
        if time.monotonic() >= deadline:
            return None
        args: dict[str, Any] = {"action_id": action_id}
        if session_id:
            args["session_id"] = session_id
        resp = client.call_tool("hestia_query_policy", args)
        body = unwrap_tool_result(resp)
        if "_hestia_error" in body:
            debug_log(f"query_policy error: {body['_hestia_error']}")
            return None
        status = body.get("status", "decided")
        if status == "decided":
            return body
        if status != "evaluating":
            debug_log(f"unknown status {status!r}; treating as decided")
            return body
        next_poll_ms = body.get("nextPollMs")
        if not isinstance(next_poll_ms, int) or next_poll_ms < 0:
            next_poll_ms = 200
        sleep_ms = max(MIN_POLL_SLEEP_MS, next_poll_ms)
        # Cap sleep at remaining budget.
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        sleep_ms = min(sleep_ms, remaining_ms)
        if sleep_ms <= 0:
            return None
        debug_log(f"evaluating; sleeping {sleep_ms}ms before re-poll {poll + 2}")
        time.sleep(sleep_ms / 1000.0)
    return None


def cache_action(tool_use_id: str, action_id: str, tool_name: str) -> None:
    try:
        ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        (ACTIONS_DIR / f"{tool_use_id}.json").write_text(
            json.dumps({"action_id": action_id, "tool_name": tool_name, "ts": time.time()})
        )
    except OSError as e:
        debug_log(f"action cache failed: {e}")


# ---- Legacy fallback --------------------------------------------------

def fail_closed() -> bool:
    return os.environ.get("HESTIA_PRE_FAIL_CLOSED") == "1"


def deny_no_verdict(why: str) -> int:
    """Fail-closed refusal: no daemon verdict → the tool does not run."""
    sys.stderr.write(f"hestia: deny [fail-closed] — no policy verdict ({why})\n")
    debug_log(f"fail-closed deny: {why}")
    return 2


def invoke_legacy_fallback(stdin_payload: str) -> int:
    """Spawn the legacy web4-governance pre_tool_use.py with the same
    stdin and return its exit code. Returns 0 if the legacy script
    isn't available (fail-open), unless HESTIA_PRE_NO_FALLBACK=1 asked
    for deny-on-daemon-unreachable."""
    if os.environ.get("HESTIA_PRE_NO_FALLBACK") == "1":
        # Used to fall OPEN here despite the documented deny semantics
        # (GPT security review HST-004 / doc-code mismatch).
        return deny_no_verdict("daemon unreachable, legacy fallback disabled")
    if not os.path.exists(LEGACY_FALLBACK):
        debug_log(f"legacy fallback not found at {LEGACY_FALLBACK}; allowing")
        return 0
    try:
        proc = subprocess.run(
            ["python3", LEGACY_FALLBACK],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        # Forward legacy's stderr so Claude Code surfaces it to the user.
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        debug_log(f"legacy fallback exit={proc.returncode}")
        return proc.returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        debug_log(f"legacy fallback failed: {e}; allowing")
        return 0


# ---- Main flow --------------------------------------------------------

def emit_decision(decision: dict[str, Any]) -> int:
    """Translate a Hestia PolicyResult-shaped dict into a Claude Code
    hook exit code (with side-effect stderr)."""
    verdict = decision.get("decision", "allow")
    enforced = bool(decision.get("enforced", True))
    reason = decision.get("reason", "")
    rule_name = decision.get("ruleName")
    label = f" [{rule_name}]" if rule_name else ""

    if verdict == "deny" and enforced:
        sys.stderr.write(f"hestia: deny{label} — {reason}\n")
        return 2
    if verdict == "warn":
        sys.stderr.write(f"hestia: warn{label} — {reason}\n")
        return 0
    if verdict == "deny" and not enforced:
        # audit-only mode: surface the would-be denial as a warning.
        sys.stderr.write(f"hestia: would-deny (audit-only){label} — {reason}\n")
        return 0
    return 0


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        if fail_closed():
            return deny_no_verdict(f"unparseable hook event: {e}")
        debug_log(f"bad json: {e}; allowing")
        return 0

    tool_name = event.get("tool_name") or "?"
    # Claude Code's own stable session id — the real per-session audit grain.
    host_session_id = event.get("session_id")
    tool_use_id = event.get("tool_use_id") or event.get("session_id") or "no-id"
    tool_input = event.get("tool_input") or {}

    # Try the daemon first.
    result = ask_daemon(tool_name, tool_input, tool_use_id, host_session_id)
    if result is not None:
        decision, action_id = result
        cache_action(tool_use_id, action_id, tool_name)
        debug_log(
            f"daemon decided: {tool_name} → {decision.get('decision')} "
            f"(rule={decision.get('ruleId')})"
        )
        return emit_decision(decision)

    # Daemon unavailable or didn't settle. Under the fail-closed profile the
    # daemon is the law: no verdict → no tool (GPT review HST-004; governed /
    # unattended roles must not degrade to fail-open heuristics silently).
    if fail_closed():
        return deny_no_verdict(f"daemon path failed for {tool_name}")
    debug_log(f"daemon path failed; falling back to legacy for {tool_name}")
    return invoke_legacy_fallback(raw)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        if fail_closed():
            sys.exit(deny_no_verdict(f"hook crashed: {type(e).__name__}: {e}"))
        debug_log(f"top-level: {e}; allowing")
        sys.exit(0)
