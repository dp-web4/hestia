#!/usr/bin/env python3
"""Hestia witness hook for Claude Code — self-contained, stdlib only.

Wired from .claude-plugin/plugin.json as the PostToolUse hook. Reads
the hook event JSON from stdin, fires a `hestia_begin_action` +
`hestia_record_outcome` pair against the local Hestia daemon's MCP
endpoint, and exits.

DESIGN
- Pure stdlib. No `httpx`, no `mcp`, no `hestia_plugin_sdk`. The plugin
  drops in as a single file and works wherever Python 3.10+ is present.
- Fail-open at every layer. Any error connecting to Hestia is logged
  (when `HESTIA_HOOK_DEBUG=1`) and swallowed. The hook MUST NOT block
  Claude Code's tool execution.
- First-run UX: if the daemon is missing, write a single one-time
  "daemon not detected" hint to ~/.hestia-claude/last-warning so a
  user who never ran `hestia init` knows what's happening.
- Stateless across invocations. Each hook process opens its own MCP
  session and disconnects. ~50-200 ms overhead amortized through the
  fire-and-forget wrapper; the actual round-trip happens off Claude
  Code's critical path.

DEBUG
  HESTIA_HOOK_DEBUG=1     log to ~/.hestia-claude/hook.log
  HESTIA_ENDPOINT=URL     override endpoint discovery
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
from typing import Any, Optional

# ---- Configuration --------------------------------------------------------

# One witness for every orchestrator: the hook event schema (hook_event_name /
# tool_name / tool_input) is shared across the Claude-Code lineage (Claude Code,
# Kimi Code, Codex), so the SAME script witnesses any of them — set
# HESTIA_PLUGIN_ID in the hook's environment to identify the member. All plugins
# are treated identically; each accrues to its own (instance, role) trust grain.
PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID", "claude-code")
HOST_AGENT = os.environ.get("HESTIA_HOST_AGENT", PLUGIN_ID)
PROTOCOL_VERSION = "2024-11-05"
TIMEOUT_S = 2.0
HOOK_VERSION = "0.0.2"

STATE_DIR = Path(
    os.environ.get("HESTIA_STATE_DIR")
    or str(Path.home() / (".hestia-claude" if PLUGIN_ID == "claude-code" else f".hestia-{PLUGIN_ID}"))
)
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"
DEFAULT_ENDPOINT = "http://127.0.0.1:7711/mcp"


def debug_log(msg: str) -> None:
    if os.environ.get("HESTIA_HOOK_DEBUG") != "1":
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "hook.log").open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def discover_endpoint() -> Optional[str]:
    """Mirror the SDK's discovery order: env → file → default."""
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    endpoint_file = home / "endpoint"
    try:
        return endpoint_file.read_text().strip() or None
    except OSError:
        return None  # daemon hasn't run; let warn_once handle the UX


def warn_once_daemon_missing() -> None:
    """Surface a single one-time hint if the daemon was never set up."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        marker = STATE_DIR / "daemon-warned"
        if marker.exists():
            return
        marker.touch()
        sys.stderr.write(
            "hestia: daemon not detected — install at https://hestia.tools "
            "to start recording tool calls. (This message shown once.)\n"
        )
    except OSError:
        pass


# ---- Magnitude / target heuristics ---------------------------------------

def magnitude_for(tool_name: str) -> float:
    """R6 magnitude in [0..1] by tool class."""
    if tool_name in {"Bash", "Shell"}:
        return 0.8
    if tool_name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return 0.6
    if tool_name in {"WebFetch", "WebSearch"}:
        return 0.4
    if tool_name in {"Read", "Glob", "Grep", "TodoWrite"}:
        return 0.2
    return 0.4


def extract_target(tool_input: Any) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    cmd = tool_input.get("command")
    if isinstance(cmd, str) and cmd.strip():
        # Send the full command (truncated for chain-entry hygiene).
        # The policy gate already sees the untruncated command via the
        # PreToolUse hook's `parameters.command`; this `target` is for
        # forensic readability in the chain feed.
        s = cmd.strip()
        return s if len(s) <= 240 else s[:237] + "..."
    return None


def derive_success(tool_response: Any) -> tuple[bool, Optional[str]]:
    """Best-effort success flag from Claude Code's tool_response shape."""
    if not isinstance(tool_response, dict):
        return True, None
    if tool_response.get("is_error") or tool_response.get("isError"):
        err = tool_response.get("error") or tool_response.get("message") or "tool error"
        return False, str(err)[:500]
    return True, None


# ---- Minimal MCP-over-HTTP client ----------------------------------------

class McpHttp:
    """Tiny synchronous MCP client. Just enough to fire init + 2 tool calls."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _request(
        self, body: dict[str, Any], *, is_notification: bool = False
    ) -> Optional[dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            # Capture session id on first call.
            if not self.session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            if is_notification:
                return None
            payload = resp.read().decode("utf-8", errors="replace")
        return parse_json_or_sse(payload)

    # --- public ops ---

    def initialize(self) -> dict[str, Any]:
        result = self._request({
            "jsonrpc": "2.0",
            "id": self._id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": PLUGIN_ID, "version": HOOK_VERSION},
            },
        })
        return result or {}

    def initialized(self) -> None:
        self._request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            is_notification=True,
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request({
            "jsonrpc": "2.0",
            "id": self._id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        return result or {}


def parse_json_or_sse(text: str) -> dict[str, Any]:
    """Hestia returns either a plain JSON-RPC body or an SSE stream
    containing the body. Handle both."""
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    # SSE: pick the last `data:` line that parses as JSON.
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
    """Extract the structured payload from an MCP tools/call response."""
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    # Fallback to first text content.
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    return {}


# ---- Main flow -----------------------------------------------------------

def run() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        debug_log(f"bad json: {e}")
        return 0

    if event.get("hook_event_name") != "PostToolUse":
        return 0

    tool_name = event.get("tool_name") or "?"
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response")
    # Claude Code's own stable session id — the real per-session audit grain.
    host_session_id = event.get("session_id")

    endpoint = discover_endpoint()
    if endpoint is None:
        warn_once_daemon_missing()
        debug_log("no endpoint discovered; skipping")
        return 0

    target = extract_target(tool_input)
    magnitude = magnitude_for(tool_name)
    success, error = derive_success(tool_response)

    client = McpHttp(endpoint)
    try:
        init_resp = client.initialize()
        if "result" not in init_resp:
            debug_log(f"initialize failed: {init_resp}")
            return 0
        client.initialized()

        connect_args: dict[str, Any] = {
            "plugin_id": PLUGIN_ID,
            "plugin_version": HOOK_VERSION,
            "host_agent": HOST_AGENT,
            "host_agent_version": "claude-code",
            "requested_role": "citizen",
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
            return 0
        session_id = connect.get("sessionId")

        begin_resp = client.call_tool(
            "hestia_begin_action",
            {
                "tool_name": tool_name,
                "target": target,
                **({"session_id": session_id} if session_id else {}),
                **({"host_session_id": host_session_id} if host_session_id else {}),
            },
        )
        begin = unwrap_tool_result(begin_resp)
        if "_hestia_error" in begin:
            debug_log(f"begin_action rejected: {begin['_hestia_error']}")
            return 0
        action_id = begin.get("actionId")
        if not action_id:
            debug_log(f"begin_action missing actionId: {begin}")
            return 0

        outcome_resp = client.call_tool(
            "hestia_record_outcome",
            {
                "action_id": action_id,
                "success": success,
                "magnitude": magnitude,
                "error": error,
                **({"session_id": session_id} if session_id else {}),
            },
        )
        outcome = unwrap_tool_result(outcome_resp)
        if "_hestia_error" in outcome:
            debug_log(f"record_outcome rejected: {outcome['_hestia_error']}")
            return 0

        debug_log(
            f"post {tool_name} action={action_id[:8]} "
            f"success={success} magnitude={magnitude}"
        )
    except urllib.error.URLError as e:
        debug_log(f"network: {e}")
        warn_once_daemon_missing()
    except Exception as e:  # noqa: BLE001 — fail-open at top level
        debug_log(f"unexpected: {type(e).__name__}: {e}")
    return 0


BACKGROUND_MARKER = "--hestia-bg"


def fire_and_forget() -> None:
    """Relaunch self detached so the parent (Claude Code) doesn't block.

    Reads stdin in the foreground, hands it to the background process,
    exits immediately. The background process does the actual MCP work.

    Cross-platform: `start_new_session=True` on POSIX, `DETACHED_PROCESS`
    + `CREATE_NEW_PROCESS_GROUP` on Windows.
    """
    raw = sys.stdin.buffer.read()
    kwargs: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), BACKGROUND_MARKER],
            **kwargs,
        )
        if proc.stdin is not None:
            proc.stdin.write(raw)
            proc.stdin.close()
    except OSError as e:
        debug_log(f"could not background: {e}")


if __name__ == "__main__":
    try:
        if BACKGROUND_MARKER in sys.argv:
            sys.exit(run())
        fire_and_forget()
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        debug_log(f"top-level: {e}")
        sys.exit(0)
