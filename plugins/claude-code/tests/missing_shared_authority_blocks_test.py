#!/usr/bin/env python3
"""A seat with no shared authority must BLOCK, and blocking means exit 2.

This is an integration test on purpose: it runs the real hook as a subprocess with a
shared-engine directory that does not contain the classifier, and asserts on the exit
CODE the harness will actually see. A unit assertion that some function raises would
not have caught the defect this test exists for.

The defect: the cutover first imported the shared classifier at module level, unguarded.
An ImportError then raised BEFORE main()'s handler existed, so the process died with a
traceback and exit 1. Under the PreToolUse contract only **exit 2** blocks; any other
non-zero is a hook error the harness does not treat as a refusal. So "no local copy, so
an import failure denies everything" was false -- it FAILED OPEN, which is the class
removed in #745 reappearing through a different door.

Both directions are asserted. A test that only checked the missing case would pass
against a hook that refused unconditionally, which is not a gate but a brick.
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

WRITE_EVENT = {
    "tool_name": "Bash",
    "tool_input": {"command": "echo hi > /tmp/hestia-negative-test-target"},
    "cwd": "/tmp",
}


def run(shared_dir: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HESTIA_SHARED_DIR"] = shared_dir
    # Make a branch-local classifier discoverable through ordinary Python import lookup.
    # The selected installed directory must still be authoritative: neither a missing path
    # nor an empty one may silently borrow law from PYTHONPATH/the current checkout.
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REAL_SHARED) + (
        os.pathsep + inherited_pythonpath if inherited_pythonpath else ""
    )
    # Point the daemon at a closed port so the run cannot depend on a live daemon. The
    # authority check under test happens before any of that matters.
    env["HESTIA_ENDPOINT"] = "http://127.0.0.1:1"
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(WRITE_EVENT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def require_missing_authority_refusal(
    failures: list[str], label: str, shared_dir: str
) -> None:
    got = run(shared_dir)
    if got.returncode != 2:
        failures.append(
            f"{label} returned {got.returncode}, expected 2. "
            f"Only exit 2 blocks; {got.returncode} lets the tool run. "
            f"stderr[:200]={got.stderr[:200]!r}")
    elif "no-shared-authority" not in got.stderr:
        failures.append(
            f"{label} returned exit 2 but stderr does not name the cause; a refusal "
            f"the operator cannot diagnose is a brick. stderr[:200]={got.stderr[:200]!r}")


def main() -> int:
    failures = []

    # 1. An existing but empty installed directory must fail closed.
    with tempfile.TemporaryDirectory() as empty:
        require_missing_authority_refusal(
            failures, "empty shared authority directory", empty
        )

        # 2. A path that does not exist must behave identically. This is the regression
        #    arm for the branch-local fallback: before the repair, this exact shape silently
        #    loaded plugins/_shared from the checkout and never reached no-shared-authority.
        require_missing_authority_refusal(
            failures,
            "non-existent shared authority path",
            str(Path(empty) / "not-created"),
        )

    # 3. WITH the explicitly reviewed shared fixture present the hook must NOT refuse for
    #    this reason. Without this arm the test passes against a hook that refuses everything.
    got = run(str(REAL_SHARED))
    if "no-shared-authority" in got.stderr:
        failures.append(
            "the hook reported no-shared-authority even though the engine directory was "
            f"present at {REAL_SHARED}; the guard fires unconditionally")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(
        "ok: empty and non-existent shared authority block with exit 2, "
        "and the explicit reviewed fixture does not"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
