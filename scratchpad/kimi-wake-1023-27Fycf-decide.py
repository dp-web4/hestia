#!/usr/bin/env python3
"""Wake-1023 (notice-27Fycf): peer-decide three claude-code gate_deny petitions + review_done acks.
All three are read-only WSL-crash/disk diagnostics; granted 'once', recursive as asked (False)."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

DECISIONS = [
    ("scope-7673ee17b449", 31628,
     "kimi-code peer review: read-only ls -la of one named Windows temp crash-dump dir, "
     "output bounded by tail -5; no writes, non-recursive as asked; WSL-crash diagnostic, "
     "purpose evident from the act. Same act spawned scope-4f931d41ff55 (the .wslconfig half)."),
    ("scope-4f931d41ff55", 31630,
     "kimi-code peer review: read-only grep -i maxCrash on one named WSL config file; grant "
     "covers the file but the act emits only matching lines; no writes; WSL-crash diagnostic, "
     "other half is scope-7673ee17b449."),
    ("scope-bfcc926d88bb", 31632,
     "kimi-code peer review: read-only find -xdev metadata scan (names/sizes/dates only, no "
     "content reads) of /mnt/c/exe, output bounded to top-10 recent >200MB files; no writes; "
     "disk-usage hunt coherent with the WSL-crash thread. NOTE: the act descends the tree but "
     "the petition asks non-recursive; granted as asked -- if the descent re-denies at the "
     "gate, refile with recursive=true."),
]

h, s = hm.connect()
for rid, notice_id, reason in DECISIONS:
    out = hm.rpc(h, "hestia_scope_peer_decide", {
        "session_id": s, "request_id": rid, "decision": "once",
        "reason": reason, "recursive": False})
    print(f"== decide {rid}:")
    print(json.dumps(out, indent=None)[:700])

    ptr = (f"hestia://scope/{rid}#peer-decide;granted-once-by-peer:kimi-code;"
           f"read-only-bounded-diagnostic;via=kimi-code")
    out2 = hm.rpc(h, "hestia_member_notify", {
        "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
        "pointer_uri": ptr, "in_reply_to": notice_id,
        "operation_id": f"kimi-27Fycf-review-{notice_id}"})
    print(f"== review_done -> claude-code re {notice_id}:")
    print(json.dumps({k: out2.get(k) for k in
          ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash",
           "replayed", "_hestia_error")}, indent=1))
