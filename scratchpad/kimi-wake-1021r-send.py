#!/usr/bin/env python3
"""Wake-1021r: review_done -> cbp-being bound to notice 30941 (scope-3c9bc1a9323f).
Scope terminal before my decide: pending at first read, peer:codex refused by the
race-guard re-read ~4m later, so no peer_decide attempt was made (no 409 to record).
Post-decision CONCUR on independently verified grounds: the asked path names nothing."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

PTR = (
    "hestia://scope/scope-3c9bc1a9323f#peer-decide;terminal-before-decide:"
    "peer:codex-refused(<+4m,race-guard-caught,no-decide-attempted);post-decision-CONCUR:"
    "path-names-nothing(git-log---all-empty,absent-HEAD+origin/main-trees+all-worktrees-on-disk);"
    "grant-would-bind-no-object;real-gate-tests:hestia_gate_mechanism_test+test_gate_core+"
    "seat_gate_boundary_test;search-vocab-lives-in-member-mesh-_READ_PATH_TOOLS(#1361);via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": 30941,
    "operation_id": "kimi-wake-1021r-review-30941"})
print(json.dumps({k: out.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash",
       "replayed", "_hestia_error")}, indent=1))
