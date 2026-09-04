#!/usr/bin/env python3
"""Claude Code -> Hestia common-gate shim.

CERTIFIED SHIM CONTRACT: this file contains only authority bootstrap, profile data,
harness syntax translation, and harness response rendering.  It contains no policy,
classification, scope logic, enforcement mode, escalation sequencing, or decision recorder.
"""
from __future__ import annotations

import importlib.util
import json
import os
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
    "member_id": "claude-code",
    "identity_path": os.path.expanduser("~/.claude/hestia-instance/identity.json"),
    "home_markers": ("~/.claude",),
    "host_agent": "claude-code",
    "client_name": "hestia-claude-code-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": "~/.claude/hestia-observe",
}


# 3. HARNESS SYNTAX ADAPTERS.
def to_event(gate, raw):
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "PreToolUse":
        raise ValueError("expected Claude Code PreToolUse event")
    tool = raw.get("tool_name")
    tool_input = raw.get("tool_input")
    if not isinstance(tool, str) or not tool:
        raise ValueError("PreToolUse event has no tool_name")
    if not isinstance(tool_input, dict):
        raise ValueError("PreToolUse event has non-object tool_input")
    return gate.GateEvent(
        tool=tool,
        tool_input=tool_input,
        cwd=raw.get("cwd") if isinstance(raw.get("cwd"), str) else None,
        session_id=raw.get("session_id") if isinstance(raw.get("session_id"), str) else None,
        tool_use_id=(raw.get("tool_use_id") if isinstance(raw.get("tool_use_id"), str) else None),
        raw=raw,
    )


def emit(decision) -> int:
    if decision.decision == "allow":
        return 0
    text = f"hestia: {decision.decision} [{decision.rule or 'gate'}]"
    if decision.reason:
        text += " - " + decision.reason
    if decision.remedy:
        text += ". " + decision.remedy
    sys.stderr.write(text + "\n")
    return 2 if decision.decision == "deny" else 0


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
