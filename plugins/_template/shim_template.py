"""Certified Hestia harness shim template.

A shim translates an event. It never decides how that event is governed.

One-gate stage C (docs/one-gate-convergence-plan.md §4): every seat's gate IS this template.
A seat copies sections 0, 1 and 4 byte-for-byte, replaces the DATA in section 2 (PROFILE,
HARNESS) and writes the three adapters in section 3. The tuples below are the machine-readable
structural contract consumed by `tools/shim_certification.py` and its test; prose and checker do
not carry separate allow-lists that can drift.

THE HARNESS IS DATA, AND ITS TIMEOUT IS READ, NEVER ASSUMED. `HARNESS` declares where this
harness records its hook registrations, the hook event, the timeout's unit, the harness's own
default for an entry that omits it, what the harness does when the timeout expires, and the
margin this process needs around the decision (interpreter start before `_START`, rendering and
exit after). `main` asks the common gate's `harness_bound()` for the deadline the REAL
registration allows (`_START + registered timeout - margin`) and passes it to `decide()`, so the
gate always fails closed before the harness can kill it and fail open (dp 2026-10-02, the safety
invariant). A registration that cannot be read is a refusal, not a guess.
"""
from __future__ import annotations

import time

_START = time.monotonic()   # the harness's clock started when it spawned this process

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

SHIM_CERTIFICATION_SCHEMA = "hestia-shim-cert/v1"
CERTIFICATION_CRITERIA = "PRD_SHIM_CERTIFICATION.md@2026-10-04"
REQUIRED_GATE_API = "decide/2"

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
    "client_name", "gate_path", "observe_dir", "launch_cwd_env", "declares_review_door",
}
PERMITTED_HARNESS_KEYS = {
    "name", "event", "registrations", "timeout_unit_seconds", "default_timeout_seconds",
    "on_timeout", "margin_seconds",
}


# 0. CONFIGURATION BOOTSTRAP. Copy byte-for-byte.
# The projection `$HESTIA_HOME/seats/<member>.env` is this seat's ONLY configuration source
# (PRD_CONFIG_FROM_VAULT; #944). HESTIA_HOME is the one launcher-supplied locator and has no
# default anywhere. Every projected key is exported over the launcher's environment except
# HESTIA_ROLE (launch context, never config) and HESTIA_ROLE_PERMITTED (its bound, kept aside
# unjudged for the common gate, which owns the verdict: #1084). Import never fails; `main`
# refuses on the recorded outcome before it reads the harness event.
def _load_projection(member: str):
    global _ROLE_PERMITTED
    # THE ROLLOUT IS THE VAULT'S (C5: no enforcement posture selectable by the environment a seat
    # runs in). A launcher-supplied HESTIA_GATE_MODE is dropped; only this seat's projection
    # (`<SEAT_TOKEN>__HESTIA_GATE_MODE`) may set it, and with none the gate enforces.
    os.environ.pop("HESTIA_GATE_MODE", None)
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
    # OWNERSHIP RIDES ON EVERY LINE (design A). A per-seat line is `TOKEN__KEY`; shared lines
    # are plain. This seat strips ITS token and exports the bare key; a line carrying any other
    # seat's token is a miswire, not a value -- it cannot be consumed here, whatever it says.
    token = "".join(ch.upper() if ch.isalnum() else "_" for ch in member)
    projected = {}
    for key, value in pairs:
        if "__" in key:
            prefix, bare = key.split("__", 1)
            if prefix != token:
                return ("config.miswired", f"projection {path} carries a line for seat token "
                        f"{prefix!r}, but this seat is {token!r} ({member}); a line cannot be "
                        "consumed by a seat it was not rendered for")
            key = bare
        projected[key] = value
    if "HESTIA_HOME" in projected and os.path.realpath(projected["HESTIA_HOME"]) != os.path.realpath(home):
        return ("config.miswired", f"the launcher supplied HESTIA_HOME={home!r} but the vault "
                f"projection says {projected['HESTIA_HOME']!r}; this seat is running against a "
                "home the authority does not name")
    if projected.get("HESTIA_PLUGIN_ID", member) != member:
        return ("config.miswired", f"projection {path} says HESTIA_PLUGIN_ID="
                f"{projected['HESTIA_PLUGIN_ID']!r} but this seat is {member!r}")
    _ROLE_PERMITTED = projected.get("HESTIA_ROLE_PERMITTED", "")
    for key, value in projected.items():
        if key in ("HESTIA_ROLE", "HESTIA_ROLE_PERMITTED"):
            continue
        os.environ[key] = value
    os.environ["HESTIA_PROJECTION_SHA256"] = hashlib.sha256(raw).hexdigest()
    os.environ["HESTIA_PROJECTION_PATH"] = path
    return None


MEMBER_ID = "<seat>"
_ROLE_PERMITTED = ""
_PROJECTION_ERROR = _load_projection(MEMBER_ID)


# 1. AUTHORITY BOOTSTRAP. Copy byte-for-byte.
# The installed engine only: an explicit HESTIA_SHARED_DIR (the projection renders it; tests and
# the deploy preflight name the tree under test), else $HESTIA_HOME/shared. Never a checkout.
def _authority_dir() -> str:
    explicit = os.environ.get("HESTIA_SHARED_DIR")
    if explicit:
        return os.path.realpath(explicit)
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
    # A same-named module an earlier import left in sys.modules beats sys.path, so the gate's
    # bare sibling imports would bind it (#747). Evict every hestia_* module not loaded from
    # the selected authority.
    prefix = selected_key + os.sep
    for cached_name in [n for n in list(sys.modules) if n.startswith("hestia_")]:
        origin = getattr(sys.modules.get(cached_name), "__file__", None)
        try:
            inside = bool(origin) and os.path.normcase(os.path.realpath(origin)).startswith(prefix)
        except (TypeError, ValueError, OSError):
            inside = False
        if not inside:
            sys.modules.pop(cached_name, None)
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


# Exit 2 with text on stderr blocks on every supported harness (Claude Code, Codex and Kimi
# block on exit 2; Gemini denies any exit-2 output). This path runs only when the common gate
# itself is unavailable, so it leaves a local artifact instead of a witnessed record (C7b).
def _emergency_block(reason: str, rule: str = "gate.bootstrap_unavailable") -> int:
    home = os.environ.get("HESTIA_HOME")
    if home:
        try:
            row = {
                "ts": int(time.time()),
                "member": PROFILE.get("member_id", "unknown"),
                "tool": "unknown",
                "cause": "unknown",
                "decision": "deny",
                "rule": rule,
                "verdict_available": False,
                "detail": str(reason)[:200],
                "kind": "gate_unavailable",
            }
            path = os.path.join(home, "telemetry", "gate-unavailable.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        except BaseException:
            pass
    sys.stderr.write("hestia: deny [" + rule + "] - " + reason + "\n")
    return 2


# 2. PROFILE AND HARNESS DATA. Replace values, never add policy. Every path is READ from the
# projected environment (`os.environ.get("<KEY>")`, no default): the vault authored it, the
# launcher supplied only the locator, and a default here would be the #943 class.
PROFILE = {
    "member_id": "<seat>",
    "identity_path": os.environ.get("HESTIA_<SEAT>_IDENTITY"),
    "home_markers": (os.environ.get("HESTIA_HARNESS_HOME"),),
    "host_agent": "<seat>",
    "client_name": "hestia-<seat>-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": os.environ.get("HESTIA_OBSERVE_DIR"),
    "launch_cwd_env": "",
    "declares_review_door": False,
}
# Where this harness records the hook and what its timeout means. `registrations[].path` may use
# `~`, `${VAR:-default}` and `{cwd}` (the event's cwd); a source that does not exist is skipped.
HARNESS = {
    "name": "<harness>",
    "event": "PreToolUse",
    "registrations": (
        {"reader": "json-hook-commands", "layout": "nested", "path": "~/.<harness>/settings.json"},
    ),
    "timeout_unit_seconds": 1,
    "default_timeout_seconds": None,
    "on_timeout": "fail-open: <what the harness does when the hook outlives its timeout>",
    "margin_seconds": 1.5,
}


# 3. HARNESS SYNTAX ADAPTERS. Pure translation/rendering only.
def to_event(gate, raw):
    raise NotImplementedError("translate harness event to gate.GateEvent (None: not a tool event)")


def emit(gate, decision) -> int:
    raise NotImplementedError("render gate.render(decision) using the harness blocking protocol")


def read_harness_event():
    raise NotImplementedError("read one harness-native event")


# 4. MAIN. Copy byte-for-byte.
def main() -> int:
    if _PROJECTION_ERROR is not None:
        return _emergency_block(_PROJECTION_ERROR[1], rule=_PROJECTION_ERROR[0])
    try:
        raw = read_harness_event()
    except BaseException as exc:
        return _emergency_block(
            f"the harness event could not be read ({type(exc).__name__}: {exc})",
            rule="gate.event_unreadable")
    try:
        gate = _load_gate()
    except BaseException as exc:
        return _emergency_block(
            f"common gate could not be loaded ({type(exc).__name__}: {exc})")
    try:
        event = to_event(gate, raw)
        if event is None:
            return 0
        bound = gate.harness_bound(HARNESS, os.path.abspath(__file__), _START, cwd=event.cwd)
        decision = gate.decide(event, gate.GateProfile(**PROFILE), bound=bound,
                               permitted_roles=_ROLE_PERMITTED)
        return emit(gate, decision)
    except BaseException as exc:
        return _emergency_block(
            f"shim could not translate/emit the event ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
