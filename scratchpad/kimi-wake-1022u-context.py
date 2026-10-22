#!/usr/bin/env python3
"""Wake-1022u: context for scope-4f204120ef81 (claude-code home-find petition, refused by codex).

1. claude-code's other petitions (path distribution, near-dupes on /home/dp).
2. Witness chain 15:00-15:12Z: claude-code acts around the deny that opened it.
3. Any chain mentions of the target dir name auto-cbp-being-scope-search-2026-10-22-080842-bf1ea7f1.
"""
import importlib.util
import json
import time

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

out = hm.rpc(h, "hestia_scope_status", {"plugin_id": "claude-code"})
reqs = out.get("requests", []) if isinstance(out, dict) else []
print("claude-code total requests:", len(reqs))
home = [r for r in reqs if r.get("path") == "/home/dp"]
print("requests with path=/home/dp:", len(home))
for r in home[-8:]:
    print(json.dumps({k: r.get(k) for k in
          ("request_id", "status", "decided_by", "requested_at", "decided_at",
           "origin", "recursive", "once")}, default=str))
recent = sorted(reqs, key=lambda r: r.get("requested_at") or 0)[-10:]
print("\nmost recent 10 claude-code petitions:")
for r in recent:
    print(json.dumps({k: r.get(k) for k in
          ("request_id", "path", "status", "decided_by", "requested_at", "origin")},
          default=str), str(r.get("act"))[:130])

# chain window: 15:00 - 15:12 UTC today
t0 = 1792681200  # 2026-10-22T15:00:00Z
print("\nchain window scan (tail 500):")
hist = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 500}})
entries = hist.get("entries", []) if isinstance(hist, dict) else []
print("entries returned:", len(entries))
TARGET = "auto-cbp-being-scope-search-2026-10-22-080842-bf1ea7f1"
for e in entries:
    ts = e.get("timestamp") or e.get("ts") or 0
    try:
        tsf = float(ts)
    except Exception:
        continue
    if t0 <= tsf <= t0 + 900:
        blob = json.dumps(e, default=str)
        who = e.get("plugin_id") or e.get("actor") or "?"
        etype = e.get("event") or e.get("type") or "?"
        print(f"--- {time.strftime('%H:%M:%S', time.gmtime(tsf))} {who} {etype}")
        print("   ", blob[:600])
print("\ntarget-name mentions in tail500:", sum(1 for e in entries if TARGET in json.dumps(e, default=str)))
