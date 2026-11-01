#!/usr/bin/env python3
"""A seat with no shared authority must BLOCK, and blocking means exit 2.

This is an integration test on purpose: it runs the real hook as a subprocess and asserts
on the exit CODE the harness will actually see. A unit assertion that some function raises
would not have caught either defect this test now carries.

Defect 1 (the reason the test exists). The cutover first imported the shared classifier at
module level, unguarded. An ImportError then raised BEFORE main()'s handler existed, so the
process died with a traceback and exit 1. Under the PreToolUse contract only **exit 2**
blocks; any other non-zero is a hook error the harness does not treat as a refusal. It
FAILED OPEN, the class removed in #745 reappearing through a different door.

Defect 2 (the reason the test has three arms, not two). The first version's "missing
authority" arm used TemporaryDirectory(), which EXISTS. The seat's loader fell back to the
repository `plugins/_shared` only when the installed directory was ABSENT, so an existing
empty directory suppressed the fallback and the test passed while the ordinary
missing-install state still loaded branch-local law and denied for an unrelated reason
(`gate.degraded`, never `no-shared-authority`). The control did not model the state it
named, and it would have stayed green had the fallback lived forever. So:

  arm A  the installed path does NOT EXIST          -> exit 2, names no-shared-authority
  arm B  the installed path exists, module absent   -> exit 2, names no-shared-authority
  arm C  the reviewed shared fixture, named explicitly -> the guard does NOT fire

Arm A is the one that would catch a fallback coming back: the repository copy sits right
beside this hook on every checkout, so any implicit "use the tree" path answers arm A with a
verdict that is not `no-shared-authority`. Arm C keeps the test from passing against a hook
that refuses unconditionally, which is not a gate but a brick.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"
REAL_SHARED = ROOT / "plugins" / "_shared"
# One-gate stage C: the certified shim's refusal when its common gate cannot be loaded from the
# selected authority (the pre-C hook named it `no-shared-authority`).
MARK = "gate.bootstrap_unavailable"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from projection_fixture import projection_env, write_projection  # noqa: E402

WRITE_EVENT = {
    "tool_name": "Bash",
    "tool_input": {"command": "echo hi > /tmp/hestia-negative-test-target"},
    "cwd": "/tmp",
}


def run(shared_dir: str) -> subprocess.CompletedProcess:
    # Since one-gate stage C the seat reads its authority from its vault PROJECTION (the only
    # config source; a launcher's HESTIA_SHARED_DIR is overridden by it), so the selected
    # authority is staged where the seat really reads it. The home itself has no `shared`, so
    # nothing can resolve by accident. Closed port: no live daemon can matter.
    with tempfile.TemporaryDirectory() as home:
        write_projection(home, env={"HESTIA_SHARED_DIR": shared_dir,
                                    "HESTIA_ENDPOINT": "http://127.0.0.1:1"})
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(WRITE_EVENT),
            capture_output=True,
            text=True,
            env=projection_env(home),
            timeout=60,
        )


def expect_refusal(label: str, got: subprocess.CompletedProcess, failures: list) -> None:
    if got.returncode != 2:
        failures.append(
            f"{label}: returned {got.returncode}, expected 2. Only exit 2 blocks; "
            f"{got.returncode} lets the tool run. stderr[:200]={got.stderr[:200]!r}")
    elif MARK not in got.stderr:
        failures.append(
            f"{label}: exit 2 but stderr does not name {MARK}. A deny for some OTHER reason "
            "means a module answered, and the only module that could is branch-local law. "
            f"stderr[:200]={got.stderr[:200]!r}")


def main() -> int:
    failures = []

    # A. the installed authority path does not exist at all.
    with tempfile.TemporaryDirectory() as parent:
        absent = os.path.join(parent, "shared-that-was-never-installed")
        assert not os.path.exists(absent)
        expect_refusal("A (installed path absent)", run(absent), failures)

    # B. the installed authority path exists but does not hold the engine.
    with tempfile.TemporaryDirectory() as empty:
        expect_refusal("B (installed path exists, engine absent)", run(empty), failures)

    # C. the reviewed shared fixture, selected explicitly. The guard must not fire.
    got = run(str(REAL_SHARED))
    if MARK in got.stderr:
        failures.append(
            f"C: the hook reported {MARK} even though the engine directory was present at "
            f"{REAL_SHARED}; the guard fires unconditionally")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("ok: absent AND engine-less installed paths both block with exit 2 naming "
          f"{MARK}; the explicit reviewed fixture does not trip the guard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
