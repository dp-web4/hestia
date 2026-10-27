#!/usr/bin/env python3
"""Wake-1027n: verify claude-code's refusal basis -- does cbp-being hold a live grant
covering /home/dp/ai-workspace/governance/hestia/core/src/server/state_lock.rs?"""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
if isinstance(out, dict) and "_hestia_error" in out:
    print(json.dumps(out, indent=1)[:1500])
    raise SystemExit
grants = out.get("grants", out)
print(json.dumps(grants, indent=1)[:5000])
