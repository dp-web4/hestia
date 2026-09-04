#!/usr/bin/env python3
"""Gemini CLI -> Hestia common-gate shim.

CERTIFIED SHIM CONTRACT: this file contains only authority bootstrap, profile data,
harness syntax translation, and Gemini's documented response rendering.  It contains no
policy, classification, scope logic, enforcement mode, escalation sequencing, or recorder.

JUSTIFIED DIFFERENCES from the Claude-lineage shim:
  * Gemini calls the event `BeforeTool` and uses different tool/argument names.
  * Gemini exposes MCP transport metadata in `mcp_context`; this adapter preserves it and
    translates command/argument spellings without judging them.
  * Gemini's runner treats exit-0 JSON {decision:"deny"} as a clean policy block, while
    exit 2 denotes a hook anomaly.  `emit` therefore uses JSON for decided policy denies and
    stderr+2 for infrastructure/anomaly denies.  Both block the tool.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys


# 1. AUTHORITY BOOTSTRAP -- byte-identical across certified shims.
def _authority_dir() -> str:
    if os.environ.get("HESTIA_GATE_TEST_MODE") == "1":
        test_dir = os.environ.get("HESTIA_SHARED_DIR")
        if test_dir:
            return os.path.realpath(os.path.expanduser(test_dir))
    return os.path.realpath(os.path.expanduser("~/.hestia/shared"))


def _load_gate():
    name = "hestia_single_gate"
    shared = _authority_dir()
    required = os.path.realpath(os.path.join(shared, name + ".py"))
    if not os.path.isfile(required):
        raise ImportError(f"installed common gate unavailable at {required!r}")
    selected_key = os.path.normcase(shared)
    retained = []
    for entry in sys.path:
        try:
            key = os.path.normcase(os.path.realpath(os.fspath(entry) or os.getcwd()))
        except (TypeError, ValueError, OSError):
            retained.append(entry)
            continue
        if key != selected_key:
            retained.append(entry)
    sys.path[:] = [shared, *retained]
    cached = sys.modules.get(name)
    if cached is not None:
        loaded = getattr(cached, "__file__", None)
        if loaded and os.path.realpath(loaded) == required:
            return cached
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, required)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot construct loader for {required!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:
        sys.modules.pop(name, None)
        raise ImportError("installed common gate failed to initialize") from exc
    loaded = getattr(module, "__file__", None)
    if not loaded or os.path.realpath(loaded) != required:
        sys.modules.pop(name, None)
        raise ImportError(
            f"common gate authority miswire: loaded {loaded!r}, expected {required!r}")
    return module


def _emergency_block(reason: str) -> int:
    sys.stderr.write("hestia: deny [gate.unavailable] - " + reason + "\n")
    return 2


# 2. PROFILE DATA -- context, never law.
PROFILE = {
    "member_id": "gemini",
    "identity_path": os.path.expanduser("~/.gemini/hestia-instance/identity.json"),
    "home_markers": ("~/.gemini",),
    "host_agent": "gemini",
    "client_name": "hestia-gemini-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": "~/.gemini/hestia-observe",
}


# 3. HARNESS SYNTAX ADAPTERS.
_TOOL = {
    "run_shell_command": "Shell",
    "write_file": "Write",
    "replace": "Edit",
    "read_file": "Read",
    "read_many_files": "Read",
    "glob": "Glob",
    "search_file_content": "Grep",
    "list_directory": "Read",
    "web_fetch": "WebFetch",
    "google_web_search": "WebSearch",
}
_ARG = {"absolute_path": "file_path", "dir_path": "path"}


def _string_leaves(value, depth=0):
    if isinstance(value, str):
        return [value]
    if depth > 4:
        return []
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _string_leaves(item, depth + 1)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _string_leaves(item, depth + 1)]
    return []


def to_event(gate, raw):
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "BeforeTool":
        raise ValueError("expected Gemini BeforeTool event")
    native_tool = raw.get("tool_name")
    native_input = raw.get("tool_input")
    if not isinstance(native_tool, str) or not native_tool:
        raise ValueError("BeforeTool event has no tool_name")
    if not isinstance(native_input, dict):
        raise ValueError("BeforeTool event has non-object tool_input")

    ti = {_ARG.get(k, k): v for k, v in native_input.items()}
    if "file_path" not in ti and "path" not in ti:
        include = native_input.get("include")
        if isinstance(include, list) and include and isinstance(include[0], str):
            ti["path"] = include[0]

    mcp = raw.get("mcp_context")
    if isinstance(mcp, dict):
        ti["_hestia_mcp_context"] = mcp
        server = mcp.get("server_name")
        tool = mcp.get("tool_name")
        canonical_tool = (
            f"mcp__{server}__{tool or '?'}" if isinstance(server, str) and server
            else _TOOL.get(native_tool.lower(), native_tool)
        )
        # MCP command/args/cwd are local execution/reach syntax.  Preserve all of them in the
        # canonical command field so the common command-scope rule, not this adapter, judges it.
        parts = []
        existing = ti.get("command")
        if isinstance(existing, str):
            parts.append(existing)
        elif isinstance(existing, list):
            parts.extend(str(x) for x in existing)
        parts.extend(_string_leaves(mcp.get("command")))
        parts.extend(_string_leaves(mcp.get("args")))
        parts.extend(_string_leaves(mcp.get("cwd")))
        if parts:
            ti["command"] = " ".join(parts)
        if "url" not in ti and isinstance(mcp.get("url"), str) and mcp.get("url"):
            ti["url"] = mcp["url"]
    else:
        canonical_tool = _TOOL.get(native_tool.lower(), native_tool)

    # Gemini web_fetch may encode the target URL only inside its prompt.  Lift the spelling;
    # whether the target is allowed remains entirely the common gate's decision.
    if canonical_tool == "WebFetch" and "url" not in ti:
        match = re.search(r"https?://[^\s\"'<>)]+", str(native_input.get("prompt") or ""))
        if match:
            ti["url"] = match.group(0)

    canonical_raw = dict(raw)
    canonical_raw["source_event"] = {
        "lineage": "gemini",
        "tool_name": native_tool,
        "tool_input": native_input,
        "mcp_context": mcp,
    }
    return gate.GateEvent(
        tool=canonical_tool,
        tool_input=ti,
        cwd=raw.get("cwd") if isinstance(raw.get("cwd"), str) else None,
        session_id=raw.get("session_id") if isinstance(raw.get("session_id"), str) else None,
        tool_use_id=(raw.get("tool_use_id") if isinstance(raw.get("tool_use_id"), str) else None),
        raw=canonical_raw,
    )


def emit(decision) -> int:
    text = f"hestia: {decision.decision} [{decision.rule or 'gate'}]"
    if decision.reason:
        text += " - " + decision.reason
    if decision.remedy:
        text += ". " + decision.remedy
    if decision.decision == "deny":
        if decision.anomaly:
            # Gemini runner: nonzero+text is the corruption-resistant anomaly deny channel.
            sys.stderr.write(text + "\n")
            return 2
        # Gemini runner: a decided policy deny is a clean exit-0 JSON block.
        sys.stdout.write(json.dumps({"decision": "deny", "reason": text}, ensure_ascii=True))
        return 0
    if decision.decision == "warn":
        sys.stderr.write(text + "\n")
    return 0


def read_harness_event():
    raw = sys.stdin.read()
    if not raw:
        raise ValueError("empty hook event")
    return json.loads(raw)


# 4. MAIN -- same decision call for every harness.
def main() -> int:
    try:
        gate = _load_gate()
    except BaseException as exc:
        return _emergency_block(
            f"common gate could not be loaded ({type(exc).__name__}: {exc})")
    try:
        raw = read_harness_event()
        ev = to_event(gate, raw)
        decision = gate.decide(ev, gate.GateProfile(**PROFILE))
        return emit(decision)
    except BaseException as exc:
        return _emergency_block(
            f"shim could not translate/emit the event ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
