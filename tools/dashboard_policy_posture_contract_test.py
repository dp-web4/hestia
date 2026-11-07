#!/usr/bin/env python3
"""Policy posture is never presented as healthy merely because it is a choice (#435).

Executes the real policyIsLoosened predicate with Node. A permissive or non-enforcing
society baseline must warn even when no per-member grant exists; an enforcing safety or
strict baseline stays calm.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

UI = (Path(__file__).resolve().parents[1] / "core/src/server/dashboard/index.html").read_text()
FAILURES = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


check("the loosened class is warning-colored",
      ".policy-btn-scoped, .policy-btn-loosened { background: var(--warning)" in UI)
check("the policy chip applies the class independently of grants",
      "if (policyIsLoosened(pol)) polBtn.classList.add('policy-btn-loosened');" in UI
      and "else polBtn.classList.remove('policy-btn-loosened');" in UI)

match = re.search(r"function policyIsLoosened\(pol\) \{.*?\n  \}\n", UI, re.S)
check("policyIsLoosened is defined", match is not None)
node = shutil.which("node")
check("node is available to execute the predicate", node is not None)
if match and node:
    js = match.group(0) + """
const cases = {
  permissive: {preset: 'permissive', enforce: true},
  safety: {preset: 'safety', enforce: true},
  auditOnly: {preset: 'audit-only', enforce: false},
  safetyAudit: {preset: 'safety', enforce: false},
  strict: {preset: 'strict', enforce: true},
  missing: null,
};
console.log(JSON.stringify(Object.fromEntries(
  Object.entries(cases).map(([name, pol]) => [name, policyIsLoosened(pol)]))));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    check("predicate executes", result.returncode == 0, result.stderr.strip()[:300])
    if result.returncode == 0:
        got = json.loads(result.stdout)
        check("permissive warns", got["permissive"] is True)
        check("audit-only warns", got["auditOnly"] is True)
        check("non-enforcing safety warns", got["safetyAudit"] is True)
        check("enforcing safety stays calm", got["safety"] is False)
        check("enforcing strict stays calm", got["strict"] is False)
        check("missing policy is not a healthy claim", got["missing"] is False)

if FAILURES:
    raise SystemExit("dashboard policy posture contract failed: " + ", ".join(FAILURES))
print("dashboard policy posture contract: PASS")
