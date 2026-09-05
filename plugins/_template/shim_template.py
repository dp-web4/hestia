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
    "_load_projection",
    "_authority_dir",
    "_load_gate",
    "_emergency_block",
    "to_event",
    "emit",
    "read_harness_event",
    "main",
)
BYTE_IDENTICAL_FUNCTIONS = (
    "_load_projection",
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


# 0. CONFIGURATION BOOTSTRAP. Copy byte-for-byte.
# The projection `$HESTIA_HOME/seats/<member>` is this seat's ONLY configuration source
# (PRD_CONFIG_FROM_VAULT; #944). HESTIA_HOME is the one launcher-supplied locator and has no
# default anywhere. Every projected key is exported over the launcher's environment except
# HESTIA_ROLE, which is launch context and never config. Import never fails; `main` refuses
# on the recorded outcome before it reads the harness event.
def _load_projection(member: str):
    home = os.environ.get("HESTIA_HOME")
    if not home:
        return ("config.unbacked", "HESTIA_HOME is not set; the launcher must supply the "
                "bootstrap locator (there is no default, by design)")
    path = os.path.join(home, "seats", member + ".env")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return ("config.unbacked", f"no rendered projection for {member} at {path} ({exc}); "
                "populate this seat's config in the vault (Govern -> Runtime config)")
    import hashlib
    import re as _re
    pairs = []
    for line in raw.decode("utf-8", "replace").split("\n"):
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            return ("config.unbacked", f"projection {path} carries an unusable key {key!r}")
        pairs.append((key, value))
    projected = dict(pairs)
    if "HESTIA_HOME" in projected and os.path.realpath(projected["HESTIA_HOME"]) != os.path.realpath(home):
        return ("config.miswired", f"the launcher supplied HESTIA_HOME={home!r} but the vault "
                f"projection says {projected['HESTIA_HOME']!r}; this seat is running against a "
                "home the authority does not name")
    for key, value in pairs:
        if key == "HESTIA_ROLE":
            continue
        os.environ[key] = value
    os.environ["HESTIA_PROJECTION_SHA256"] = hashlib.sha256(raw).hexdigest()
    os.environ["HESTIA_PROJECTION_PATH"] = path
    return None


MEMBER_ID = "<seat>"
_PROJECTION_ERROR = _load_projection(MEMBER_ID)


# 1. AUTHORITY BOOTSTRAP. Copy byte-for-byte.
def _authority_dir() -> str:
    home = os.environ.get("HESTIA_HOME")
    if not home:
        raise ImportError("HESTIA_HOME is not set; no shared authority can be located")
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


def _emergency_block(reason: str, rule: str = "gate.bootstrap_unavailable") -> int:
    home = os.environ.get("HESTIA_HOME")
    if home:
        try:
            import time
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "seat": PROFILE.get("member_id", "unknown"),
                "decision": "deny",
                "rule": rule,
                "verdict_available": False,
                "detail": str(reason)[:400],
            }
            path = os.path.join(home, "telemetry", "gate-unavailable.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        except BaseException:
            pass
    sys.stderr.write("hestia: deny [" + rule + "] - " + reason + "\n")
    return 2


# 2. PROFILE DATA. Replace values, never add policy. Every path is READ from the projected
# environment (`os.environ.get("<KEY>")`, no default): the vault authored it, the launcher
# supplied only the locator, and a default here would be the #943 class.
PROFILE = {
    "member_id": "<seat>",
    "identity_path": os.environ.get("HESTIA_<SEAT>_IDENTITY"),
    "home_markers": (os.environ.get("HESTIA_HARNESS_HOME"),),
    "host_agent": "<seat>",
    "client_name": "hestia-<seat>-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": os.environ.get("HESTIA_OBSERVE_DIR"),
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
    if _PROJECTION_ERROR is not None:
        return _emergency_block(_PROJECTION_ERROR[1], rule=_PROJECTION_ERROR[0])
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
