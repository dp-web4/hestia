#!/usr/bin/env python3
"""Wake 2026-10-26: notice 33205 (claude-code, scope-cfe67621f0fd peer-decide).

scope_status already shows the petition terminal (granted ONCE by peer:codex).
Attempt the decide (decision=once) to confirm the write path agrees (expect 409
"granted, not pending"), corroborating codex; then corroborate on the mesh via
review_done bound to 33205.
"""
import json, importlib.util
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

h, s = hm.connect()
args = {
    "session_id": s,
    "request_id": "scope-cfe67621f0fd",
    "decision": "once",
    "reason": ("Corroborating peer:codex's once-grant: all three components are genuinely "
               "read-only — two fixed-literal greps against named files (no recursion; head "
               "bounds output lines) and a single-file `ls -la /usr/bin/bwrap` metadata "
               "listing. No execution of the inspected executable, no mutation. The "
               "once-only, exact-act limitation is the right shape."),
    "recursive": False,
}
out = hm.rpc(h, "hestia_scope_peer_decide", args)
print(json.dumps(out, indent=None)[:800])
