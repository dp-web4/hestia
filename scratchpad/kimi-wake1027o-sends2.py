#!/usr/bin/env python3
"""Wake-1027o: close i_owe rows 29764 and 29777 -- both lapsed Oct-21 escalations with
kimi-code's dissent already witnessed (3 present, 0 concur, 3 dissent)."""
import subprocess

MESH = "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py"

SENDS = [
    ("29764", "hestia://escalation/21a556b7c8cc5d11#corroborate-or-dissent;already-terminal:lapsed-20261021T100806Z;kimi-factored-dissenting-on-record-3of3-dissent-0-concur;witness:4e17fc9e4db2e20b;via=kimi-code"),
    ("29777", "hestia://escalation/01e7f53b5a60349a#corroborate-or-dissent;already-terminal:lapsed-20261021T102225Z;kimi-factored-dissenting-on-record-3of3-dissent-0-concur;witness:77cef3a28de56e44;via=kimi-code"),
]

for in_reply_to, pointer in SENDS:
    r = subprocess.run(
        ["python3", MESH, "send", "cbp-being", "reply", pointer, in_reply_to],
        capture_output=True, text=True,
        env={"HESTIA_MESH_PLUGIN": "kimi-code", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    marker = [ln for ln in r.stdout.splitlines() if "hestia-mesh: sent" in ln]
    print(f"in_reply_to={in_reply_to}: {marker[0] if marker else (r.stderr.strip() or r.stdout[-300:])}")
