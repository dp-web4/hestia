#!/usr/bin/env python3
"""Hestia witness — record Claude Code tool calls to the local Hestia daemon.

Wired from ~/.claude/settings.json as the PreToolUse / PostToolUse hooks.
Reads the hook event JSON from stdin, fires a begin_action (Pre) or
record_outcome (Post) against http://127.0.0.1:7711/mcp, and exits.

DESIGN POINTS
- Fail-open. Any error connecting to Hestia is logged and swallowed.
  This script MUST NOT block Claude Code's tool execution.
- Stateless across invocations. Each hook process opens its own MCP
  session and disconnects. This is N×100ms overhead per tool call but
  trades simplicity for performance during the initial witness-data
  collection phase. Performance work happens after we see what breaks.
- Action correlation: Pre stores an action_id keyed by tool_use_id
  under /tmp/hestia-actions/, Post reads it back. If the file is
  missing (Pre never fired, Hestia was down then), Post still records
  a standalone outcome with action_id=null.

DEBUG
  HESTIA_HOOK_DEBUG=1  log to /tmp/hestia-hook.log
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# ---- Path so we can import the SDK without pip-installing -----------------
SDK_PATH = "/mnt/c/exe/projects/ai-agents/hestia/plugin-sdk/python"
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

from hestia_plugin_sdk import (  # type: ignore
    HestiaClientConfig,
    Outcome,
    ToolCallSpec,
    create_hestia_client,
)

DEBUG = os.environ.get("HESTIA_HOOK_DEBUG") == "1"
DEBUG_LOG = Path("/tmp/hestia-hook.log")
ACTIONS_DIR = Path("/tmp/hestia-actions")
ACTIONS_DIR.mkdir(exist_ok=True, parents=True)
ENDPOINT = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN_ID = "claude-code"
HOST_AGENT = "claude-code"
# Optional constellation role for this session. Absent → omit → daemon
# defaults to role:constellation:member. The daemon normalizes any string.
HESTIA_ROLE = os.environ.get("HESTIA_ROLE")


def log(msg: str) -> None:
    if not DEBUG:
        return
    try:
        with DEBUG_LOG.open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def magnitude_for(tool_name: str) -> float:
    """R6 magnitude in [0..1] based on tool class. Higher = more consequential."""
    high = {"Bash", "Shell"}
    mid_write = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    mid_net = {"WebFetch", "WebSearch"}
    low_read = {"Read", "Glob", "Grep", "TodoWrite"}
    if tool_name in high:
        return 0.8
    if tool_name in mid_write:
        return 0.6
    if tool_name in mid_net:
        return 0.4
    if tool_name in low_read:
        return 0.2
    return 0.4


def extract_target(tool_name: str, tool_input: dict) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    cmd = tool_input.get("command")
    if isinstance(cmd, str):
        return cmd.split()[0] if cmd.split() else cmd
    return None


async def run() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"bad json: {e}")
        return 0

    event_name = event.get("hook_event_name")
    tool_name = event.get("tool_name") or "?"
    # Claude Code's own stable session id — the real per-session audit grain.
    host_session_id = event.get("session_id")
    tool_use_id = event.get("tool_use_id") or event.get("session_id", "no-id")
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response")

    config = HestiaClientConfig(
        plugin_id=PLUGIN_ID,
        plugin_version="hook-0.0.1",
        host_agent=HOST_AGENT,
        host_agent_version="claude-code",
        hestia_endpoint=ENDPOINT,
    )
    client = create_hestia_client(config)

    try:
        await client.connect(role=HESTIA_ROLE)
    except Exception as e:  # noqa: BLE001 — fail-open
        log(f"connect failed: {e}")
        return 0

    try:
        if event_name == "PreToolUse":
            target = extract_target(tool_name, tool_input)
            try:
                action = await client.begin_action(
                    ToolCallSpec(tool_name=tool_name, target=target),
                    host_session_id=host_session_id,
                )
                ACTIONS_DIR.joinpath(f"{tool_use_id}.json").write_text(
                    json.dumps(
                        {
                            "action_id": action.action_id,
                            "started_at": action.started_at.isoformat(),
                            "chain_position": action.chain_position,
                            "tool_name": tool_name,
                        }
                    )
                )
                log(f"pre  {tool_name} action_id={action.action_id[:8]}")
            except Exception as e:  # noqa: BLE001
                log(f"begin_action failed: {e}")

        elif event_name == "PostToolUse":
            action_id = None
            tool_name_from_pre = tool_name
            cached = ACTIONS_DIR / f"{tool_use_id}.json"
            if cached.exists():
                try:
                    data = json.loads(cached.read_text())
                    action_id = data.get("action_id")
                    tool_name_from_pre = data.get("tool_name", tool_name)
                except (OSError, json.JSONDecodeError):
                    pass
                cached.unlink(missing_ok=True)

            success = True
            error = None
            if isinstance(tool_response, dict):
                # Claude Code's tool_response shape varies; treat any
                # error-shaped key as failure.
                if tool_response.get("is_error") or tool_response.get("isError"):
                    success = False
                    error = str(tool_response.get("error") or tool_response.get("message") or "tool error")[:500]
            magnitude = magnitude_for(tool_name_from_pre)

            try:
                if action_id is None:
                    # Cold-record an outcome: begin and finish in one breath.
                    action = await client.begin_action(
                        ToolCallSpec(
                            tool_name=tool_name_from_pre,
                            target=extract_target(tool_name_from_pre, tool_input),
                        ),
                        host_session_id=host_session_id,
                    )
                    action_id = action.action_id
                    # Synthesize an R6Action for record_outcome.
                    from hestia_plugin_sdk import R6Action  # type: ignore
                    from datetime import datetime, timezone

                    action_obj = R6Action(
                        action_id=action.action_id,
                        tool_name=tool_name_from_pre,
                        started_at=action.started_at,
                        chain_position=action.chain_position,
                    )
                else:
                    from hestia_plugin_sdk import R6Action  # type: ignore
                    from datetime import datetime, timezone

                    action_obj = R6Action(
                        action_id=action_id,
                        tool_name=tool_name_from_pre,
                        started_at=datetime.now(timezone.utc),
                        chain_position=0,
                    )

                await client.record_outcome(
                    action_obj,
                    Outcome(success=success, magnitude=magnitude, error=error),
                )
                log(f"post {tool_name_from_pre} action_id={action_id[:8]} success={success}")
            except Exception as e:  # noqa: BLE001
                log(f"record_outcome failed: {e}")
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as e:  # noqa: BLE001 — fail-open at top level
        log(f"top-level: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
