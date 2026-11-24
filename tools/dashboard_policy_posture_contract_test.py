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

def policy_editor_behavior(data):
    start = UI.index("  (function wirePolicyEditor() {")
    end = UI.index("\n  })();", start) + len("\n  })();")
    block = UI[start:end]
    js = """
const sent = [], confirms = [], prompts = [];
const card = { handlers: {}, addEventListener(kind, fn) { this.handlers[kind] = fn; } };
const $ = id => id === 'govern-policy' ? card : { textContent: '' };
const selectedOrch = null;
const lastData = DATA;
const confirm = message => { confirms.push(message); return lastData.ack !== false; };
const prompt = message => { prompts.push(message); return lastData.reason || null; };
const polSend = async (...args) => { sent.push(args); };
BLOCK
(async () => {
  await card.handlers.click({ target: { dataset: { preset: lastData.target } } });
  console.log(JSON.stringify({ sent, confirms, prompts }));
})();
""".replace("DATA", json.dumps(data)).replace("BLOCK", block)
    result = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    check("policy editor executes", result.returncode == 0, result.stderr.strip()[:500])
    return json.loads(result.stdout) if result.returncode == 0 else {}


check("the witness indicator is a non-interactive status span",
      '<span id="witness-policy" class="witness-policy" role="status" aria-live="polite"></span>' in UI
      and '<button id="witness-policy"' not in UI
      and 'id="witness-policy" class="witness-policy" role="status" aria-live="polite" onclick' not in UI)
check("the witness indicator is prominent and warning-aware",
      "font-size: 1.1rem" in UI
      and ".witness-policy.policy-btn-scoped, .witness-policy.policy-btn-loosened { color: var(--warning); }" in UI)


def witness_state(data):
    start = UI.index("    const polBtn = (() => {")
    end = UI.index("    const filterLabel =", start)
    block = match.group(0) + UI[start:end]
    js = """
const els = {};
function el(id) {
  if (els[id]) return els[id];
  const classes = new Set();
  return els[id] = {
    textContent: '', title: '',
    classList: {
      add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
    },
    get classes() { return Array.from(classes).sort(); },
  };
}
const $ = el;
const lastData = DATA;
const pol = lastData.policy;
const selectedOrch = lastData.selectedOrch || null;
BLOCK
console.log(JSON.stringify({ text: $('witness-policy').textContent,
  classes: $('witness-policy').classes, title: $('witness-policy').title }));
""".replace("DATA", json.dumps(data)).replace("BLOCK", block)
    result = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    check("witness indicator executes", result.returncode == 0, result.stderr.strip()[:500])
    return json.loads(result.stdout) if result.returncode == 0 else {}


if node:
    loosening = {"policy": {"preset": "strict", "enforce": True}, "target": "permissive"}
    cancelled = policy_editor_behavior(dict(loosening, ack=False))
    check("society loosening acknowledges the transition before sending",
          len(cancelled["confirms"]) == 1 and "strict" in cancelled["confirms"][0]
          and "permissive" in cancelled["confirms"][0] and cancelled["sent"] == [], cancelled)
    refused = policy_editor_behavior(loosening)
    check("cancelling a society loosening sends nothing", refused["sent"] == [], refused)
    accepted = policy_editor_behavior(dict(loosening, reason="incident review"))
    check("a reasoned loosening reaches the daemon with that reason",
          len(accepted["sent"]) == 1
          and accepted["sent"][0][2] == {"preset": "permissive", "reason": "incident review"},
          accepted)
    tightened = policy_editor_behavior({
        "policy": {"preset": "permissive", "enforce": True}, "target": "strict"})
    check("tightening stays one click with no acknowledgement or reason prompt",
          tightened["confirms"] == [] and tightened["prompts"] == []
          and tightened["sent"][0][2] == {"preset": "strict"}, tightened)
    audit = policy_editor_behavior({
        "policy": {"preset": "safety", "enforce": True}, "target": "audit-only",
        "reason": "temporary observation"})
    check("enforcement-off is also a reasoned loosening",
          len(audit["confirms"]) == 1 and audit["sent"][0][2]["reason"] == "temporary observation",
          audit)
    from_audit = policy_editor_behavior({
        "policy": {"preset": "audit-only", "enforce": False}, "target": "permissive",
        "reason": "incident review"})
    check("audit-only to permissive requires the same acknowledgement and reason",
          len(from_audit["confirms"]) == 1
          and from_audit["sent"][0][2] == {"preset": "permissive", "reason": "incident review"},
          from_audit)
    from_audit_refused = policy_editor_behavior({
        "policy": {"preset": "audit-only", "enforce": False}, "target": "permissive"})
    check("audit-only to permissive without a reason sends nothing",
          from_audit_refused["sent"] == [], from_audit_refused)
    cases = [
        ({"policy": {"preset": "permissive", "enforce": True}, "instance_grants": []},
         "policy: permissive", ["policy-btn-loosened"]),
        ({"policy": {"preset": "safety", "enforce": False}, "instance_grants": []},
         "policy: safety (audit)", ["policy-btn-loosened"]),
        ({"policy": {"preset": "safety", "enforce": True},
          "instance_grants": [{"plugin_id": "other", "preset": "permissive"}]},
         "policy: safety · 1 grant", ["policy-btn-scoped"]),
        ({"policy": {"preset": "strict", "enforce": True}, "instance_grants": []},
         "policy: strict", []),
        ({"policy": {"preset": "safety", "enforce": True}, "selectedOrch": "claude-code",
          "instance_grants": [{"plugin_id": "claude-code", "preset": "permissive", "reason": "x"}]},
         "policy: permissive · claude-code", ["policy-btn-scoped"]),
    ]
    for data, text, classes in cases:
        got = witness_state(data)
        check(f"witness indicator renders {text}", got.get("text") == text, got)
        check(f"witness indicator classes for {text}", got.get("classes") == classes, got)

if FAILURES:
    raise SystemExit("dashboard policy posture contract failed: " + ", ".join(FAILURES))
print("dashboard policy posture contract: PASS")
