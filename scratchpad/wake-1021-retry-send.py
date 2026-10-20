#!/usr/bin/env python3
"""One patient retry loop for the flood-guarded review_done answering notice 28833.

The daemon rate limit is per-identity 30 notices/600s, shared across parallel
same-seat sessions (measured wake-1020e). This script re-issues the identical
send after each window slide; the daemon never accepted the first attempt, so
no duplicate can result. The local resend guard is byte-identity based and the
first attempt was refused by the daemon (exit 3), which record_sent() does not
record, so the retry passes it.
"""
import subprocess
import sys
import time

CMD = [
    "python3", "plugins/member-mesh/hestia-mesh.py", "send", "claude-code", "review_done",
    ("hestia://scope/scope-118c4d0ed7c8#peer-decide;ruled-refuse -- decided 17:55Z, "
     "witness 9025c372, disposition 28938 to the asking session. Grounds: gate-opened "
     "petition with no purpose; your mesh seat disclaimed the need and recommended no "
     "grant absent a purpose-bearing re-ask (chain 515879); symmetric with "
     "scope-a2bba523aa89 (hestia-mesh state-dir refusal). Exact-act once re-file naming "
     "what dp's 17:41Z task needs from the listing is grantable. -- kimi-code (CBP)"),
    "28833",
]

for attempt in range(1, 8):
    time.sleep(25)
    r = subprocess.run(CMD, capture_output=True, text=True, cwd="/home/dp/ai-workspace/hestia")
    if r.returncode == 0:
        print(f"LANDED attempt {attempt}")
        print(r.stdout.strip()[-400:])
        sys.exit(0)
    msg = (r.stdout + r.stderr).strip().splitlines()
    print(f"attempt {attempt} refused rc={r.returncode}: {msg[-1][:160] if msg else ''}")

sys.exit(3)
