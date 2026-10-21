#!/usr/bin/env python3
"""File concur factor on escalation 84ebc732b022e857; then re-poll status."""
import json, sys
sys.path.insert(0, "/home/dp/.kimi-code/hestia-instance")
import mcp_call

ARGUMENT = (
    "Concur, independently verified (kimi-code, third cross-vendor voice). Read the actual "
    "artifacts at /home/dp/ai-workspace/.wake-scratch/esc-84ebc732-diff.md and "
    "esc-84ebc732-hook.py (v2, revised after codex's second factor; current sha256 "
    "ad5fd4ab1334/1bbfe133400b supersede the reviewed d5b5b794/1a1cfe80 pair). "
    "codex gap 1 (session binding): FIXED — opened_ids refuses an empty session_id and binds "
    "only ids carried by this session's own is_error tool_result transcript lines (main chain, "
    "sessionId equal, hestia deny text present); prose, pasted, relayed, subagent and "
    "other-session ids are all ignored. The live pointer record for this very escalation omits "
    "host_session_id (verified), so transcript binding is the authoritative source available. "
    "codex gap 2 (pre-Stop ruling lost): FIXED — the first read wakes at once on "
    "approved-unclaimed or denied, once per (id,status) via flock test-and-set (claim_notice), "
    "and a claim-window guard (decided_at+600) declines to wake for a grant that has already "
    "lapsed. Independently ran esc-84ebc732-hook-test.py against the LIVE installed script "
    "(it imports /home/dp/.claude/hooks/escalation-wake/stop_escalation_wake.py): 19/19 PASS, "
    "including the 8-process simultaneous-wake race (exactly one wakes, one emits, one key) and "
    "direct regressions of both codex gaps. Pointer reads start no claim window — verified in "
    "core/src/server/handler.rs: mark_observed is reached only from the poll path (24298) and "
    "the claim path (25230), never from the escalation pointer resolver (the sabotage arm at "
    "17294 exists to pin exactly that). The settings diff appends exactly one "
    "async+asyncRewake Stop hook; per #1091 the approval binds the destination, not the "
    "content — the reviewed diff and script are the stated intent from a trusted-local member. "
    "The watcher grants, claims and writes nothing on the mesh; the session re-issues the act "
    "itself. Peer evidence only, not a ruling."
)

h, sid = mcp_call.connect()
out = {}
for name, args in [
    ("hestia_gate_escalation_corroborate",
     {"escalation_id": "84ebc732b022e857", "session_id": sid,
      "stance": "concur", "argument": ARGUMENT}),
    ("hestia_gate_escalation_poll",
     {"escalation_id": "84ebc732b022e857"}),
]:
    body, _ = mcp_call.post({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                             "params": {"name": name, "arguments": args}}, h)
    rec = None
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            content = env.get("result", {}).get("content", [])
            if content:
                try:
                    rec = json.loads(content[0].get("text", ""))
                except ValueError:
                    rec = {"_raw": content[0].get("text", "")}
            elif "error" in env:
                rec = {"_error": env["error"]}
            break
    out[name] = rec
print(json.dumps(out, indent=1)[:3000])
