#!/usr/bin/env python3
"""#1435 fix: a single-gate GateEvent (tool_input, no command/paths) through core.egress_unsweepable_deny must return,
not raise. CI on the first #1435 head (90b74740): every single-gate act failed closed as gate.internal_error.
Run: python3 tools/gate_event_reach_test.py   (applied 2026-10-31 under escalation 812eda165b4d9bd7; pass a dir
holding core_rev.py to judge a revised copy)."""
import importlib.util, pathlib, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else ""
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
if OUT:
    spec = importlib.util.spec_from_file_location("hestia_gate_core", pathlib.Path(OUT) / "core_rev.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_core"] = mod
    spec.loader.exec_module(mod)
import hestia_gate_core as core  # noqa: E402
from hestia_single_gate import GateEvent  # noqa: E402

bad = []
for tool, ti in (("Bash", {"command": "cat *.txt"}), ("Read", {"file_path": "/tmp/x"}), ("Write", {"file_path": "/tmp/y", "content": "z"})):
    try:
        v = core.egress_unsweepable_deny(GateEvent(tool=tool, tool_input=ti, cwd="/tmp"))
        if v is not None:
            bad.append(f"{tool}: expected None (nothing unsweepable), got {v.rule}")
    except Exception as e:
        bad.append(f"{tool}: raised {type(e).__name__}: {e}")
for b in bad:
    print("FAIL", b)
print("PASS" if not bad else "FAIL", "- a GateEvent through egress_unsweepable_deny")
sys.exit(1 if bad else 0)
