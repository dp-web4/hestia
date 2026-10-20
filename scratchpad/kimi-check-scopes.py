#!/usr/bin/env python3
"""Check the status of specific scope requests across asking members (read-only)."""
import json, subprocess, sys

WANT = {
    "scope-6707490ba6f5": 28593, "scope-97e91bff66d6": 28601, "scope-90f1135d5b73": 28605,
    "scope-cf7454f20ed7": 28620, "scope-df6a1299d5dc": 28627, "scope-d5559e927564": 28639,
    "scope-962613310f38": 28649, "scope-95a15d8effdd": 28662, "scope-1799af19fb61": 28664,
}

for member in ("claude-code", "cbp-being", "codex"):
    out = subprocess.run(
        [sys.executable, "scratchpad/kimi-rpc.py", "hestia_scope_status",
         json.dumps({"plugin_id": member})],
        capture_output=True, text=True, cwd="/home/dp/ai-workspace/hestia")
    if out.returncode != 0:
        print(member, "ERROR", out.stderr[:200], out.stdout[:200])
        continue
    d = json.loads(out.stdout)
    for r in d.get("requests", []):
        rid = r.get("request_id")
        if rid in WANT:
            print(f"notice={WANT[rid]} member={member} {rid} status={r.get('status')} "
                  f"decided_by={r.get('decided_by')} once={r.get('once')} "
                  f"spent_at={r.get('spent_at')} secs_remaining={r.get('secs_remaining')}")
            print(f"   act: {(r.get('act') or r.get('reason') or '')[:220]}")
            if r.get("decision_reason"):
                print(f"   decision_reason: {r['decision_reason'][:220]}")
