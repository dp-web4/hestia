import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read",
                   "params": {"uri": "hestia://escalation/29f13b3bc3bb8d4c"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        txt = env["result"]["contents"][0]["text"]
        print(json.dumps(json.loads(txt), indent=1))
