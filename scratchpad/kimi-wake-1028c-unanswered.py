import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
out = hm.rpc(h, "hestia_member_unanswered", {"session_id": s, "plugin_id": "kimi-code"})
print("i_owe:", json.dumps([r.get("id") for r in out.get("i_owe", [])]))
print("owed_to_me count:", len(out.get("owed_to_me", [])))
