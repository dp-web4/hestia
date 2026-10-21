# read-only: summarize several escalations' acts and factors
import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for eid in ["01e7f53b5a60349a", "8590a8f841594f25", "21a556b7c8cc5d11", "4161b0b8e92c5d2a"]:
    out = hm.rpc(h, "hestia_escalation_evidence", {"escalation_id": eid, "session_id": s})
    if not out.get("found"):
        print(f"=== {eid}: NOT FOUND")
        continue
    ev = out["evidence"]
    e = ev["escalation"]
    print(f"=== {e['id']} | tool={e['tool_name']} | status={e['status']} | bar_met={e['bar_met']}")
    print("act:", ev.get("act_text", "")[:250])
    print("detail:", (e.get("stated_detail") or "")[:250])
    print("payload_sha256:", e.get("payload_sha256"))
    for f in e["factors"]:
        verdict = "dissent" if f.get("dissent") else "concur"
        print(f"  -- {f['by']} ({verdict}):", f["argument"][:300].replace("\n", " "))
