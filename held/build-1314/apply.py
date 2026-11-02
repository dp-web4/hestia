import os, subprocess
from apply_lib import split, apply
from scratch import require_scratch
REPO = os.environ["HESTIA_1314_REPO"]
BASE = "2d79644f"
OUT = require_scratch()

files = split(open(OUT / "held.txt").read())
names = {"plugins/_shared/hestia_gate_core.py": "core_held.py",
         "tools/shell_scope_reach_battery_test.py": "battery_held.py",
         "tools/one_gate_decide_contract_test.py": "contract_held.py"}
for f, n in names.items():
    base = subprocess.run(["git", "-C", REPO, "show", f"{BASE}:{f}"], capture_output=True, text=True, check=True).stdout
    (OUT / n).write_text(apply(base, files[f]))
    (OUT / n.replace("_held", "_main")).write_text(base)
print("ok")
