import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
out = hm.rpc(h, "hestia_member_unanswered", {"session_id": s, "plugin_id": "kimi-code"})
un = out.get("unanswered", out)
owe = un.get("i_owe", [])
owed = un.get("owed_to_me", [])
print("i_owe count:", len(owe))
for r in owe:
    print(" ", r.get("id"), r.get("from_plugin"), r.get("pointer_uri", "")[:90])
print("owed_to_me count:", len(owed))
print("moot i_owe:", len(un.get("i_owe_moot", [])), " moot owed:", len(un.get("owed_to_me_moot", [])))
