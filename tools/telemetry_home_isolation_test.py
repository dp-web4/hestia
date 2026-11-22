#!/usr/bin/env python3
"""#1184: failure-path tests must never write the ambient home's telemetry."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _assert_suite_leaves_ambient_home_absent(relative, tmp_path):
    ambient = tmp_path / "ambient-hestia-home"
    env = dict(os.environ, HESTIA_HOME=str(ambient), PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run(
        [sys.executable, str(ROOT / relative)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert not ambient.exists(), (
        f"{relative} wrote into the ambient HESTIA_HOME: "
        + "\n".join(str(path.relative_to(ambient)) for path in ambient.rglob("*") if path.is_file())
    )


def test_sprint_f_leaves_ambient_telemetry_untouched(tmp_path):
    _assert_suite_leaves_ambient_home_absent("plugins/_shared/sprintF_test.py", tmp_path)


def test_mechanism_suite_leaves_ambient_telemetry_untouched(tmp_path):
    _assert_suite_leaves_ambient_home_absent("plugins/_shared/hestia_gate_mechanism_test.py", tmp_path)
