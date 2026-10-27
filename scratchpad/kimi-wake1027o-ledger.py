#!/usr/bin/env python3
"""Wake-1027o: post-send ledger check -- i_owe should now be 0 (33793 corroboration
+ 5 resurfaced-row closures all bound this wake)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_unanswered", {"session_id": s, "plugin_id": "kimi-code"})
if isinstance(out, dict) and "_hestia_error" in out:
    print(json.dumps(out, indent=1)[:2000])
    raise SystemExit(1)
i_owe = out.get("i_owe", [])
owed = out.get("owed_to_me", [])
print(f"i_owe: {len(i_owe)}")
for r in i_owe:
    print("  ", r.get("id"), r.get("kind"), r.get("from_plugin"), r.get("pointer_uri", "")[:100])
print(f"owed_to_me: {len(owed)} (others' debt; expected ~51 + this wake's 6 sent replies)")
