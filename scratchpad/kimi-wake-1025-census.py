#!/usr/bin/env python3
"""Wake-1025 census: classify every unanswered review_request in the primer JSON.

For each i_owe entry: resolve pointer -> scope status or escalation evidence,
print one compact line: notice_id | kind | target | state | detail
Read-only.
"""
import sys, json, importlib.util

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

PRIMER = "/home/dp/.kimi-code/hestia-mesh-primers/notice-82tPAc.json"
data = json.load(open(PRIMER))
owe = data["unanswered"]["i_owe"]
print(f"i_owe rows: {len(owe)}", file=sys.stderr)

h, s = hm.connect()

for n in owe:
    nid = n["id"]; ptr = n["pointer_uri"]; frm = n["from_plugin"]
    if ptr.startswith("hestia://scope/"):
        rid = ptr.split("/")[3].split("#")[0]
        out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": rid, "plugin_id": frm})
        try:
            if out.get("error") or out.get("_hestia_error"):
                state = "ERR:" + json.dumps(out)[:160]; detail = ""
            else:
                r = out.get("result", out)
                reqs = r.get("requests", []) if isinstance(r, dict) else []
                match = [q for q in reqs if q.get("request_id") == rid]
                if match:
                    q = match[0]
                    state = q.get("status", "?")
                    detail = (f"by={q.get('decided_by')} reason={str(q.get('decision_reason'))[:80]} "
                              f"path={q.get('path')} modes={q.get('modes')} why={str(q.get('reason'))[:140]}")
                else:
                    state = "NOT-IN-MAP"; detail = f"{len(reqs)} requests visible"
        except Exception as e:
            state = "EXC:" + str(e)[:120]; detail = ""
        print(f"{nid} scope {rid} from={frm} -> {state}")
        if detail:
            print("   " + detail.replace("\n", " ")[:380])
    elif ptr.startswith("hestia://escalation/"):
        eid = ptr.split("/")[3].split("#")[0]
        out = hm.rpc(h, "hestia_escalation_evidence", {"session_id": s, "escalation_id": eid})
        if out.get("error") or out.get("_hestia_error"):
            print(f"{nid} esc {eid} from={frm} -> EVIDENCE_UNKNOWN " + json.dumps(out)[:200])
        else:
            r = out.get("result", out)
            txt = r.get("content", [{}])[0].get("text", "") if isinstance(r, dict) else ""
            try:
                body = json.loads(txt)
            except Exception:
                body = r
            print(f"{nid} esc {eid} from={frm} -> " + json.dumps(body)[:400])
    else:
        print(f"{nid} OTHER {ptr} from={frm}")
