#!/usr/bin/env python3
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()
out = hm.rpc(h, "hestia_member_unanswered", {"session_id": s})
print("i_owe:", json.dumps(out.get("i_owe"))[:400])
print("owed_to_me count:", len(out.get("owed_to_me", [])))
print("i_owe_moot:", json.dumps(out.get("i_owe_moot"))[:200])
