"""Run the shipped suites with the proposed resolver injected in memory."""
import sys, importlib, traceback
SHARED = "/tmp/wt-gaterepair/plugins/_shared"
TOOLS  = "/tmp/wt-gaterepair/tools"
sys.path.insert(0, SHARED); sys.path.insert(0, TOOLS); sys.path.insert(0, "/tmp/gaterepair")
import hestia_governance_closure as g
import resolver
if "--repaired" in sys.argv:
    new_bwt, _ = resolver.make(g)
    g._bash_write_targets = new_bwt
    print("### RESOLVER INJECTED ###")
else:
    print("### SHIPPED (baseline) ###")

MODS = ["hestia_governance_closure_test", "governance_closure_arms_test",
        "cross_harness_closure_test", "hestia_gate_mechanism_test", "shell_grammar_test"]
total_fail = 0
for name in MODS:
    try:
        m = importlib.import_module(name)
    except Exception as e:
        print(f"-- {name}: IMPORT FAIL {e}"); continue
    fns = getattr(m, "ALL", None) or [getattr(m, n) for n in dir(m) if n.startswith("test_") and callable(getattr(m, n))]
    fails = []
    for fn in fns:
        try:
            fn()
        except BaseException as e:
            fails.append((getattr(fn, "__name__", str(fn)), str(e).split("\n")[0][:220]))
    total_fail += len(fails)
    print(f"-- {name}: {len(fns)-len(fails)}/{len(fns)} pass")
    for n, e in fails:
        print(f"     FAIL {n}: {e}")
print("TOTAL FAILURES:", total_fail)
