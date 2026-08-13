#!/usr/bin/env python3
"""Break-the-core test — PRD §7.1 criterion 9(b): deliberately break the core/policy path
and assert every adopting harness takes the DEFINED degraded path — no harness falls open,
none invents its own fallback.

Each patched shim is copied (under a neutral name) into an isolated directory and run as a
SUBPROCESS on a Write event with its core import sabotaged two ways:

  arm A — MISSING: HESTIA_WORKSPACE points at an empty directory, so the shared dir the
          shim resolves does not exist and `import` fails;
  arm B — POISONED: the shared dir exists but the core module raises on import (the
          sabotaged-sys.path arm — the module found is not importable).

Expected posture (both shims, both arms, asserted): the guarded import leaves _core=None
and main() FAILS CLOSED with its explicit Tier-2 deny (exit 2, "shared gate core could not
be loaded") — for the Write, and ALSO for a Read: the shim-level Tier-2 backstop carries
no READ_CLASS carve-out, a documented TIGHTENING of the ratified deny-writes-allow-reads
posture (per-shim tighten-only is explicitly allowed by criterion 9; the read-allow half
of the posture is computed by the CORE, which in this arm is exactly the broken thing).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.environ.get("SPRINTF_TREE") or os.path.join(HERE, "tree")
HOOK = "pre_" + "tool_use.py"
CORE = "hestia_gate_" + "core.py"


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _run(copy_path, ws, event):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"HESTIA_WORKSPACE": ws,
                "HESTIA_KIMI_GATE_MODE": "enforce",
                "HESTIA_CODEX_GATE_MODE": "enforce",
                "HESTIA_ENDPOINT": "http://127.0.0.1:9/mcp"})
    p = subprocess.run([sys.executable, copy_path], input=json.dumps(event),
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.dirname(copy_path), env=env)
    return p.returncode, p.stderr


def _event(tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "break-core-test", "cwd": ""}


def _isolated_copies(tmp):
    """Neutral-named copies far from any _shared dir, so the shims' own path candidates
    cannot accidentally resolve a working core."""
    copies = {}
    for shim, rel in (("kimi", os.path.join("plugins", "kimi", "hooks", HOOK)),
                      ("codex", os.path.join("plugins", "codex", "hooks", HOOK))):
        dst = os.path.join(tmp, f"{shim}_under_test.py")
        shutil.copy(os.path.join(TREE, rel), dst)
        copies[shim] = dst
    return copies


def _assert_fails_closed(shim, copy_path, ws, arm):
    for tool, tin in (("Write", {"file_path": os.path.join(ws, "x.md"), "content": "x"}),
                      ("Read", {"file_path": os.path.join(ws, "x.md")})):
        rc, err = _run(copy_path, ws, _event(tool, tin))
        check(f"{shim}-{arm}-{tool}-fails-closed", rc == 2, f"rc={rc} stderr={err}")
        check(f"{shim}-{arm}-{tool}-names-the-cause",
              "shared gate core could not be loaded" in err, err)


def test_missing_core_fails_closed():
    # Neutral system tmp, NOT dir=HERE: in-repo HERE is plugins/_shared, and a temp
    # workspace nested inside the closure makes every probe write classify as a
    # governance write (a different, earlier deny than the arm under test).
    with tempfile.TemporaryDirectory() as tmp:
        copies = _isolated_copies(tmp)
        ws = os.path.join(tmp, "empty-ws")
        os.makedirs(ws)
        for shim, copy_path in copies.items():
            _assert_fails_closed(shim, copy_path, ws, "missing")


def test_poisoned_core_fails_closed():
    # Neutral system tmp, NOT dir=HERE: in-repo HERE is plugins/_shared, and a temp
    # workspace nested inside the closure makes every probe write classify as a
    # governance write (a different, earlier deny than the arm under test).
    with tempfile.TemporaryDirectory() as tmp:
        copies = _isolated_copies(tmp)
        ws = os.path.join(tmp, "poisoned-ws")
        shared = os.path.join(ws, "hestia", "plugins", "_shared")
        os.makedirs(shared)
        with open(os.path.join(shared, CORE), "w", encoding="utf-8") as fh:
            fh.write("raise ImportError('sabotaged for break_the_core_test')\n")
        for shim, copy_path in copies.items():
            _assert_fails_closed(shim, copy_path, ws, "poisoned")


ALL = [test_missing_core_fails_closed, test_poisoned_core_fails_closed]

if __name__ == "__main__":
    print("Break-the-core — criterion 9(b): every adopting harness fails CLOSED, none open")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
