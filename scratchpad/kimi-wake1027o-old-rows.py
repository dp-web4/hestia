#!/usr/bin/env python3
"""Wake-1027o: resolve the 5 resurfaced i_owe rows (all cbp-being->kimi-code, 2026-10-21):
29665 scope-b3cf8cdb88f5, 29690 escalation/f87dd9850f246bcc, 29711 scope-44355d934301,
29714 escalation/e6d875839a0a87e2, 29738 scope-537ea765b120.
Terminal state decides the reply text; scope_pointer_not_found reads unknown-not-moot
(memory-only live map), per the 33604/33637 precedent."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    (29665, "hestia://scope/scope-b3cf8cdb88f5"),
    (29690, "hestia://escalation/f87dd9850f246bcc"),
    (29711, "hestia://scope/scope-44355d934301"),
    (29714, "hestia://escalation/e6d875839a0a87e2"),
    (29738, "hestia://scope/scope-537ea765b120"),
]

for notice_id, uri in URIS:
    print(f"===== notice {notice_id} -> {uri}")
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            r = env.get("result", env)
            print(json.dumps(r, indent=1)[:3000])
            break
    print()
