import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
print("session:", s, "plugin:", hm.PLUGIN)

DECISIONS = [
 ("scope-f9f92a1a46c3", "refuse",
  "Refused as filed: the gate petitioned rwed over /var/log/outreach-cbp.log for a read-only "
  "tail/grep, with no task purpose stated. The diagnostic question (did outreach stop on credit "
  "exhaustion) is legitimate; refile once, read-only, this exact path, purpose in words, and it "
  "can be granted."),
 ("scope-a5b5d0a2e73e", "refuse",
  "Refused as filed: the gate mapped this act to rwed over /home/dp (the whole home directory) "
  "for a git checkout/stash-drop plus a python run inside one repository, with no stated purpose. "
  "Breadth and modes far exceed the act, and stash drop is destructive. Refile bounded to the "
  "private-context path with the purpose in words."),
]
for rid, dec, reason in DECISIONS:
    r = hm.rpc(h, "hestia_scope_peer_decide",
               {"session_id": s, "request_id": rid, "decision": dec, "reason": reason})
    print(rid, "->", json.dumps(r)[:400])
