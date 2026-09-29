#!/usr/bin/env python3
"""Regression controls for the differential acceptance exit contract."""

from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_differential as gd  # noqa: E402


def exercise(mode: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / ".wt").mkdir()
        gates = [("alpha", root / "alpha.py"), ("beta", root / "beta.py")]

        old_repo_root = gd.meter.repo_root
        old_discover = gd.meter.discover_gates
        old_run_seat = gd.run_seat
        old_corpus = gd.CORPUS
        old_argv = sys.argv
        try:
            gd.meter.repo_root = lambda _p: root
            gd.meter.discover_gates = lambda _root: (gates, [])
            gd.CORPUS = [("case", "Bash", {"command": "true"}, "read", "control")]

            def fake_run(gate: Path, cwd: Path, _cases) -> dict:
                seat = gate.stem
                if mode == "uniform-wrong":
                    return {"case": "write"}
                if mode == "partial-cwd" and seat == "beta" and cwd == root / ".wt":
                    return {"_error": "simulated cwd load failure"}
                if mode == "case-error" and seat == "alpha" and cwd == Path("/tmp"):
                    return {"case": "ERR:RuntimeError"}
                return {"case": "read"}

            gd.run_seat = fake_run
            sys.argv = ["gate_differential.py"]
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = gd.main()
            return rc, out.getvalue() + err.getvalue()
        finally:
            gd.meter.repo_root = old_repo_root
            gd.meter.discover_gates = old_discover
            gd.run_seat = old_run_seat
            gd.CORPUS = old_corpus
            sys.argv = old_argv


def main() -> int:
    rc, text = exercise("correct")
    assert rc == 0, (rc, text)
    assert "EXPECTATION MISSES: none" in text

    rc, text = exercise("uniform-wrong")
    assert rc == 1, (rc, text)
    assert "EXPECTATION MISSES: 1 (acceptance failure)" in text

    rc, text = exercise("partial-cwd")
    assert rc == 2, (rc, text)
    assert "MEASUREMENT INCOMPLETE" in text
    assert "simulated cwd load failure" in text

    rc, text = exercise("case-error")
    assert rc == 2, (rc, text)
    assert "ERR:RuntimeError" in text

    print("ok: differential exit contract rejects wrong and incomplete measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
