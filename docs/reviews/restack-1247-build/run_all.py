#!/usr/bin/env python3
"""Run the Python suites over the re-stack with the patched governed modules swapped in.
HOME / HESTIA_HOME isolated outside /tmp; no HESTIA_* from the caller (never the live daemon).
Usage: run_all.py [label-substring ...]   (RS_UNPATCHED=1 for the unpatched control arm)"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = HERE / "merged"
W = "/home/dp/ai-workspace/hestia/scratchpad/wt-1247-restack-af33"
H = os.path.expanduser("~/.cache/rs1247-home")
SH = "plugins/_shared/"
SUITES = [
    ("registered_surface", SH + "registered_surface_test.py", M / "regtest.py"),
    ("member_install_surface", SH + "member_install_surface_test.py", M / "mistest.py"),
    ("seat_gate_boundary", SH + "seat_gate_boundary_test.py", M / "seattest.py"),
    ("claim_self_write", SH + "claim_self_write_test.py", None),
    ("governance_closure", SH + "hestia_governance_closure_test.py", None),
    ("gate_core", SH + "test_gate_core.py", None),
    ("gate_mechanism", SH + "hestia_gate_mechanism_test.py", None),
    ("cross_harness_closure", SH + "cross_harness_closure_test.py", None),
    ("shim_structure", SH + "shim_structure_test.py", None),
    ("shell_grammar", SH + "shell_grammar_test.py", None),
    ("sprintD", SH + "sprintD_test.py", None),
    ("sprintE", SH + "sprintE_test.py", None),
    ("sprintF", SH + "sprintF_test.py", None),
    ("one_gate_decide_contract", "tools/one_gate_decide_contract_test.py", None),
    ("supersession_hard_stop", "tools/supersession_hard_stop_test.py", None),
    ("attempted_summary", "tools/attempted_summary_test.py", None),
    ("governance_class_drift", "tools/governance_class_drift_test.py", None),
    ("hooks_gt_test", "tools/hooks_gt_test.py", None),
]
want = sys.argv[1:]
env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
env.update({"HOME": H, "HESTIA_HOME": os.path.join(H, "hestia"), "W": W, "PYTHONDONTWRITEBYTECODE": "1"})
if os.environ.get("RS_UNPATCHED"):
    env["RS_UNPATCHED"] = "1"
os.makedirs(env["HESTIA_HOME"], exist_ok=True)
bad = 0
ran = 0
for label, rel, src in SUITES:
    if want and not any(w in label for w in want):
        continue
    ran += 1
    t = time.time()
    argv = [sys.executable, str(HERE / "run_one.py"), rel] + ([str(src)] if src and not env.get("RS_UNPATCHED") else [])
    p = subprocess.run(argv, cwd=W, env=env, capture_output=True, text=True, timeout=1800)
    out = (p.stdout + p.stderr).strip().splitlines()
    (HERE / "logs").mkdir(exist_ok=True)
    (HERE / "logs" / f"{label}{'.ctl' if env.get('RS_UNPATCHED') else ''}.log").write_text(p.stdout + p.stderr)
    tail = [ln for ln in out if any(k in ln.lower() for k in ("passed", "failed", "ok", "fail", "green", "checks"))][-1:] or out[-1:]
    bad += p.returncode != 0
    print(f"{'ok  ' if p.returncode == 0 else 'FAIL'} rc={p.returncode} {time.time() - t:6.1f}s  {label:26} {(tail or [''])[0][:120]}", flush=True)
print(f"{ran - bad}/{ran} green")
sys.exit(1 if bad else 0)
