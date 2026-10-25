#!/usr/bin/env python3
"""Classify each wake-1025 target from the deep-scan events into a terminal state."""
import json

d = json.load(open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1025-targets.json"))
scopes = d["scopes"]; escs = d["escalations"]; events = d["events"]

TERMINAL_SCOPE = {"scope_granted", "scope_refused", "scope_revoked", "scope_decided"}
ESC_TERM = {"gate_escalation_decided", "gate_escalation_expired", "gate_escalation_withdrawn"}

rows = []
for tid, evs in events.items():
    evs.sort(key=lambda e: e["ts"])
    nid = scopes.get(tid) or escs.get(tid)
    kind = "scope" if tid in scopes else "esc"
    term = [e for e in evs if e["eventType"] in TERMINAL_SCOPE | ESC_TERM]
    factors = [e for e in evs if "factor" in e["eventType"] or e["eventType"] in
               ("gate_escalation_corroborated", "gate_escalation_dissented")]
    first, last = evs[0], evs[-1]
    if term:
        t = term[-1]
        verdict = (t["data"].get("status") or t["data"].get("decision") or
                   t["data"].get("outcome") or t["eventType"])
        rows.append((nid, kind, tid, "TERMINAL", f"{t['eventType']}:{verdict}",
                     t["ts"], len(evs), len(factors),
                     str(first["data"])[:150]))
    else:
        rows.append((nid, kind, tid, "OPEN?", last["eventType"], last["ts"],
                     len(evs), len(factors), str(first["data"])[:150]))

rows.sort(key=lambda r: r[0])
for r in rows:
    print(f"{r[0]} {r[1]:5} {r[2][:24]:26} {r[3]:8} {r[4]:44} {r[5][:19]} ev={r[6]:2} fac={r[7]}")
print()
open_ = [r for r in rows if r[3] != "TERMINAL"]
print(f"terminal: {len(rows)-len(open_)}, maybe-open: {len(open_)}")
for r in open_:
    print("OPEN?", r)
