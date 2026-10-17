import sys, subprocess, pathlib, glob
sys.path.insert(0, "/tmp/s1314e")
from apply_lib import split, apply
S = pathlib.Path("/tmp/s1314e")
p = [x for x in glob.glob("/tmp/s1314e/*.patch") if len(pathlib.Path(x).stem) == 64][0]
files = split(open(p).read())
want = {"plugins/_shared/hestia_gate_core.py": "core_rev.py",
        "tools/shell_scope_reach_battery_test.py": "battery_rev.py",
        "tools/one_gate_decide_contract_test.py": "contract_held.py"}
for f, lines in files.items():
    base = subprocess.run(["git", "-C", "/home/dp/ai-workspace/hestia", "show", f"2d79644f:{f}"],
                          capture_output=True, text=True, check=True).stdout
    got = apply(base, lines)
    if f in want:
        print(f, got == (S / want[f]).read_text())
    elif f.endswith("hestia_gate_core.py"):
        core = (S / "core_rev.py").read_text()
        print(f, "mirror body contains core_rev:", core.split("\n", 5)[-1] in got)
    else:
        print(f, "applies")
