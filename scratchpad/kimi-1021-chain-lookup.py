# read-only: resolve a witness-chain hash/prefix via hestia_query_history filter.hash
import json, importlib.util, sys
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for ptr in sys.argv[1:]:
    out = hm.rpc(h, "hestia_query_history", {"filter": {"hash": ptr}, "session_id": s})
    print(f"===== {ptr} =====")
    print(json.dumps(out, indent=1)[:3000])
