#!/usr/bin/env python3
"""Escalations render once, with current disposition and the terminal ruling hash (#869)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

ui = Path("core/src/server/dashboard/index.html").read_text(encoding="utf-8")
failures = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def function_source(name):
    match = re.search(rf"function {name}\([^)]*\) \{{.*?\n  \}}\n", ui, re.S)
    check(f"{name} is defined", match is not None)
    return match.group(0) if match else ""


check("the feed projects through the live pending set", "projectEscalations(source, pendingIds)" in ui)
check("the renderer consumes the escalation view", "if (escView)" in ui)
check("the event label says escalation", "escView ? 'escalation' : e.event_type" in ui)

node = shutil.which("node")
check("node is available to execute the projection", node is not None)
if node:
    js = function_source("escalationView") + function_source("projectEscalations") + r"""
const opened = {
  chain_position: 1, event_type: 'gate_escalation_opened', escalation_id: 'abcdefghijkl',
  plugin_id: 'kimi-code', marker: 'policy.json', hash: 'open',
};
const decided = {
  chain_position: 3, event_type: 'gate_escalation_decided', escalation_id: 'abcdefghijkl',
  plugin_id: 'kimi-code', decided_by: 'dp', decided_via: 'operator_session',
  bar: 'single_approver', bar_met: true, granted: true, hash: 'ruling',
};
const claimed = {
  chain_position: 4, event_type: 'gate_escalation_claimed', escalation_id: 'abcdefghijkl',
  plugin_id: 'kimi-code', hash: 'claim',
};
const approved = projectEscalations([claimed, decided, opened], new Set());
const pending = projectEscalations([opened], new Set(['abcdefghijkl']));
const offRecord = projectEscalations([opened], new Set());
const deniedOpen = {
  chain_position: 10, event_type: 'gate_escalation_opened', escalation_id: 'denied-abcdefghij',
  plugin_id: 'codex', marker: 'law.json', hash: 'denied-open',
};
const deniedDecision = {
  chain_position: 11, event_type: 'gate_escalation_decided', escalation_id: 'denied-abcdefghij',
  decided_by: 'claude-code', decided_via: 'peer_member', bar: 'sovereign_plus_peer',
  bar_met: false, granted: false, hash: 'denied-ruling',
};
const denied = projectEscalations([deniedDecision, deniedOpen], new Set());
const withdrawn = projectEscalations([{...deniedDecision, decided_via: 'self_withdrawn'}], new Set());
const expired = projectEscalations([{...deniedDecision, event_type: 'gate_escalation_expired'}], new Set());
const claimOnly = projectEscalations([claimed], new Set());
const ordinary = {chain_position: 30, event_type: 'outcome', plugin_id: 'kimi-code', hash: 'ordinary'};
const untouched = projectEscalations([ordinary], new Set());
console.log(JSON.stringify({approved, pending, offRecord, denied, withdrawn, expired, claimOnly, untouched}));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    check("projection executes", result.returncode == 0, result.stderr.strip()[:500])
    if result.returncode == 0:
        got = json.loads(result.stdout)
        approved = got["approved"]
        check("open, ruling, and claim collapse to one row", len(approved) == 1)
        check("the representative is the ruling, not the claim", approved[0]["hash"] == "ruling")
        check("the asker comes from the open row", approved[0]["plugin_id"] == "kimi-code")
        check("approval names ruler, channel, and met bar",
              approved[0]["escalation_view"]["status"] == "approved"
              and "approved by dp (operator_session, bar single_approver met)"
              in approved[0]["escalation_view"]["detail"])
        check("the marker survives on the terminal row",
              approved[0]["escalation_view"]["detail"].startswith("abcdefgh policy.json ->"))
        check("a live pending open renders pending",
              got["pending"][0]["escalation_view"]["status"] == "pending")
        check("an unconfirmed open is not mislabeled pending",
              got["offRecord"][0]["escalation_view"]["detail"].endswith("no longer on record"))
        denied = got["denied"][0]["escalation_view"]
        check("denial names ruler and unmet bar", denied["status"] == "denied"
              and "denied by claude-code (peer_member, bar sovereign_plus_peer not met)" in denied["detail"])
        check("self-withdrawal is not mislabeled as a merits denial",
              got["withdrawn"][0]["escalation_view"]["status"] == "withdrawn")
        check("expiry is explicit and unruled",
              got["expired"][0]["escalation_view"]["detail"].endswith("expired unruled"))
        check("a claim without its ruling says the ruling is outside the window",
              got["claimOnly"][0]["escalation_view"]["detail"].endswith("claimed (ruling outside this window)"))
        check("non-escalation rows pass through unchanged", got["untouched"] == [{
            "chain_position": 30, "event_type": "outcome", "plugin_id": "kimi-code", "hash": "ordinary",
        }])

if failures:
    raise SystemExit("dashboard escalation feed contract failed: " + ", ".join(failures))
print("dashboard escalation feed contract: PASS")
