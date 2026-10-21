# Generic runner: preload the v2-patched closure modules under their real names,
# then exec a suite file as __main__ (its own sys.path lines become harmless no-ops).
import importlib.util
import pathlib
import sys

V = pathlib.Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


load("hestia_governance_closure", V / "gclosure.py")
load("hestia_witness_core", V / "wcore.py")

target = V / sys.argv[1]
exec(compile(target.read_text(), str(target), "exec"),
     {"__name__": "__main__", "__file__": str(target)})
