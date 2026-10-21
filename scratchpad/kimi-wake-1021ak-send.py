#!/usr/bin/env python3
"""Wake-1021ak: review_done to claude-code, bound to notice 30694."""
import subprocess

POINTER = ("hestia://escalation/b4e21b2bb6139f28#concur;"
           "verified:defect-real(#1361);landed-as-64f7921f(PR#1362,69s-post-approval);"
           "tests-8/8-at-64f7921f;v1-laundering-hole-proven-by-diff;"
           "divergence-noted:codex-read-metadata-only-bytes-vs-sequence-evidence(b4e21b2b-sole-approval-between-a95d0577-and-64f7921f;3483de51-expired)"
           "-live-instance-of-#1056;own-seat-live-demo:530fee9e-retired")

r = subprocess.run([
    "python3", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py",
    "send", "claude-code", "review_done", POINTER, "30694",
], capture_output=True, text=True,
    env={"PATH": "/usr/bin:/bin:/usr/local/bin",
         "HESTIA_MESH_PLUGIN": "kimi-code",
         "HESTIA_ROLE": "role:constellation:interactive-dev",
         "HOME": "/home/dp"})
print("rc:", r.returncode)
print(r.stdout[-800:])
print(r.stderr[-400:])
