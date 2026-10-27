#!/usr/bin/env python3
"""Wake-1027o: resolve i_owe rows 29764 and 29777 (cbp-being escalation asks) that the
primer's capped render did not show."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for notice_id, uri in [(29764, "hestia://escalation/21a556b7c8cc5d11"),
                       (29777, "hestia://escalation/01e7f53b5a60349a")]:
    print(f"===== notice {notice_id} -> {uri}")
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            r = env.get("result", env)
            txt = r["contents"][0]["text"] if "contents" in r else json.dumps(r)
            d = json.loads(txt) if isinstance(txt, str) else txt
            keep = {k: d.get(k) for k in
                    ("status", "stated_reason", "opened_at", "expires_at", "decided_by",
                     "decided_at", "factors_present", "source", "note")}
            se = d.get("settled_entry") or {}
            keep["settled_event"] = se.get("eventType")
            keep["settled_ts"] = se.get("timestamp")
            keep["witness"] = (se.get("hash") or "")[:16]
            ed = se.get("eventData") or {}
            keep["factors_by"] = ed.get("factors_by")
            keep["concur"] = ed.get("factors_concurring")
            keep["dissent"] = ed.get("factors_dissenting")
            print(json.dumps(keep, indent=1))
            break
    print()
