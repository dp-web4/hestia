#!/usr/bin/env python3
"""Run existing shared test files with the HELD mechanism pre-loaded as `hestia_gate_mechanism`.

argv: <mech file> <test file>...   Each test file runs in its own subprocess (as __main__), with
plugins/_shared on sys.path and sys.modules["hestia_gate_mechanism"] bound to <mech file> first,
so every `import hestia_gate_mechanism` in the suite (and in the modules it imports) gets the held
code. Pytest-style files (no __main__ block) are run under pytest with the same preload.
"""
import pathlib
import subprocess
import sys

MECH = str(pathlib.Path(sys.argv[1]).resolve())
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
SHARED = str(ROOT / "plugins" / "_shared")
PRELOAD = (
    "import importlib.util, sys, runpy\n"
    f"sys.path.insert(0, {SHARED!r})\n"
    f"spec = importlib.util.spec_from_file_location('hestia_gate_mechanism', {MECH!r})\n"
    "m = importlib.util.module_from_spec(spec); sys.modules['hestia_gate_mechanism'] = m\n"
    "spec.loader.exec_module(m)\n"
)
bad = 0
for t in sys.argv[2:]:
    src = pathlib.Path(t).read_text(encoding="utf-8")
    if "__main__" in src or "at module scope" in src:
        code = PRELOAD + f"sys.argv=[{t!r}]\nrunpy.run_path({t!r}, run_name='__main__')\n"
    else:
        code = PRELOAD + f"import pytest\nsys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', {t!r}]))\n"
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {pathlib.Path(t).name}: {' | '.join(tail)[:300]}")
    bad += r.returncode != 0
sys.exit(1 if bad else 0)
