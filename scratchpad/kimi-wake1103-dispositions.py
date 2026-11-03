import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for rid in ["scope-7640641da57b", "scope-e33f95a33c93"]:
    body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read",
                       "params": {"uri": "hestia://scope/" + rid}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            txt = env["result"]["contents"][0]["text"]
            try:
                r = json.loads(txt)
                if "_hestia_error" in r:
                    print(rid, "->", r["_hestia_error"]["code"])
                else:
                    print(rid, "->", json.dumps(r)[:900])
            except ValueError:
                print(rid, "->", txt[:400])
