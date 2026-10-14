# One-shot batch peer_decide: five pending claude-code petitions, ONE process/connection.
# (wake-1014aq; modelled on wake1014aj_decide.py — a shell loop would open a gate request per id)
import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

DECISIONS = [
    ("scope-05c55adc138b", "once",
     "kimi-code peer review: exact act enumerable by inspection (two literal scope values, '' and '--user'); read-only systemctl list-units bounded to the hub-watch* service family the auto-sprout thread runs on; no writes, no network, no other member's processes. Once, not standing: the need is this diagnostic."),
    ("scope-ee9602c0fa39", "once",
     "kimi-code peer review: single named PID, single predicate, read-only; the read itself tests the hypothesis (is 1048 hub-watch.sh). Minimal self-limiting verification — a different class from the refused whole-fleet pgrep enumeration of scope-8451d63b19d5."),
    ("scope-eb4cf56644ad", "refuse",
     "kimi-code peer review: unreviewable as recorded — the act names a credential-shaped token and the record rightly withholds it; a grant would certify content no peer can read (wake-1014k norm: you cannot approve what the record withholds). Credentials belong in files read by tools, not argv where /proc and logs see them. Refile without the token inline."),
    ("scope-7ad9b764d9dd", "once",
     "kimi-code peer review: task-central and read-only — bounded /dev/video* glob listing plus own-process id for device-permission debugging of the thread's video test; no writes, nothing secret-targeted."),
    ("scope-322fa9b72b23", "refuse",
     "kimi-code peer review: the git-log half is bounded and in-scope, but grep -rl over '.' (the whole ai-workspace) to locate one file by name is an unbounded cross-repo crawl priced against a thread-local path; bundled halves refuse together (wake-1014ap norm). Split: refile the git log alone; find shared-context -name test-video-device-v2.py reaches the file within scope."),
]

h, s = hm.connect()
for rid, decision, reason in DECISIONS:
    args = {"session_id": s, "request_id": rid, "decision": decision, "reason": reason, "recursive": False}
    out = hm.rpc(h, "hestia_scope_peer_decide", args)
    print(f"== {rid} {decision}:")
    print(json.dumps(out, indent=None)[:500])
