#!/usr/bin/env python3
"""Wake-1021ai: locate the three petitions claude-code asked this seat to peer-decide
(notices 30644/30646/30649). hestia_scope_status is per-plugin and read-only; loop the
local roster and print the matching request records verbatim."""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

TARGETS = {"scope-8bd24da75b53", "scope-87be6b0ebbc3", "scope-d69ff8af9349"}
ROSTER = ["claude-code", "codex", "cbp-being", "gemini", "sprout-being", "kimi-code"]

h, s = hm.connect()
found = {}
for pid in ROSTER:
    try:
        out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": pid})
    except Exception as e:
        print(f"{pid}: RPC error {e}")
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    for r in reqs:
        if r.get("request_id") in TARGETS:
            found[r["request_id"]] = (pid, r)
missing = TARGETS - set(found)
print(json.dumps({rid: {"petitioner": pid, "record": rec}
                  for rid, (pid, rec) in found.items()}, indent=2, sort_keys=True))
if missing:
    print("NOT FOUND under queried plugin_ids:", sorted(missing))
