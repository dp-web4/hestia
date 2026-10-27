"""Run tg_rev.py (test_gate_core.py with #1411 fixtures) as if it lived in <wt>/plugins/_shared, with the
gate core and mechanism served from the neutral copies -- both the imported modules and every read of
the core's own source text. argv: <hestia worktree> <dir with core_rev.py, mech_rev.py, tg_rev.py>"""
import builtins, importlib.util, io, os, runpy, sys

wt, ov = sys.argv[1:3]
shared = os.path.join(wt, "plugins", "_shared")
sys.path.insert(0, shared)
for name, fn in (("hestia_gate_core", "core_rev.py"), ("hestia_gate_mechanism", "mech_rev.py")):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ov, fn))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
redirect = {os.path.join(shared, "hestia_gate_core.py"): os.path.join(ov, "core_rev.py"),
            os.path.join(shared, "hestia_gate_mechanism.py"): os.path.join(ov, "mech_rev.py")}
real_open = builtins.open


def _open(file, *a, **k):
    if isinstance(file, str):
        file = redirect.get(os.path.abspath(file), file)
    return real_open(file, *a, **k)


builtins.open = _open
io.open = _open
src = real_open(os.path.join(ov, "tg_rev.py"), encoding="utf-8").read()
os.chdir(wt)
sys.argv = [os.path.join(shared, "test_gate_core.py")]
code = compile(src, os.path.join(shared, "test_gate_core.py"), "exec")
exec(code, {"__name__": "__main__", "__file__": os.path.join(shared, "test_gate_core.py")})
