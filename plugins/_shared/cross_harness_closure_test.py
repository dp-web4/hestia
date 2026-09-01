#!/usr/bin/env python3
"""Cross-harness governance-closure test — PRD §7.3 criterion 8.

For EACH of the three wired shims (the patched copies are IMPORTED, so what is asserted
is the classifier each shim actually holds after wiring, not the module in isolation):

  * a Write, an Edit, and a Bash redirect targeting
      (a) the shared gate core            (hestia_gate_core.py)
      (b) the shared mechanism module     (hestia_gate_mechanism.py)
      (c) the closure module ITSELF       (hestia_governance_closure.py)
      (d) the installer                   (deploy/install-members.sh)
      (e) a registration config path      (~/.claude/settings.json)
    classifies "write" — refused-and-escalatable: the verdict carries a rule id, which is
    what each shim's escalate/deny path keys its record on;
  * a read-only command NAMING the same file classifies "read" (allowed + witnessed);
  * and the shim is genuinely WIRED: its `_closure_classify` is the shared module's
    `classify`, not None (fallback engaged) and not a third copy.

Negative control: an ordinary write far from the closure classifies "none" through every
shim — a classifier that denies everything would green the write rows for free.

Paths (env-overridable):
  HGC_CLAUDE / HGC_KIMI / HGC_CODEX  — patched shim copies
  HGC_SHARED                         — dir holding the shared modules
Defaults resolve into ./build/ beside this file (built by build/stage.py + build/patch_all.py).

Run:  python3 cross_harness_closure_test.py     (or -m pytest)
"""
import importlib.util
import os
import sys

_HOOK = "pre_" + "tool_use.py"   # named as data (two parts), never a write destination
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")

# Defaults resolve IN-REPO relative to this file (plugins/_shared/ -> sibling plugin hooks
# dirs); the HGC_* env overrides and the build/ staging layout remain for out-of-tree runs.
_PLUGINS = os.path.dirname(HERE)


def _shim_default(plugin):
    in_repo = os.path.join(_PLUGINS, plugin, "hooks", _HOOK)
    if os.path.isfile(in_repo):
        return in_repo
    return os.path.join(BUILD, "p", plugin, "h", _HOOK)


SHARED = os.environ.get("HGC_SHARED") or (HERE if os.path.isfile(
    os.path.join(HERE, "hestia_governance_closure.py")) else os.path.join(BUILD, "p", "_shared"))
SHIM_FILES = {
    "claude": os.environ.get("HGC_CLAUDE") or _shim_default("claude-code"),
    "kimi": os.environ.get("HGC_KIMI") or _shim_default("kimi"),
    "codex": os.environ.get("HGC_CODEX") or _shim_default("codex"),
}

# This is an intentional reviewed fixture, not a runtime authority fallback. #742 makes
# Codex load governing modules only from explicit HESTIA_SHARED_DIR or installed
# $HESTIA_HOME/shared. Point the synthetic cross-harness fixture at the exact shared tree
# it is testing so the test exercises the new loader contract rather than depending on
# ambient sys.path behavior.
os.environ.setdefault("HESTIA_SHARED_DIR", SHARED)

# The module must be importable BEFORE the shims load (each shim's own sys.path insert
# also points at a _shared dir; this entry guarantees all three bind the SAME module,
# which the wiring test below then asserts by identity).
sys.path.insert(0, SHARED)
# kimi/codex capture WORKSPACE at import; pin it away from any real workspace.
os.environ.setdefault("HESTIA_WORKSPACE", os.path.join(BUILD, "ws"))
os.makedirs(os.environ["HESTIA_WORKSPACE"], exist_ok=True)

import hestia_governance_closure as hgc  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(f"wired_shim_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHIMS = {name: _load(name, path) for name, path in SHIM_FILES.items()}

# ── the closure elements under test — the EXPLICIT ALL list (§7.3(8) a–e) ────────────
WS = "/ws-under-test/hestia"
ALL_TARGETS = [
    ("a-core", f"{WS}/plugins/_shared/hestia_gate_core.py"),
    ("b-mechanism", f"{WS}/plugins/_shared/hestia_gate_mechanism.py"),
    ("c-closure-module-itself", f"{WS}/plugins/_shared/hestia_governance_closure.py"),
    ("d-installer", f"{WS}/deploy/install-members.sh"),
    ("e-registration-config", "/home/member/.claude/settings.json"),
]

WRITE_SHAPES = [
    ("Write", lambda p: ("Write", {"file_path": p, "content": "x"})),
    ("Edit", lambda p: ("Edit", {"file_path": p, "old_string": "a", "new_string": "b"})),
    ("Bash-redirect", lambda p: ("Bash", {"command": f"echo pwned > {p}"})),
]

READ_SHAPE = lambda p: ("Bash", {"command": f"grep -n marker {p}"})  # noqa: E731


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _classify(shim, tool, tin):
    return shim._closure_classify(tool, tin)


# ── tests ────────────────────────────────────────────────────────────────────────────
def test_shims_are_wired_to_the_one_module():
    """Wiring, not agreement: each patched shim holds THE shared classify — import
    succeeded (no fallback engaged) and it is the same function object, not a copy."""
    for name, shim in SHIMS.items():
        check(f"{name}_has_classifier", getattr(shim, "_closure_classify", None) is not None,
              f"{name}: _closure_classify is None (fallback engaged) or absent")
        check(f"{name}_is_shared_module", shim._closure_classify is hgc.classify,
              f"{name}: bound {shim._closure_classify!r}, expected hgc.classify")


def test_every_closure_write_shape_classifies_write():
    """(a)-(e) × Write/Edit/Bash-redirect × 3 shims: classification 'write' with a rule
    id — the refused-and-escalatable posture every shim's deny path keys on."""
    for shim_name, shim in SHIMS.items():
        for tname, target in ALL_TARGETS:
            for sname, shape in WRITE_SHAPES:
                tool, tin = shape(target)
                v = _classify(shim, tool, tin)
                check(f"{shim_name}[{tname}][{sname}]_write",
                      v.classification == "write",
                      f"got {v.classification!r} (marker={v.marker!r} rule={v.rule!r})")
                check(f"{shim_name}[{tname}][{sname}]_rule",
                      bool(v.rule), f"write verdict carries no rule id: {v!r}")
                check(f"{shim_name}[{tname}][{sname}]_resource",
                      v.resource == target,
                      f"resource {v.resource!r} != target (the record must name the ACT)")


def test_read_only_command_naming_same_files_classifies_read():
    """The FP class this module retires: NAMING a closure file in a read position is
    'read' (allowed + witnessed), never 'write'."""
    for shim_name, shim in SHIMS.items():
        for tname, target in ALL_TARGETS:
            tool, tin = READ_SHAPE(target)
            v = _classify(shim, tool, tin)
            check(f"{shim_name}[{tname}]_read", v.classification == "read",
                  f"got {v.classification!r} (rule={v.rule!r} resource={v.resource!r})")


def test_read_tool_on_closure_is_read():
    """The Read tool on a closure file is 'read' through every shim (publish-the-law)."""
    for shim_name, shim in SHIMS.items():
        for tname, target in ALL_TARGETS:
            v = _classify(shim, "Read", {"file_path": target})
            check(f"{shim_name}[{tname}]_Read_tool", v.classification == "read",
                  f"got {v.classification!r}")


def test_ordinary_write_is_none_control():
    """Negative control: a deny-everything classifier would green the write rows for the
    wrong reason. An ordinary write and an ordinary command classify 'none'."""
    for shim_name, shim in SHIMS.items():
        for tool, tin in [
            ("Write", {"file_path": f"{WS}/forum/claude-code/notes.md", "content": "x"}),
            ("Bash", {"command": "echo hi > /tmp/scratch/out.txt"}),
        ]:
            v = _classify(shim, tool, tin)
            check(f"{shim_name}_none_control[{tool}]", v.classification == "none",
                  f"got {v.classification!r} (marker={v.marker!r})")


# Explicit list — NOT a globals() sweep (tools/ci_selfexec_test.py convention: every test
# name must be a static reference).
ALL = [
    test_shims_are_wired_to_the_one_module,
    test_every_closure_write_shape_classifies_write,
    test_read_only_command_naming_same_files_classifies_read,
    test_read_tool_on_closure_is_read,
    test_ordinary_write_is_none_control,
]

if __name__ == "__main__":
    print("cross-harness governance-closure test (PRD §7.3 criterion 8) — "
          f"{len(SHIMS)} shims x {len(ALL_TARGETS)} closure elements")
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
          f"({len(SHIMS)*len(ALL_TARGETS)*len(WRITE_SHAPES)} write rows, "
          f"{len(SHIMS)*len(ALL_TARGETS)*2} read rows, {len(SHIMS)*2} none controls)")
    sys.exit(0)
