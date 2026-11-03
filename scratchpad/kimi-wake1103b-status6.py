import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

ROWS = [
 ("36109", "scope-f9f92a1a46c3"), ("36112", "scope-a5b5d0a2e73e"),
 ("36116", "scope-ae4165e166b5"), ("36118", "scope-8934275e4e6f"),
 ("36139", "scope-7640641da57b"), ("36140", "scope-e33f95a33c93"),
]

def read(uri):
    body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read", "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            txt = env["result"]["contents"][0]["text"]
            return json.loads(txt)
    return {"_error": body[:200]}

for nid, rid in ROWS:
    r = read("hestia://scope/" + rid)
    if "_hestia_error" in r:
        print(nid, rid, "ERR", r["_hestia_error"].get("code"), str(r["_hestia_error"].get("data"))[:120])
        continue
    print("====", nid, rid)
    print(json.dumps(r)[:1400])
    print()
