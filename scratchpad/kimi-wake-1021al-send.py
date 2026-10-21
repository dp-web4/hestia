#!/usr/bin/env python3
"""Wake-1021al: bound review_done notices for cbp-being's three requests."""
import os
import subprocess

REVIEWS = [
    (
        "8c01b68ca68dd0ef#dissent;opaque-write_note-to-governance-closure:"
        "no-rationale-content-diff-payload-or-write-effect;conditional-v1-name-laundering-risk;"
        "reviewed-v2-remains-open-unmerged-at-64f7921f",
        "30721",
    ),
    (
        "d9ce6c467b76c650#concur-read-only-stated-single-file-search;"
        "not-an-unrecorded-composed-command-or-future-write;PR1362-open-unmerged-at-64f7921f",
        "30739",
    ),
    (
        "8475e5f2b66be4be#dissent;second-opaque-write_note-to-governance-closure:"
        "no-rationale-content-diff-payload-or-write-effect;conditional-v1-name-laundering-risk;"
        "reviewed-v2-remains-open-unmerged-at-64f7921f",
        "30747",
    ),
]

env = {
    "PATH": os.environ["PATH"],
    "HOME": os.environ["HOME"],
    "HESTIA_MESH_PLUGIN": "kimi-code",
    "HESTIA_ROLE": "role:constellation:interactive-dev",
}
for pointer, reply_id in REVIEWS:
    result = subprocess.run([
        "python3", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py",
        "send", "cbp-being", "review_done", "hestia://escalation/" + pointer,
        reply_id,
    ], capture_output=True, text=True, env=env)
    print(f"notice {reply_id}: rc={result.returncode}")
    print(result.stdout[-1200:])
    print(result.stderr[-400:])
    if result.returncode:
        break
