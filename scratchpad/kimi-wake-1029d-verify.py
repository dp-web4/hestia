#!/usr/bin/env python3
"""wake-1029d: post-send verification -- member_unanswered should show i_owe empty,
and the 3 send responses are re-derived from the witness chain tail."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                   "params": {"name": "hestia_member_unanswered", "arguments": {}}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        res = env.get("result", env)
        txt = json.dumps(res)
        # content blocks or direct json
        try:
            content = res["content"][0]["text"]
            data = json.loads(content)
        except Exception:
            data = res
        i_owe = data.get("i_owe", "?")
        owed = data.get("owed_to_me", "?")
        print("i_owe:", len(i_owe) if isinstance(i_owe, list) else i_owe)
        if isinstance(i_owe, list):
            for r in i_owe:
                print("  still owed:", r.get("id"), r.get("kind"), r.get("pointer_uri"))
        print("owed_to_me:", len(owed) if isinstance(owed, list) else owed)
        for k in ("i_owe_moot", "owed_to_me_moot"):
            v = data.get(k)
            if v is not None:
                print(k + ":", len(v) if isinstance(v, list) else v)
        break
