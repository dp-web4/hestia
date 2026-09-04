"""Certified Hestia harness shim template.

A shim translates an event. It never decides how that event is governed.

The tuples below are the machine-readable structural contract consumed by
`plugins/_shared/shim_certification_test.py`; prose and checker do not carry separate
allow-lists that can drift.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

SHIM_CERTIFICATION_SCHEMA = "hestia-shim-cert/v1"
CERTIFICATION_CRITERIA = "PRD_SHIM_CERTIFICATION.md@2026-09-04"
REQUIRED_GATE_API = "decide/1"

PERMITTED_FUNCTIONS = (
    "_authority_dir",
    "_load_gate",
    "_emergency_block",
    "to_event",
    "emit",
    "read_harness_event",
    "main",
)
BYTE_IDENTICAL_FUNCTIONS = (
    "_authority_dir",
    "_load_gate",
    "_emergency_block",
    "main",
)
ADAPTER_FUNCTIONS = ("to_event", "emit", "read_harness_event")
PERMITTED_PROFILE_KEYS = {
    "member_id", "identity_path", "home_markers", "host_agent",
    "client_name", "gate_path", "observe_dir",
}


# 1. AUTHORITY BOOTSTRAP. Copy byte-for-byte.
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


# 2. PROFILE DATA. Replace values, never add policy.
PROFILE = {
    "member_id": "<seat>",
    "identity_path": "<absolute-or-expanded identity path>",
    "home_markers": ("<harness-home>",),
    "host_agent": "<seat>",
    "client_name": "hestia-<seat>-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": "<observe-dir>",
}


# 3. HARNESS SYNTAX ADAPTERS. Pure translation/rendering only.
def to_event(gate, raw):
    raise NotImplementedError("translate harness event to gate.GateEvent")


def emit(decision) -> int:
    raise NotImplementedError("render GateDecision using the harness blocking protocol")


def read_harness_event():
    raise NotImplementedError("read one harness-native event")


# 4. MAIN. Copy byte-for-byte.
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
