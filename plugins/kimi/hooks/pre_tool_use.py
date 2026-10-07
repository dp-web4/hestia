#!/usr/bin/env python3
"""Hestia PreToolUse gate for Kimi Code: the certified shim (one-gate stage C).

This file is `plugins/_template/shim_template.py` with this harness's data and adapters. It
translates Kimi's PreToolUse event into a GateEvent, asks the common gate
(`$HESTIA_HOME/shared/hestia_single_gate.py`) to decide inside the deadline this harness's real
registration allows, and renders the verdict. Every law-bearing step is the common gate's.

HARNESS FACTS (data below, not code):
  - registration: flat `[[hooks]]` tables (`event = "PreToolUse"`) in `~/.kimi-code/config.toml`;
    `timeout` in seconds. Kimi's default for an entry that declares none is not documented
    here, so such an entry is refused, never guessed.
  - Kimi's hook engine FAILS OPEN on every failure mode (verified from the binary: timeout,
    spawn failure, a non-2 exit, an exception all allow the tool).
  - the correlation key is Kimi's `tool_call_id`, read from the raw event by the common gate.

HARNESS-DIFFERENCE: read_harness_event - one JSON object on stdin; an empty or non-object event is no event, which the template refuses (the pre-template gate read empty stdin as `{}` and allowed it).
HARNESS-DIFFERENCE: to_event - Kimi is Claude-Code lineage (`path`-keyed inputs are in the law's reach table), so translation is the identity; `hook_event_name` other than PreToolUse is not a tool event.
HARNESS-DIFFERENCE: emit - exit 2 with the rendered text on stderr blocks; exit 0 allows, with a warn or a notice shown on stderr.
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


MEMBER_ID = "kimi-code"
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
    "member_id": "kimi-code",
    "identity_path": os.environ.get("HESTIA_KIMI_IDENTITY"),
    "home_markers": (os.environ.get("HESTIA_HARNESS_HOME"),),
    "host_agent": "kimi-code",
    "client_name": "hestia-kimi-code-gate",
    "gate_path": os.path.abspath(__file__),
    "observe_dir": os.environ.get("HESTIA_OBSERVE_DIR"),
    "launch_cwd_env": "HESTIA_KIMI_LAUNCH_CWD",
    # This seat HOLDS the review door: kimi-code reaches `hestia_gate_escalation_corroborate`
    # (#1050). A fact only the harness knows; it must never default to true.
    "declares_review_door": True,
}
HARNESS = {
    "name": "kimi",
    "event": "PreToolUse",
    "registrations": (
        {"reader": "toml-hook-commands", "layout": "flat", "path": "~/.kimi-code/config.toml"},
    ),
    "timeout_unit_seconds": 1,
    "default_timeout_seconds": 30,
    "on_timeout": ("fail-open: Kimi's hook engine allows the tool on a timeout, a spawn "
                   "failure, a non-2 exit or an exception"),
    "margin_seconds": 1.5,
}


# 3. HARNESS SYNTAX ADAPTERS. Pure translation/rendering only.
def to_event(gate, raw):
    name = raw.get("hook_event_name")
    if name is not None and name != HARNESS["event"]:
        return None
    tool_input = raw.get("tool_input")
    if tool_input is None:
        tool_input = {}
    if not isinstance(tool_input, dict):
        raise ValueError(f"tool_input is a {type(tool_input).__name__}, not an object")
    tool = raw.get("tool_name")
    return gate.GateEvent(tool=tool if isinstance(tool, str) and tool else "?",
                          tool_input=tool_input, cwd=raw.get("cwd"),
                          session_id=raw.get("session_id"),
                          tool_use_id=raw.get("tool_use_id"), raw=raw)


def emit(gate, decision) -> int:
    text = gate.render(decision)
    if text:
        sys.stderr.write(text + "\n")
    return 2 if decision.blocks else 0


def read_harness_event():
    data = sys.stdin.read()
    if not data.strip():
        raise ValueError("empty hook event")
    event = json.loads(data)
    if not isinstance(event, dict):
        raise ValueError("the hook event is not a JSON object")
    return event


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
