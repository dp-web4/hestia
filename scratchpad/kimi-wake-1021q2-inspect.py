#!/usr/bin/env python3
"""Wake-1021q: inspect cbp-being plugin meta + pending scope request context.

Read-only. Prints plugin-level fields of hestia_scope_status for cbp-being and
kimi-code (for MRH comparison), plus the target petition record.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)


def main():
    h, s = hm.connect()
    for plugin in ("cbp-being", "kimi-code"):
        out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": plugin})
        meta = {k: v for k, v in out.items() if k != "requests"}
        print("== plugin:", plugin)
        print(json.dumps(meta, indent=1)[:2000])
        reqs = out.get("requests", [])
        print("requests:", len(reqs))
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
    for r in out.get("requests", []):
        if r.get("request_id") == "scope-8ca4d388d577":
            print("== target petition ==")
            print(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
