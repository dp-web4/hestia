#!/usr/bin/env python3
"""Run tools/governance_class_drift_test.py with the matcher (the core) READ as the re-stacked
patched copy (merged/core.py), not the on-disk c535619d one. The drift test parses the matcher
from disk (AST), so the module overlay cannot reach it; this redirects only that one read.
Run from the worktree root (W): python3 drift_probe.py"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
W = pathlib.Path(os.environ["W"]).resolve()
target = (W / "plugins" / "_shared" / ("hestia_gate_" + "core.py")).resolve()
patched = (HERE / "merged" / "core.py").read_text(encoding="utf-8")
_orig = pathlib.Path.read_text
hits = []


def read_text(self, *a, **k):
    try:
        if self.resolve() == target:
            hits.append(1)
            return patched
    except OSError:
        pass
    return _orig(self, *a, **k)


pathlib.Path.read_text = read_text
test = W / "tools" / "governance_class_drift_test.py"
sys.argv = [str(test)]
try:
    exec(compile(test.read_text(), str(test), "exec"), {"__file__": str(test), "__name__": "__main__"})
finally:
    print(f"[drift_probe] patched matcher served {len(hits)} time(s)")
