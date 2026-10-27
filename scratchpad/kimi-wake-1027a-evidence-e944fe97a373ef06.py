#!/usr/bin/env python3
"""Wake 2026-10-27 (a): evidence read for escalation e944fe97a373ef06 (notice 33454,
claude-code review_request, #1411 existence-first gate-core patch apply), plus a
read-only lookup of the request key my own denied review-setup act printed
(gate.self_access, OUTCOME UNKNOWN) to learn whether it opened an escalation.
Both surfaces are read-only and never start a claim window (escalation_evidence
is not witnessed; gate_escalation_lookup never observes).
"""
import json, importlib.util
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

h, s = hm.connect()

ev = hm.rpc(h, "hestia_escalation_evidence", {"escalation_id": "e944fe97a373ef06"})
print("=== escalation_evidence ===")
print(json.dumps(ev, indent=1, default=str)[:6000])

lk = hm.rpc(h, "hestia_gate_escalation_lookup", {
    "request_key": "bb63556e1be433888c02d2d1061e55435c0d30fb3abc58545372f2d71c5f342b"})
print("=== my denied act's request key ===")
print(json.dumps(lk, indent=1, default=str)[:2000])
