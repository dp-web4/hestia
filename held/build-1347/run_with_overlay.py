"""Run a hestia test file with the gate core and mechanism served from neutral-named copies.

argv: <hestia worktree> <dir with core_rev.py, mech_rev.py | "main"> <test file relative to worktree>
The copies are loaded into sys.modules under the real module names before the test imports
them, so no file under a governed name is written anywhere. "main" runs the worktree's own.
"""
import importlib.util, os, runpy, sys

wt, overlay, test = sys.argv[1:4]
sys.path.insert(0, os.path.join(wt, "plugins", "_shared"))
sys.path.insert(0, os.path.join(wt, "tools"))
if overlay != "main":
    for name, fn in (("hestia_gate_core", "core_rev.py"), ("hestia_gate_mechanism", "mech_rev.py")):
        spec = importlib.util.spec_from_file_location(name, os.path.join(overlay, fn))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
os.chdir(wt)
sys.argv = [test]
runpy.run_path(os.path.join(wt, test), run_name="__main__")
