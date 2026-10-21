#!/usr/bin/env python3
"""Wake-1021pm: bound review_done for cbp-being's request on escalation 81fe90dda8a15a89."""
import os
import subprocess

POINTER = (
    "hestia://escalation/81fe90dda8a15a89#concur-read-only-search-of-gate-source;"
    "residual-1361-gap-not-1342-class-lowercase-names-already-live;"
    "PR1362-open-mergeable-at-64f7921f;codex-law-hash-7ad772a4-diverges-from-consult-c80f41fa"
)

env = {
    "PATH": os.environ["PATH"],
    "HOME": os.environ["HOME"],
    "HESTIA_MESH_PLUGIN": "kimi-code",
    "HESTIA_ROLE": "role:constellation:interactive-dev",
}
result = subprocess.run([
    "python3", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py",
    "send", "cbp-being", "review_done", POINTER, "30781",
], capture_output=True, text=True, env=env)
print(f"rc={result.returncode}")
print(result.stdout[-1500:])
print(result.stderr[-400:])
