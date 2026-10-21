#!/usr/bin/env python3
"""Wake-1021x: independent verification for escalations d32161e2aeb8c689 + 28af7f7ce6a40f9a.

Read-only. Checks:
1. Deployed snapshot /home/dp/ai-workspace/governance/hestia/.../_shared/hestia_governance_closure.py
   _READ_PATH_TOOLS membership (search / git_read present?).
2. origin/main repo copy membership (has the #1361 remedy merged?).
3. Chain rows 19:25-19:35Z: the refused memory_edit/memory_write policy_decisions,
   the 19:28:00Z allowed write of scratch/hestia_governance_closure_fix.py,
   and any gate_escalation_decided on cf54d46850bcdfe0.
4. SAGE scratch dir: does hestia_governance_closure.py exist (should NOT — refused),
   does hestia_governance_closure_fix.py exist (should — allowed)?
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from chain_walk import ChainWalker, payload  # noqa: E402

REPO = "/home/dp/ai-workspace/hestia"
DEPLOYED = "/home/dp/ai-workspace/governance/hestia/plugins/_shared/hestia_governance_closure.py"
SCRATCH = "/home/dp/ai-workspace/SAGE/sage/instances/cbp-qwen3.8-distill-4b/scratch"

fails = []

def check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        fails.append(name)

def read_path_tools(text):
    m = re.search(r"_READ_PATH_TOOLS\s*=\s*frozenset\(\{([^}]*)\}", text, re.S)
    if not m:
        m = re.search(r"_READ_PATH_TOOLS\s*=\s*\{([^}]*)\}", text, re.S)
    if not m:
        return None
    return sorted(re.findall(r'"([^"]+)"', m.group(1)))

# 1. deployed snapshot
dep = open(DEPLOYED, encoding="utf-8").read()
dep_tools = read_path_tools(dep)
for i, line in enumerate(dep.splitlines(), 1):
    if "_READ_PATH_TOOLS" in line and "=" in line:
        print(f"  deployed _READ_PATH_TOOLS at line {i}")
        break
check("deployed snapshot readable", dep_tools is not None)
if dep_tools:
    check("deployed lacks 'search'", "search" not in dep_tools, f"search in set: {'search' in dep_tools}")
    check("deployed lacks 'git_read'", "git_read" not in dep_tools, f"git_read in set: {'git_read' in dep_tools}")

# 2. origin/main repo copy
main = subprocess.run(
    ["git", "-C", REPO, "show", "origin/main:plugins/_shared/hestia_governance_closure.py"],
    capture_output=True, check=True).stdout.decode()
main_tools = read_path_tools(main)
check("origin/main _READ_PATH_TOOLS readable", main_tools is not None)
if main_tools:
    print(f"  origin/main has search={'search' in main_tools} git_read={'git_read' in main_tools}")
same = (dep_tools == main_tools) if (dep_tools and main_tools) else None
check("deployed membership == origin/main membership", same is True, f"same={same}")

# 3. chain rows
w = ChainWalker()
hits = []
for e in w.walk(max_entries=4000):
    ts = e.get("timestamp") or e.get("ts") or ""
    et = e.get("eventType") or ""
    if not isinstance(ts, str):
        ts = str(ts)
    if "2026-10-21T19:2" in ts or "2026-10-21T19:3" in ts:
        p = payload(e)
        blob = json.dumps(p)
        if any(k in blob for k in ("d32161e2", "28af7f7c", "cf54d468", "hestia_governance_closure")):
            hits.append((ts, et, p))
    if ts < "2026-10-21T19:20" and isinstance(ts, str) and ts.startswith("2026-10-21"):
        break

print(f"\n== {len(hits)} relevant chain rows 19:20-19:40Z ==")
for ts, et, p in hits:
    s = json.dumps(p)
    print(f"--- {ts} {et}")
    print(f"    {s[:600]}")

# 4. scratch dir state
print("\n== scratch dir ==")
try:
    names = sorted(os.listdir(SCRATCH))
    gov = [n for n in names if "governance_closure" in n]
    print(f"  governance_closure* files: {gov}")
    check("placeholder-name file absent (refusal held)",
          "hestia_governance_closure.py" not in gov, str(gov))
    check("_fix.py present (allowed write landed)",
          any(n.startswith("hestia_governance_closure_fix") for n in gov), str(gov))
except FileNotFoundError:
    check("scratch dir exists", False, SCRATCH)

print("\nRESULT:", "ALL OK" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
