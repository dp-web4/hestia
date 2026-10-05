#!/usr/bin/env python3
"""Cross-harness governance-closure test — PRD §7.3 criterion 8, on the stage-C shims.

Before one-gate stage C each shim held a `_closure_classify` and this test asserted it was the
shared module's. Since C no shim classifies anything: each seat's shim TRANSLATES its
harness's event (`to_event`, imported from the real shim file) and the one common gate decides
(`hestia_single_gate._closure_view`, the closure step of `decide()`). So what this asserts now
is the per-harness half the cutover could still get wrong — that every seat's TRANSLATION of
each write shape still reaches the shared classifier as a write:

  * a Write, an Edit, and a shell redirect — in EACH seat's own event shape (codex: `bash`,
    and a Write is an `apply_patch`; gemini: `write_file`, `replace`, `run_shell_command`) —
    targeting
      (a) the shared gate core            (hestia_gate_core.py)
      (b) the shared mechanism module     (hestia_gate_mechanism.py)
      (c) the closure module ITSELF       (hestia_governance_closure.py)
      (d) the installer                   (deploy/install-members.sh)
      (e) a registration config path      (~/.claude/settings.json)
      (f) the common gate itself          (hestia_single_gate.py)
    classifies "write" with a rule id and names the act's resource;
  * a read-only command NAMING the same file classifies "read" (allowed + witnessed);
  * and the wiring: no shim carries a classifier of its own, and the gate's classifier IS the
    shared module's.

Negative control: an ordinary write far from the closure classifies "none" through every seat.

Run:  python3 cross_harness_closure_test.py     (or -m pytest)
Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_OVERLAY, HESTIA_CONTRACT_SHIMS.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGINS = os.path.dirname(HERE)
_HOOK = "pre_" + "tool_use.py"   # named as data (two parts), never a write destination
_GEM = "before_" + "tool.py"
OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
SHIM_OVERRIDE = json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}")
SHIM_FILES = {s: SHIM_OVERRIDE.get(s) or os.path.join(_PLUGINS, d, "hooks", f)
              for s, d, f in (("claude-code", "claude-code", _HOOK), ("codex", "codex", _HOOK),
                              ("kimi", "kimi", _HOOK), ("gemini", "gemini", _GEM))}

# The shims run their projection loader at import; no ambient home may rebind anything here.
os.environ.pop("HESTIA_HOME", None)
sys.path.insert(0, HERE)
for _name in ("hestia_gate_core", "hestia_governance_closure", "hestia_gate_mechanism",
              "hestia_single_gate"):
    if _name in OVERLAY:
        _spec = importlib.util.spec_from_file_location(_name, OVERLAY[_name])
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)

import hestia_governance_closure as hgc  # noqa: E402
import hestia_single_gate as gate  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(f"wired_shim_{name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHIMS = {name: _load(name, path) for name, path in SHIM_FILES.items()}

WS = "/ws-under-test/hestia"
ALL_TARGETS = [
    ("a-core", f"{WS}/plugins/_shared/hestia_gate_core.py"),
    ("b-mechanism", f"{WS}/plugins/_shared/hestia_gate_mechanism.py"),
    ("c-closure-module-itself", f"{WS}/plugins/_shared/hestia_governance_closure.py"),
    ("d-installer", f"{WS}/deploy/install-members.sh"),
    ("e-registration-config", "/home/member/.claude/settings.json"),
    ("f-common-gate", "/home/member/.hestia/shared/hestia_single_" + "gate.py"),
]


def native(seat, shape, path):
    """One write or read shape, in this harness's own event vocabulary."""
    if shape == "Write":
        tool, ti = "Write", {"file_path": path, "content": "x"}
    elif shape == "Edit":
        tool, ti = "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}
    elif shape == "Bash-redirect":
        tool, ti = "Bash", {"command": f"echo pwned > {path}"}
    else:  # read-only command naming the file
        tool, ti = "Bash", {"command": f"grep -n marker {path}"}
    if seat == "codex":
        if tool in ("Write", "Edit"):
            verb = "Add" if tool == "Write" else "Update"
            return {"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                    "tool_input": {"input": f"*** Begin Patch\n*** {verb} File: {path}\n+x\n*** End Patch\n"}}
        return {"hook_event_name": "PreToolUse", "tool_name": "bash", "tool_input": ti}
    if seat == "gemini":
        g = {"Write": "write_file", "Edit": "replace", "Bash": "run_shell_command"}[tool]
        return {"hook_event_name": "BeforeTool", "tool_name": g, "tool_input": ti}
    if seat == "kimi" and "file_path" in ti:
        ti = dict(ti, path=ti.pop("file_path"))
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}


def classify(seat, raw):
    event = SHIMS[seat].to_event(gate, raw)
    return gate._closure_view(event)


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def test_no_shim_classifies_and_the_gate_holds_the_shared_classifier():
    for name, shim in SHIMS.items():
        check(f"{name}_holds_no_classifier", not hasattr(shim, "_closure_classify")
              and not hasattr(shim, "_touches_self"), f"{name} carries a classifier of its own")
    check("gate_uses_the_shared_module", gate.closure is hgc,
          f"the gate bound {gate.closure!r}, expected the shared module")


def test_every_closure_write_shape_classifies_write():
    for seat in SHIMS:
        for tname, target in ALL_TARGETS:
            for shape in ("Write", "Edit", "Bash-redirect"):
                v = classify(seat, native(seat, shape, target))
                check(f"{seat}[{tname}][{shape}]_write", v is not None and v.classification == "write",
                      f"got {getattr(v, 'classification', None)!r}")
                check(f"{seat}[{tname}][{shape}]_rule", bool(v.rule), f"no rule id: {v!r}")
                check(f"{seat}[{tname}][{shape}]_resource", v.resource == target,
                      f"resource {v.resource!r} != target (the record must name the ACT)")


def test_read_only_command_naming_same_files_classifies_read():
    for seat in SHIMS:
        for tname, target in ALL_TARGETS:
            v = classify(seat, native(seat, "read", target))
            check(f"{seat}[{tname}]_read", v is not None and v.classification == "read",
                  f"got {getattr(v, 'classification', None)!r}")


def test_ordinary_write_is_none_control():
    for seat in SHIMS:
        for shape, path in (("Write", f"{WS}/forum/claude-code/notes.md"),
                            ("Bash-redirect", "/tmp/scratch/out.txt")):
            v = classify(seat, native(seat, shape, path))
            check(f"{seat}_none_control[{shape}]", v is None or v.classification == "none",
                  f"got {getattr(v, 'classification', None)!r}")


ALL = [
    test_no_shim_classifies_and_the_gate_holds_the_shared_classifier,
    test_every_closure_write_shape_classifies_write,
    test_read_only_command_naming_same_files_classifies_read,
    test_ordinary_write_is_none_control,
]

if __name__ == "__main__":
    print("cross-harness governance-closure test (PRD §7.3 criterion 8) — "
          f"{len(SHIMS)} seats x {len(ALL_TARGETS)} closure elements")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)}/{len(ALL)} tests "
          f"({len(SHIMS)*len(ALL_TARGETS)*3} write rows, {len(SHIMS)*len(ALL_TARGETS)} read rows, "
          f"{len(SHIMS)*2} none controls)")
    sys.exit(0)
