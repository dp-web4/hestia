#!/usr/bin/env python3
"""Wake-1021q: full grant lists for cbp-being (standing + live), no truncation."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)


def main():
    h, s = hm.connect()
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
    print("== standing_grants ==")
    print(json.dumps(out.get("standing_grants", []), indent=1))
    print("== live_grants ==")
    print(json.dumps(out.get("live_grants", []), indent=1))
    print("== all requests (id, act, status, decided_by) ==")
    for r in out.get("requests", []):
        print(json.dumps({k: r.get(k) for k in
                          ("request_id", "act", "status", "decided_by", "requested_at")}))


if __name__ == "__main__":
    main()
