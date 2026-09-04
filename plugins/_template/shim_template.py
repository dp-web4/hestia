#!/usr/bin/env python3
"""CERTIFIED SHIM TEMPLATE.

A production shim may contain only these four sections:
  1. byte-identical authority bootstrap;
  2. profile DATA;
  3. harness syntax adapters (`to_event`, `emit`);
  4. the byte-identical `main` skeleton.

Anything that classifies, scopes, interprets law, chooses an enforcement mode, records a
policy decision, or sequences gates belongs in `hestia_single_gate.py`, never here.
"""
from __future__ import annotations

import importlib.util
import os
import sys


# ── 1. AUTHORITY BOOTSTRAP: byte-identical in every certified shim ──────────────────────
def _authority_dir() -> str:
    """Production authority is the installed per-user tree, never an ambient worktree.

    Tests may point at an isolated candidate only when BOTH variables are explicit.  A model
    or harness setting HESTIA_SHARED_DIR in production has no effect.
    """
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

    # The common gate legitimately imports its sibling runtime modules by canonical name.
    # Remove duplicate spellings of the selected authority path, put exactly that path first,
    # and verify the loaded module came from it.
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
    """The only decision a shim may make: no common authority means no tool execution."""
    sys.stderr.write("hestia: deny [gate.unavailable] - " + reason + "\n")
    return 2


# ── 2. PROFILE DATA: values differ; fields and semantics do not ─────────────────────────
# Filled by each concrete shim *after* the common gate loads:
# PROFILE = gate.GateProfile(...)


# ── 3. HARNESS SYNTAX ADAPTERS: the only justified code differences ────────────────────
def to_event(gate, raw):
    """Harness event -> gate.GateEvent.  Extract/rename only; do not classify."""
    raise NotImplementedError


def emit(decision) -> int:
    """gate.GateDecision -> this harness's documented blocking protocol."""
    raise NotImplementedError


# ── 4. MAIN: byte-identical apart from the PROFILE binding above ────────────────────────
def main() -> int:
    try:
        gate = _load_gate()
    except BaseException as exc:
        return _emergency_block(f"common gate could not be loaded ({type(exc).__name__}: {exc})")
    try:
        raw = read_harness_event()
        ev = to_event(gate, raw)
        decision = gate.decide(ev, PROFILE)
        return emit(decision)
    except BaseException as exc:
        # Adapter/parser failure is not a permission.  It is intentionally handled outside
        # the common gate because the failure may occur before a GateEvent can exist.
        return _emergency_block(f"shim could not translate/emit the event ({type(exc).__name__}: {exc})")


def read_harness_event():
    """Harness input transport only (usually JSON on stdin)."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
