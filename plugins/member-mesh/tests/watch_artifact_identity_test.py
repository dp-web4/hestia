#!/usr/bin/env python3
"""The watcher records its startup source snapshot and detects a replacement.

A repository commit is not sufficient evidence: the watcher may run an installed
copy or a dirty worktree file. Bash does not expose its parsed buffer, so the
record is explicitly a snapshot of the source bytes at startup. This test starts
an isolated copy, verifies that snapshot, changes one byte without changing file
length, and requires an explicit restart-required drift event.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
WATCHER = HERE.parent / "hestia-watch-member.sh"
TIMEOUT = 8.0


def read_until(proc: subprocess.Popen[str], needle: str) -> str:
    lines: list[str] = []
    deadline = time.monotonic() + TIMEOUT
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.25)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line)
        if needle in line:
            return "".join(lines)
    raise AssertionError(
        f"did not observe {needle!r}; rc={proc.poll()} output={''.join(lines)!r}"
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        original = WATCHER.read_bytes()
        script.write_bytes(original)
        script.chmod(0o755)
        expected = hashlib.sha256(original).hexdigest()

        env = dict(
            os.environ,
            HOME=str(td / "home"),
            HESTIA_MESH_STATE=str(td / "state"),
            HESTIA_ENDPOINT="http://127.0.0.1:1/mcp",
            WATCH_INTERVAL="0.1",
            UNANSWERED_EVERY="3600",
        )
        proc = subprocess.Popen(
            [str(script), "artifact-test", "test-host"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        try:
            startup = read_until(proc, " ARTIFACT ")
            assert f"startup_sha256={expected}" in startup, startup
            assert str(script) not in startup, "artifact record leaked its absolute path"

            # Same-length mutation avoids the live-script byte-offset hazard while
            # proving the process distinguishes loaded bytes from current disk bytes.
            changed = original.replace(b"local-mesh", b"local_mesh", 1)
            assert changed != original and len(changed) == len(original)
            script.write_bytes(changed)
            drifted = hashlib.sha256(changed).hexdigest()

            drift = read_until(proc, "ARTIFACT DRIFT")
            assert "restart required" in drift, drift
            assert f"startup_sha256={expected}" in drift, drift
            assert f"disk_sha256={drifted}" in drift, drift
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    print("ok: watcher artifact identity and drift are observable")


if __name__ == "__main__":
    main()
