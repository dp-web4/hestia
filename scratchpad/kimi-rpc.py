#!/usr/bin/env python3
"""Call one read-only hestia tool over the daemon's MCP HTTP surface.

Usage: kimi-rpc.py <tool_name> '<json-args>'
Reuses plugins/member-mesh/hestia-mesh.py's post/rpc/connect so the wire shape
(initialize -> notifications/initialized -> hestia_connect -> tools/call) is
identical to the member-mesh CLI's.
"""
import importlib.util, json, os, sys

spec = importlib.util.spec_from_file_location(
    "hestia_mesh", os.path.join(os.path.dirname(__file__), "..", "plugins", "member-mesh", "hestia-mesh.py"))
mesh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mesh)

def main():
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    h, s = mesh.connect()
    args.setdefault("session_id", s)
    out = mesh.rpc(h, tool, args)
    print(json.dumps(out, indent=1))
    if mesh.failed(out):
        sys.exit(3)

if __name__ == "__main__":
    main()
