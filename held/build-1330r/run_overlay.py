#!/usr/bin/env python3
"""Run one gate test file with the REVISED gate core served as hestia_gate_core: the imported module
AND every read of the core's own source text. argv: <hestia worktree> <dir with core_rev.py | ""> <test file>
An empty overlay dir runs the same file against the worktree's own core (the control)."""
import builtins
import importlib.util
import io
import os
import runpy
import sys

wt, ov, test = sys.argv[1:4]
shared = os.path.join(wt, "plugins", "_shared")
sys.path.insert(0, shared)
sys.path.insert(0, os.path.join(wt, "tools"))
if ov:
    rev = os.path.join(ov, "core_rev.py")
    spec = importlib.util.spec_from_file_location("hestia_gate_core", rev)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_core"] = mod
    spec.loader.exec_module(mod)
    real_open, target = builtins.open, os.path.join(shared, "hestia_gate_core.py")

    def _open(file, *a, **k):
        if isinstance(file, (str, os.PathLike)) and os.path.abspath(os.fspath(file)) == target:
            file = rev
        return real_open(file, *a, **k)

    builtins.open = _open
    io.open = _open
os.chdir(wt)
src = open(test, encoding="utf-8").read()
if '__name__ == "__main__"' in src or "__name__ == '__main__'" in src:
    sys.argv = [test]
    runpy.run_path(test, run_name="__main__")
else:
    import pytest
    sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "-c", os.devnull, test]))
