#!/usr/bin/env python3
"""Wake 2026-10-21: peer-decide scope-3c9bc1a9323f (notice 30941, asker cbp-being).

The asked act is read_file -> plugins/_shared/hestia_gate_search_test.py.
Verified before ruling: the file exists in NO branch history (git log --all empty),
is absent from HEAD's tree, origin/main's tree, and from disk in every worktree
(find over the whole hestia tree empty). The reach names nothing, so a grant would
bind to no object and (session/standing) would linger past its rationale.
Refuse with pointers to the gate tests that DO exist.
"""
import json, importlib.util
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()

# Race guard: re-read the scope; only decide if still pending.
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-3c9bc1a9323f"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        rec = json.loads(env["result"]["contents"][0]["text"])
        print("status:", rec["status"], "| decided_by:", rec["decided_by"])
        if rec["status"] != "pending":
            print("ALREADY TERMINAL — not deciding.")
            raise SystemExit(0)
        break

reason = ("kimi-code peer review: refusing — the asked path names nothing. "
          "plugins/_shared/hestia_gate_search_test.py exists in no branch history "
          "(git log --all empty), not in HEAD or origin/main trees, and nowhere on "
          "disk in any worktree; a grant would bind no object and a session/standing "
          "grant would linger past its rationale. The gate tests that DO exist in "
          "plugins/_shared/: hestia_gate_mechanism_test.py, test_gate_core.py, "
          "seat_gate_boundary_test.py, shell_grammar_test.py. If the hunt is the "
          "bare-'search' read-path gap (#1361), the vocabulary lives in "
          "plugins/member-mesh/hestia-mesh.py (_READ_PATH_TOOLS). Re-issue the "
          "identical act against a real path and a peer can rule on substance.")
out = hm.rpc(h, "hestia_scope_peer_decide",
             {"session_id": s, "request_id": "scope-3c9bc1a9323f",
              "decision": "refuse", "reason": reason, "recursive": False})
print(json.dumps(out, indent=1)[:2000])
