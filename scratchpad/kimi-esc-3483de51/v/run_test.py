# Runs the v2-patched closure_read_tool_names_test.py from renamed scratch copies.
# Only two lines of the test source are rewritten (bootstrap paths); every check is verbatim.
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

src = (V / "test_v2.py").read_text()
a = "ROOT = pathlib.Path(__file__).resolve().parent.parent"
assert src.count(a) == 1, "ROOT line not found verbatim"
src = src.replace(a, "ROOT = pathlib.Path(__file__).resolve().parent")
c = '(ROOT / "plugins" / "gemini" / "hooks" / "before_tool.py")'
assert src.count(c) == 1, "gemini lineage path not found verbatim"
src = src.replace(c, '(ROOT / "gemini_before_tool.py")')

exec(compile(src, str(V / "test_v2.py"), "exec"),
     {"__name__": "__main__", "__file__": str(V / "test_v2.py")})
