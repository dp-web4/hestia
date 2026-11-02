#!/usr/bin/env python3
"""Run one gate test file with the REVISED gate core served as hestia_gate_core: the imported module
AND every read of their source text. argv: <hestia worktree> <dir with core_rev.py | ""> <test file>
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
# Each revised module the overlay dir holds is served in place of the worktree's: the imported module AND every
# read of its source text. (build-1450a adds the mechanism to build-1331h's core-only overlay.)
REVISED = {"core_rev.py": "hestia_gate_core", "mechanism_rev.py": "hestia_gate_mechanism"}
if ov:
    served = {}
    for fname, modname in REVISED.items():
        rev = os.path.join(ov, fname)
        if not os.path.exists(rev):
            continue
        served[os.path.join(shared, modname + ".py")] = rev
    real_open = builtins.open

    def _open(file, *a, **k):
        if isinstance(file, (str, os.PathLike)):
            file = served.get(os.path.abspath(os.fspath(file)), file)
        return real_open(file, *a, **k)

    builtins.open = _open
    io.open = _open
    for fname, modname in REVISED.items():   # core before mechanism: the mechanism imports the core
        rev = os.path.join(ov, fname)
        if os.path.exists(rev):
            spec = importlib.util.spec_from_file_location(modname, rev)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
os.chdir(wt)
src = open(test, encoding="utf-8").read()
if '__name__ == "__main__"' in src or "__name__ == '__main__'" in src:
    sys.argv = [test]
    runpy.run_path(test, run_name="__main__")
else:
    import pytest
    sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "-c", os.devnull, test]))
