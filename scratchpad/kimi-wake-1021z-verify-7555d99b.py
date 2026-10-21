#!/usr/bin/env python3
"""Wake-1021z: independent verification for escalation 7555d99bc158d821 (notice 30412).

Read-only. Checks:
1. The denied act: chain policy_decision 19:54:29Z, tool=search, payload_sha256 null.
2. #1361 false positive still live: deployed snapshot vs origin/main _READ_PATH_TOOLS.
3. Intent landed anyway via allowed read_file rows after the denial.
4. Adjacent probes (patch_apply 19:55:01, git_read 19:59:05, search on
   hestia_single_gate.py 19:59:14 -> escalation 7b827655bf55f4f3) are separate acts.
5. Escalation still open (no gate_escalation_decided), expires_at 1792616068.
"""
import json
import re
import subprocess
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from chain_walk import ChainWalker, payload  # noqa: E402

REPO = "/home/dp/ai-workspace/hestia"
DEPLOYED = "/home/dp/ai-workspace/governance/hestia/plugins/_shared/hestia_governance_closure.py"
ESC = "7555d99bc158d821"

fails = []

def check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        fails.append(name)

def read_path_tools(text):
    m = re.search(r"_READ_PATH_TOOLS\s*=\s*frozenset\(\{([^}]*)\}", text, re.S)
    if not m:
        m = re.search(r"_READ_PATH_TOOLS\s*=\s*\{([^}]*)\}", text, re.S)
    return sorted(re.findall(r'"([^"]+)"', m.group(1))) if m else None

# 2. frozenset membership, deployed vs origin/main
dep = open(DEPLOYED, encoding="utf-8").read()
dt = read_path_tools(dep)
main = subprocess.run(
    ["git", "-C", REPO, "show", "origin/main:plugins/_shared/hestia_governance_closure.py"],
    capture_output=True, check=True).stdout.decode()
mt = read_path_tools(main)
check("deployed _READ_PATH_TOOLS readable", dt is not None)
check("origin/main _READ_PATH_TOOLS readable", mt is not None)
if dt and mt:
    check("both lack 'search'", "search" not in dt and "search" not in mt)
    check("both lack 'git_read'", "git_read" not in dt and "git_read" not in mt)
    check("membership identical", dt == mt, f"n={len(dt)}")
log = subprocess.run(["git", "-C", REPO, "log", "--oneline", "HEAD..origin/main"],
                     capture_output=True, check=True).stdout.decode()
check("cf54d468 (#1361 fix) still unmerged", "cf54d468" not in log)

# 1,3,4,5. chain rows 19:54Z+
w = ChainWalker()
deny = None
decided = []
corrob = []
landed = []
adjacent = []
for e in w.walk(max_entries=8000):
    ts = e.get("timestamp") or ""
    if not isinstance(ts, str):
        ts = str(ts)
    if isinstance(ts, str) and ts < "2026-10-21T19:53":
        break
    et = e.get("eventType")
    p = payload(e)
    blob = json.dumps(p)
    if et == "policy_decision" and p.get("decision") == "deny" and ESC in blob:
        deny = (e.get("chainPosition"), ts, p)
    if et == "gate_escalation_decided" and p.get("escalation_id") == ESC:
        decided.append((ts, p))
    if et == "gate_escalation_corroborated" and p.get("escalation_id") == ESC:
        corrob.append((ts, p.get("corroborated_by"), p.get("stance")))
    if et == "policy_allow" and p.get("plugin_id") == "cbp-being" and p.get("tool_name") == "read_file":
        landed.append((ts, (p.get("target") or "")[:110]))
    if et == "policy_decision" and p.get("plugin_id") == "cbp-being" and p.get("decision") == "deny" and ESC not in blob:
        adjacent.append((ts, p.get("tool_name"), (p.get("reason") or "")[:90]))

check("deny row found", deny is not None)
if deny:
    pos, ts, p = deny
    print(f"  deny at chain position {pos} ({ts})")
    check("tool is search", p.get("tool_name") == "search")
    check("deny is gate.self_access", "gate.self_access" in (p.get("reason") or ""))
    check("payload_sha256 null (digest binds act text only)", p.get("payload_sha256") is None)
check("escalation still open (no decided row)", not decided, f"decided={len(decided)}")
print(f"  corroborations so far: {corrob}")
print(f"  allowed read_file rows after deny: {len(landed)}")
for ts, t in landed:
    print(f"    {ts} {t}")
check("intent landed via read_file", len(landed) >= 2)
print(f"  adjacent denied probes (separate acts): {len(adjacent)}")
for ts, t, r in adjacent:
    print(f"    {ts} {t}: {r}")

print("\nRESULT:", "ALL OK" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
