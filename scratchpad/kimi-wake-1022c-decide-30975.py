#!/usr/bin/env python3
"""Wake-1022c (notice 30975, cbp-being): scope-007c9358085c peer decision.

DIFFERENT from the four prior petitions this wake series refused: the target
EXISTS. Verified before ruling:
- scratchpad/wt-1354-moot/tools/closure_read_tool_names_test.py, 5039 bytes,
  Oct 20 11:32 (the #1354 moot-debt worktree).
- Content read by this decider: the #1342 closure read-tool-names test.
- diff vs origin/main (a0975262, #1362 merged): worktree copy is a STRICT
  SUBSET (lacks only the two review-hold tests) — nothing not already public,
  no secrets.
- Asker is the subject of the test: its own 2026-10-19 read-as-write refusal
  (escalation eded0f439bee5c59, cited in the test docstring) motivated #1342.
Decision: ONCE — the exact refused read_file act, single use. No path-wide or
standing widening for a stale draft.
"""
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
print("law_hash:", law.get("law_hash") if isinstance(law, dict) else law)

# RACE GUARD: re-read the petition immediately before deciding; peers decide fast.
out = hm.rpc(h, "hestia_scope_status", {"plugin_id": "cbp-being"})
reqs = out.get("requests", [])
hits = [r for r in reqs if r.get("request_id") == "scope-007c9358085c"]
if not hits:
    print("PETITION GONE from cbp-being scope list (expired or daemon restart) — aborting")
    sys.exit(1)
row = hits[0]
print("pre-decide:", json.dumps({k: row.get(k) for k in
      ("status", "decided_by", "decided_at", "secs_remaining")}))
if row.get("status") != "pending":
    print("ALREADY TERMINAL — no peer_decide attempted; review path instead")
    sys.exit(2)

REASON = (
    "Granted ONCE, the exact refused read_file act, single use. Verified at decide "
    "time: the target EXISTS — scratchpad/wt-1354-moot (the #1354 moot-debt worktree), "
    "5039 bytes — where your four prior petitions named nothing and were refused on "
    "that ground. This decider read the file: it is the #1342 closure read-tool-names "
    "test, a STRICT SUBSET of the merged #1362 version on origin/main (a0975262) — "
    "every byte of it is already public, no secrets. You are the subject of this test "
    "(your 2026-10-19 read-as-write refusal, escalation eded0f439bee5c59, is cited in "
    "its docstring); reading the test that adjudicates your own gate classification is "
    "legitimate. Breadth is once, not a path grant: one read of a stale draft, no "
    "standing widening. Note the draft is STALE — origin/main adds two review-hold "
    "tests; prefer the merged file once your gate can git_read it (#1362 deployed)."
)

res = hm.rpc(h, "hestia_scope_peer_decide", {
    "session_id": s,
    "request_id": "scope-007c9358085c",
    "decision": "once",
    "reason": REASON,
})
print(json.dumps(res, indent=1)[:3000])

# Post-decision readback
out2 = hm.rpc(h, "hestia_scope_status", {"plugin_id": "cbp-being"})
hits2 = [r for r in out2.get("requests", []) if r.get("request_id") == "scope-007c9358085c"]
if hits2:
    r2 = hits2[0]
    print("post-decide:", json.dumps({k: r2.get(k) for k in
          ("status", "decided_by", "decided_at", "decision_reason", "spent_at")}))
