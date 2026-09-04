#!/usr/bin/env python3
"""Kimi Code -> Hestia common-gate shim.

HARNESS-DIFFERENCE: Kimi supplies a PreToolUse JSON event on stdin and treats exit 2 as a
blocking hook result. No governance semantics differ from any other seat.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

SHIM_CERTIFICATION_SCHEMA = "hestia-shim-cert/v1"
CERTIFICATION_CRITERIA = "PRD_SHIM_CERTIFICATION.md@2026-09-04"
REQUIRED_GATE_API = "decide/1"


def _authority_dir() -> str:
    # HESTIA_HOME is the launcher's home selector (hestia.service, hestia-deploy.service, the
    # daemon's --home), not a member input; unset -> ~/.hestia, the same value as before.
    home = os.path.expanduser(os.getenv("HESTIA_HOME", "~/.hestia"))
    return os.path.realpath(os.path.join(home, "shared"))


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
    "member_id": "kimi-code",
    "identity_path": os.path.expanduser("~/.kimi-code/hestia-instance/identity.json"),
    "home_markers": ("~/.kimi-code",),
    "host_agent": "kimi-code",
    "client_name": "hestia-kimi-code-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": "~/.kimi-code/hestia-observe",
}


def to_event(gate, raw):
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "PreToolUse":
        raise ValueError("expected PreToolUse event")
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
        tool_use_id=raw.get("tool_use_id") if isinstance(raw.get("tool_use_id"), str) else None,
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
