#!/usr/bin/env python3
"""Gemini CLI -> Hestia common-gate shim.

HARNESS-DIFFERENCE: Gemini names the event BeforeTool, uses different tool/argument names,
and exposes nested MCP transport metadata that must be translated without judging it.
HARNESS-DIFFERENCE: Gemini's runner uses exit-0 JSON for a decided policy deny and exit 2
for a hook/infrastructure anomaly; both block the tool.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

SHIM_CERTIFICATION_SCHEMA = "hestia-shim-cert/v1"
CERTIFICATION_CRITERIA = "PRD_SHIM_CERTIFICATION.md@2026-09-04"
REQUIRED_GATE_API = "decide/1"


def _authority_dir() -> str:
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
    if getattr(module, "GATE_API_VERSION", None) != REQUIRED_GATE_API:
        sys.modules.pop(name, None)
        raise ImportError(
            f"common gate API mismatch: got {getattr(module, 'GATE_API_VERSION', None)!r}, "
            f"expected {REQUIRED_GATE_API!r}")
    return module


def _emergency_block(reason: str) -> int:
    try:
        import time
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seat": PROFILE.get("member_id", "unknown"),
            "decision": "deny",
            "rule": "gate.bootstrap_unavailable",
            "verdict_available": False,
            "detail": str(reason)[:400],
        }
        home = os.path.expanduser("~/.hestia")
        path = os.path.join(home, "telemetry", "gate-unavailable.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except BaseException:
        pass
    sys.stderr.write("hestia: deny [gate.bootstrap_unavailable] - " + reason + "\n")
    return 2


PROFILE = {
    "member_id": "gemini",
    "identity_path": os.path.expanduser("~/.gemini/hestia-instance/identity.json"),
    "home_markers": ("~/.gemini",),
    "host_agent": "gemini",
    "client_name": "hestia-gemini-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": "~/.gemini/hestia-observe",
}


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
        mcp_tool = mcp.get("tool_name")
        canonical_tool = (
            f"mcp__{server}__{mcp_tool or '?'}" if isinstance(server, str) and server
            else _TOOL.get(native_tool.lower(), native_tool)
        )
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
        tool_use_id=raw.get("tool_use_id") if isinstance(raw.get("tool_use_id"), str) else None,
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
            sys.stderr.write(text + "\n")
            return 2
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


def main() -> int:
    try:
        gate = _load_gate()
    except BaseException as exc:
        return _emergency_block(
            f"common gate could not be loaded ({type(exc).__name__}: {exc})")
    try:
        raw = read_harness_event()
        event = to_event(gate, raw)
        decision = gate.decide(event, gate.GateProfile(**PROFILE))
        return emit(decision)
    except BaseException as exc:
        return _emergency_block(
            f"shim could not translate/emit the event ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
