import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

ROWS = [
 (35460, "scope", "scope-c2f5e14e92ea"), (35462, "scope", "scope-ca7399e629f3"),
 (35464, "scope", "scope-ae3ffbfb36a6"), (35615, "scope", "scope-2a5241c248d5"),
 (35622, "scope", "scope-c595cb36acc1"), (35624, "scope", "scope-92d27ebbee3f"),
 (35633, "scope", "scope-2f2499417f36"), (35643, "scope", "scope-e46ee4e31f52"),
 (35677, "scope", "scope-288392f2c33a"), (35705, "scope", "scope-7a35d7f7e712"),
 (35707, "scope", "scope-6a259d3ec696"), (35735, "escalation", "4e166b669ca90901"),
 (35806, "scope", "scope-8a03a0bd2bba"), (35830, "scope", "scope-9cce887f2166"),
 (35858, "scope", "scope-b853796a947b"), (35872, "scope", "scope-20d53a4871c1"),
 (35907, "scope", "scope-d23045e51a04"), (35972, "escalation", "5c4bb7c8125eff99"),
 (35984, "scope", "scope-2c10fcdb19cf"), (35997, "scope", "scope-d0b093c2b6eb"),
 (35999, "scope", "scope-d099aa1d1974"), (36016, "scope", "scope-47a7328c42f1"),
 (36081, "scope", "scope-ae0e61985fc0"), (36096, "scope", "scope-9bc145280b50"),
]

def read(uri):
    body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read", "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            txt = env["result"]["contents"][0]["text"]
            return json.loads(txt)
    return {"_error": body[:200]}

for nid, kind, rid in ROWS:
    r = read("hestia://" + kind + "/" + rid)
    if "_hestia_error" in r:
        print(nid, rid, "NOT_FOUND", r["_hestia_error"]["data"].get("chainLength"))
        continue
    if kind == "scope":
        print(nid, rid, "status=" + str(r.get("status")), "path=" + str(r.get("path"))[:60],
              "modes=" + str(r.get("modes")), "by=" + str(r.get("granted_by") or r.get("decided_by") or ""),
              "purpose=" + str(r.get("purpose"))[:60])
    else:
        print(nid, rid, "status=" + str(r.get("status")), "tool=" + str(r.get("tool_name")),
              "by=" + str(r.get("decided_by")), "marker=" + str(r.get("marker")),
              "act=" + str(r.get("stated_reason"))[:80])
