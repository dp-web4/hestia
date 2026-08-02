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
import shutil
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
WATCHER = HERE.parent / "hestia-watch-member.sh"
TIMEOUT = 8.0


def read_until(proc: subprocess.Popen[str], needle: str, accept=None) -> str:
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
        if needle in line and (accept is None or accept(line)):
            return "".join(lines)
    raise AssertionError(
        f"did not observe {needle!r}; rc={proc.poll()} output={''.join(lines)!r}"
    )


def stop(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def start(script: Path, home: Path, **extra_env: str) -> subprocess.Popen[str]:
    env = dict(
        os.environ,
        HOME=str(home),
        HESTIA_MESH_STATE=str(home / "state"),
        HESTIA_ENDPOINT="http://127.0.0.1:1/mcp",
        WATCH_INTERVAL="0.1",
        UNANSWERED_EVERY="1",
        **extra_env,
    )
    return subprocess.Popen(
        [str(script), "artifact-test", "test-host"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def real_drift_stays_visible() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        original = WATCHER.read_bytes()
        script.write_bytes(original)
        script.chmod(0o755)
        expected = hashlib.sha256(original).hexdigest()

        proc = start(script, td / "home")
        try:
            startup = read_until(proc, "ARTIFACT plugin=")
            assert "state=ok" in startup, startup
            assert f"startup_sha256={expected}" in startup, startup
            assert str(script) not in startup, "artifact record leaked its absolute path"

            # Replace atomically. Truncating the inode bash is still parsing can make
            # it observe EOF and exit successfully before the loop starts — a flaky
            # test that reports the watcher healthy by killing it is worse than none.
            changed = original.replace(b"local-mesh", b"local_mesh", 1)
            assert changed != original and len(changed) == len(original)
            replacement = script.with_suffix(".new")
            replacement.write_bytes(changed)
            replacement.chmod(0o755)
            os.replace(replacement, script)
            drifted = hashlib.sha256(changed).hexdigest()

            drift = read_until(proc, "ARTIFACT DRIFT")
            assert "restart required" in drift, drift
            assert f"startup_sha256={expected}" in drift, drift
            assert f"disk_sha256={drifted}" in drift, drift

            # Outlive the edge alarm. The next periodic gauge must continue to
            # report drift, never return to the healthy startup-only shape.
            gauge = read_until(proc, "ARTIFACT plugin=")
            assert "state=drift" in gauge, gauge
            assert "reason=differs-from-startup" in gauge, gauge
            assert f"disk_sha256={drifted}" in gauge, gauge
        finally:
            stop(proc)


def unavailable_startup_is_absorbing() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        script.write_bytes(WATCHER.read_bytes())
        script.chmod(0o755)

        real_python = shutil.which("python3")
        assert real_python is not None
        bin_dir = td / "bin"
        bin_dir.mkdir()
        enabled = td / "python-enabled"
        shim = bin_dir / "python3"
        shim.write_text(
            "#!/bin/sh\n"
            f'[ -f "{enabled}" ] || exit 1\n'
            f'exec "{real_python}" "$@"\n'
        )
        shim.chmod(0o755)

        proc = start(
            script,
            td / "home",
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )
        try:
            startup = read_until(proc, "ARTIFACT plugin=")
            assert "state=unverifiable" in startup, startup
            assert "reason=startup-baseline-unavailable" in startup, startup
            assert "startup_sha256=unavailable" in startup, startup

            # Restoring the hasher does not create a time machine: the current disk
            # hash becomes visible evidence, but no startup baseline can be inferred.
            enabled.touch()
            later = read_until(
                proc,
                "ARTIFACT plugin=",
                lambda line: "disk_sha256=unavailable" not in line,
            )
            measured = [
                line for line in later.splitlines() if "ARTIFACT plugin=" in line
            ][-1]
            assert "state=unverifiable" in measured, later
            assert "reason=startup-baseline-unavailable" in measured, later
            assert "disk_sha256=unavailable" not in measured, later
            assert "ARTIFACT DRIFT" not in later, later
        finally:
            stop(proc)


def main() -> None:
    real_drift_stays_visible()
    unavailable_startup_is_absorbing()

    print("ok: watcher artifact state is persistent, live, and race-free")


if __name__ == "__main__":
    main()
