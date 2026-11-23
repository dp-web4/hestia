#!/usr/bin/env python3
"""#1184: failure-path tests must never write the ambient home's telemetry.

Run:  python3 tools/telemetry_home_isolation_test.py

CI runs this file with bare `python3`, so it carries the explicit `TESTS` list and
`__main__` block from `tools/claimable_test.py`. As pytest-style functions taking
`tmp_path` the two sentinels were discovered, defined their assertions, executed none,
and reported green (PR #1694 review, `tools/ci_selfexec_test.py`).
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def _assert_suite_leaves_ambient_home_absent(relative):
    # The ambient home is a path that must NOT come into existence. Its parent is a fresh
    # temp dir; nothing here is a scope fixture, so a /tmp parent is fine.
    with tempfile.TemporaryDirectory(prefix="telemetry-isolation-") as parent:
        ambient = Path(parent) / "ambient-hestia-home"
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


def test_sprint_f_leaves_ambient_telemetry_untouched():
    _assert_suite_leaves_ambient_home_absent("plugins/_shared/sprintF_test.py")


def test_mechanism_suite_leaves_ambient_telemetry_untouched():
    _assert_suite_leaves_ambient_home_absent("plugins/_shared/hestia_gate_mechanism_test.py")


# Explicit list, not a `globals()` sweep: `ci_selfexec_test.py` walks `ast.Name`, so a
# test is wired up only when its name is written out. The staleness check in `main()`
# is what makes the list a fix rather than a suppression.
TESTS = [
    test_sprint_f_leaves_ambient_telemetry_untouched,
    test_mechanism_suite_leaves_ambient_telemetry_untouched,
]


def main():
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, e))
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
