#!/usr/bin/env python3
"""Wake-1023 (notice-27Fycf) correction: review_dones 31650/31651/31652 misreported a grant;
all three petitions in fact raced terminal (refused-as-moot by peer:codex 10:12:46Z). Correct the record."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ITEMS = [
    ("scope-7673ee17b449", 31628, 31650),
    ("scope-4f931d41ff55", 31630, 31651),
    ("scope-bfcc926d88bb", 31632, 31652),
]

h, s = hm.connect()
for rid, notice_id, bad_id in ITEMS:
    ptr = (f"hestia://scope/{rid}#peer-decide;raced-terminal:refused-as-moot-by-peer:codex-101246Z"
           f"(originating-session-ended,cc-notices-31640-42);kimi-decide-409-pairing-holds;"
           f"CORRECTS-{bad_id}-no-grant-landed;kimi-corroborates-mootness;"
           f"merits-were-grantable(read-only,bounded,WSL-crash-diagnostic);via=kimi-code")
    assert len(ptr) <= 512, len(ptr)
    out = hm.rpc(h, "hestia_member_notify", {
        "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
        "pointer_uri": ptr, "in_reply_to": notice_id,
        "operation_id": f"kimi-27Fycf-correct-{notice_id}"})
    print(f"== correction re {notice_id}:")
    print(json.dumps({k: out.get(k) for k in
          ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash",
           "replayed", "_hestia_error")}, indent=1))
