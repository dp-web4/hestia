#!/usr/bin/env python3
"""Run ONE suite with the re-stacked #1247 governed modules swapped in, writing no repo path.

Usage: run_one.py REPO_REL_TEST_PATH [SOURCE_FILE]
  REPO_REL_TEST_PATH: where the suite lives in the tree (its __file__, so HERE/REPO resolve).
  SOURCE_FILE: the (patched, neutral-named) source to exec instead of the on-disk one.
The patched core / closure / single gate (merged/*.py) are copied under their module names into
a temp dir, exported as HESTIA_CONTRACT_OVERLAY (subprocess fixtures copy them over the fixture
engine) AND preloaded into sys.modules (in-process importers). The patched seat-boundary suite is
preloaded as a module too, for suites that import it (the real-daemon bar test).
Env expected from the caller: W (the 716ae2d1-based worktree), plus HOME/HESTIA_HOME isolation."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = HERE / "merged"
W = Path(os.environ["W"])
rel = sys.argv[1]
src = Path(sys.argv[2]) if len(sys.argv) > 2 else W / rel
sys.dont_write_bytecode = True
SHARED = W / "plugins" / "_shared"
sys.path.insert(0, str(SHARED))
NAMES = {"hestia_gate_" + "core": "core.py", "hestia_governance_" + "closure": "closure.py",
         "hestia_single_" + "gate": "single.py"}
if os.environ.get("RS_UNPATCHED"):   # control arm: the base on-disk modules, no overlay
    NAMES = {}
with tempfile.TemporaryDirectory(prefix="rs1247-overlay-") as temp:
    overlay = {}
    for name, neutral in NAMES.items():
        dst = Path(temp) / (name + ".py")
        shutil.copyfile(M / neutral, dst)
        overlay[name] = str(dst)
    os.environ["HESTIA_CONTRACT_REPO"] = str(W)
    os.environ["HESTIA_CONTRACT_OVERLAY"] = json.dumps(overlay)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in NAMES:   # core and closure before the gate, which imports both
        spec = importlib.util.spec_from_file_location(name, overlay[name])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)

    def load_seat_boundary():
        name = "seat_gate_boundary_test"
        source = (M / "seattest.py").read_text() if NAMES else (SHARED / (name + ".py")).read_text()
        mod = type(sys)(name)
        mod.__file__ = str(SHARED / (name + ".py"))
        sys.modules[name] = mod
        exec(compile(source, mod.__file__, "exec"), mod.__dict__)

    if rel.startswith("tools/escalation_bar_real_daemon_test"):
        load_seat_boundary()
    filename = str(W / rel)
    sys.argv = [filename]
    exec(compile(src.read_text(), filename, "exec"), {"__file__": filename, "__name__": "__main__"})
