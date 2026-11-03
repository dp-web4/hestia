import importlib.util
import json

spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, session_id = hm.connect()
out = hm.rpc(h, "hestia_member_unanswered", {"session_id": session_id, "plugin_id": "kimi-code"})
unanswered = out.get("unanswered", out)
print(json.dumps(unanswered.get("i_owe", []), indent=2))
