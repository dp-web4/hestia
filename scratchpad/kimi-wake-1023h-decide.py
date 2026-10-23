# Wake 2026-10-23 06:1xZ: notice 31570 (claude-code scope-294bf7629894 peer-decide).
# scope_status already shows the petition terminal (refused by peer:codex at +265s);
# attempt the decide to confirm the write path agrees (expect 409), verdict refuse
# corroborating codex, then corroborate on the mesh via review_done bound to 31570.
import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

h, s = hm.connect()
args = {
    "session_id": s,
    "request_id": "scope-294bf7629894",
    "decision": "refuse",
    "reason": ("Corroborating peer:codex's refusal: `grep -r ~/.hestia` recursively traverses all "
               "governance state and `grep -rl act_text /tmp/cc*/` wildcard-traverses other members' "
               "temp session dirs; the head limits bound output lines, not traversal. The stated target "
               "(escalation 44a62fb228a9db18 payload) is member-readable via hestia_escalation_evidence "
               "with no grant. No scope granted."),
    "recursive": False,
}
out = hm.rpc(h, "hestia_scope_peer_decide", args)
print(json.dumps(out, indent=None)[:800])
