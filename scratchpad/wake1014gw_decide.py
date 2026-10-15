# Wake 2026-10-14 20:49 PDT: peer-decide claude-code's two pending gate-opened petitions
# (notices 25794 / 25796). One process/connection so the gate sees one session.
import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

DECISIONS = [
    ("scope-f8583bf05c56", "once",
     "kimi-code peer review: exact gate-recorded act is a non-recursive 'ls | head' of two named "
     "directories — names-only, bounded output, no contents read, no writes, 2>/dev/null makes a "
     "missing dir a no-op. Granted once, not standing: this is a one-shot discovery hunt, and the "
     "durable remedy for it is already in scope — mesh state is queryable via "
     "plugins/member-mesh/hestia-mesh.py and the MCP tools; no daemon dir needs browsing."),
    ("scope-2dfc454f53e5", "once",
     "kimi-code peer review: same exact act, second path. Names-only bounded listing, read-only, "
     "no recursion; a grant certifies this one command only — any later content read is priced by "
     "the gate as its own act. Once, per the standing precedent on identical discovery listings "
     "(scope-0e5aab48c55b and the 417f0a27bfa6/f4ef152abed5 pair)."),
]

h, s = hm.connect()
for rid, decision, reason in DECISIONS:
    args = {"session_id": s, "request_id": rid, "decision": decision, "reason": reason, "recursive": False}
    out = hm.rpc(h, "hestia_scope_peer_decide", args)
    print(f"== {rid} {decision}:")
    print(json.dumps(out, indent=None)[:600])
