import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for eid in ["4e166b669ca90901", "5c4bb7c8125eff99"]:
    body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read",
                       "params": {"uri": "hestia://escalation/" + eid}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print("############ " + eid + " ############")
            print(json.dumps(json.loads(env["result"]["contents"][0]["text"]), indent=1))
