#!/usr/bin/env python3
"""Hestia outcome witness — the Gemini CLI shim. Stdlib only.

Registered on the harness's post-tool event(s): AfterTool. It says WHO is witnessing and hands
the event to the shared core, `hestia_witness_core` (installed at $HESTIA_HOME/shared with the
rest of the engine). Everything else — the gate<->outcome correlation (#977), the spool (#696),
the cold-path typing, the harness event shapes — lives in the core, once.

WHY A SHIM (findings/per-harness-witness-drift-2026-09-28.md). Each harness used to carry its own
witness, and a fix landed in one copy of four: claude-code 1985 of 1986 warned acts closed by a
same-id outcome, kimi 0 of 37, codex 0 of 1, gemini's outcomes never reached the daemon. This
file is byte-identical across harnesses except the two identity lines below; a shim that needs
more than that has started to fork — extend the core instead.

DEBUG
  HESTIA_HOOK_DEBUG=1         log to the seat's state dir (hook.log)
  HESTIA_ENDPOINT=URL         override endpoint discovery
  HESTIA_WITNESS_TIMEOUT_S    per-call budget (default 2.0; tests)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

DEFAULT_PLUGIN_ID = "gemini"
HOST_AGENT_VERSION = "gemini"

PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID", DEFAULT_PLUGIN_ID)
HOOK_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# THE PROJECTION IS THE ONLY SOURCE OF THIS SEAT'S CONFIGURATION (PRD_CONFIG_FROM_VAULT; #944)
# ---------------------------------------------------------------------------
# One bootstrap locator, launcher-supplied, no default: HESTIA_HOME. Everything else — the shared
# runtime dir, the endpoint, the state dir — comes from `$HESTIA_HOME/seats/<plugin_id>.env`.
# Loaded at IMPORT (the shared dir is resolved from it). Import never fails: the outcome is
# recorded in `_PROJECTION_ERROR` and run() returns on it. Bootstrap wiring, not law.
PROJECTION_DIR = "seats"


def _load_projection(plugin_id):
    """Export the seat's rendered projection into the environment. Returns None, or the
    reason the seat is not configured — never raises."""
    home = os.environ.get("HESTIA_HOME")
    if not home:
        return ("config.unbacked", "HESTIA_HOME is not set; the launcher must supply the "
                "bootstrap locator (there is no default, by design)")
    path = os.path.join(home, PROJECTION_DIR, plugin_id + ".env")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return ("config.unbacked", f"no rendered projection for {plugin_id} at {path} ({e}); "
                "populate this seat's config in the vault (Govern -> Runtime config)")
    import hashlib
    import re
    digest = hashlib.sha256(raw).hexdigest()
    pairs = []
    for ln in raw.decode("utf-8", "replace").split("\n"):
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            return ("config.unbacked", f"projection {path} carries an unusable key {k!r}")
        pairs.append((k, v))
    # OWNERSHIP RIDES ON EVERY LINE (design A): `TOKEN__KEY` lines belong to one seat.
    token = "".join(ch.upper() if ch.isalnum() else "_" for ch in plugin_id)
    projected = {}
    for k, v in pairs:
        if "__" in k:
            prefix, bare = k.split("__", 1)
            if prefix != token:
                return ("config.miswired", f"projection {path} carries a line for seat token "
                        f"{prefix!r}, but this seat is {token!r} ({plugin_id}); a line cannot be "
                        "consumed by a seat it was not rendered for")
            k = bare
        projected[k] = v
    if "HESTIA_HOME" in projected and os.path.realpath(projected["HESTIA_HOME"]) != os.path.realpath(home):
        return ("config.miswired", f"the launcher supplied HESTIA_HOME={home!r} but the vault "
                f"projection says {projected['HESTIA_HOME']!r}; this seat is running against a "
                "home the authority does not name")
    if projected.get("HESTIA_PLUGIN_ID", plugin_id) != plugin_id:
        return ("config.miswired", f"projection {path} says HESTIA_PLUGIN_ID="
                f"{projected['HESTIA_PLUGIN_ID']!r} but this seat is {plugin_id!r}")
    for k, v in projected.items():
        if k == "HESTIA_ROLE":
            continue   # launch context, never config
        os.environ[k] = v
    os.environ["HESTIA_PROJECTION_SHA256"] = digest
    os.environ["HESTIA_PROJECTION_PATH"] = path
    return None


_PROJECTION_ERROR = _load_projection(PLUGIN_ID)

# Resolved AFTER the projection: the vault may name it (projection_consumer_test pins this). No
# default is spelled here -- once the core loads, its STATE_DIR (one rule, in the engine) is used.
STATE_DIR = os.environ.get("HESTIA_STATE_DIR")


# ---------------------------------------------------------------------------
# The core is loaded ONLY from the installed authority directory — the gates' loader, verbatim in
# behaviour: never a checkout fallback (#742/#747).
# ---------------------------------------------------------------------------
def _shared_runtime_dir():
    explicit = os.environ.get("HESTIA_SHARED_DIR")
    if explicit:
        return explicit
    home = os.environ.get("HESTIA_HOME")
    return os.path.join(home, "shared") if home else ""


def _load_shared_module(name):
    """Load the named module only from the selected installed authority directory."""
    import importlib.util

    shared = _shared_runtime_dir()
    required = os.path.realpath(os.path.join(shared, name + ".py"))
    if not os.path.isfile(required):
        raise ImportError(f"installed Hestia shared module {name!r} is unavailable at {required!r}; "
                          "run deploy/install-members.sh")
    selected_dir = os.path.dirname(required)
    selected_key = os.path.normcase(selected_dir)
    retained = []
    for entry in sys.path:
        try:
            entry_key = os.path.normcase(os.path.realpath(os.fspath(entry) or os.getcwd()))
        except (TypeError, ValueError, OSError):
            retained.append(entry)
            continue
        if entry_key != selected_key:
            retained.append(entry)
    sys.path[:] = [selected_dir, *retained]
    cached = sys.modules.get(name)
    if cached is not None:
        cached_file = getattr(cached, "__file__", None)
        if cached_file and os.path.realpath(cached_file) == required:
            return cached
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, required)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot construct a loader for installed module {required!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:
        sys.modules.pop(name, None)
        raise ImportError(f"installed Hestia shared module {name!r} failed to initialize") from exc
    return module


core = None
_CORE_ERROR = None
if _PROJECTION_ERROR is None:
    try:
        core = _load_shared_module("hestia_witness_core")
        core.configure(plugin_id=PLUGIN_ID, host_agent_version=HOST_AGENT_VERSION,
                       hook_version=HOOK_VERSION)
        STATE_DIR = str(core.STATE_DIR)
    except Exception as e:  # noqa: BLE001 — recorded below, never raised into the harness
        core, _CORE_ERROR = None, f"{type(e).__name__}: {e}"


def _note_unwitnessed(why: str) -> None:
    """The core could not run, so this act reaches no chain. Say so where an operator looks —
    a silent skip is how four witness copies drifted for two months without anyone seeing."""
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {PLUGIN_ID} unwitnessed: {why}\n"
    where = STATE_DIR or os.environ.get("HESTIA_HOME")
    try:
        if not where:
            raise OSError("no state dir and no HESTIA_HOME")
        os.makedirs(where, exist_ok=True)
        with open(os.path.join(where, "witness-unwitnessed.log"), "a") as f:
            f.write(line)
    except OSError:
        sys.stderr.write("hestia: " + line)


def run() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    if _PROJECTION_ERROR is not None:
        # No projection, no authority to witness as. Infrastructure, not conduct.
        _note_unwitnessed(f"projection {_PROJECTION_ERROR[0]}: {_PROJECTION_ERROR[1]}")
        return 0
    if core is None:
        _note_unwitnessed(f"witness core unavailable: {_CORE_ERROR}")
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        core._debug_log(f"bad json: {e}")
        return 0
    return core.run(event)


BACKGROUND_MARKER = "--hestia-bg"


def fire_and_forget() -> None:
    """Relaunch self detached so the harness doesn't block on the round-trip."""
    raw = sys.stdin.buffer.read()
    kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), BACKGROUND_MARKER], **kwargs)
        if proc.stdin is not None:
            proc.stdin.write(raw)
            proc.stdin.close()
    except OSError:
        pass


if __name__ == "__main__":
    try:
        if BACKGROUND_MARKER in sys.argv:
            sys.exit(run())
        fire_and_forget()
        sys.exit(0)
    except Exception:  # noqa: BLE001 — the witness never fails the tool call
        sys.exit(0)
