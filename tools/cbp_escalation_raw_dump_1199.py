#!/usr/bin/env python3
"""Dump `gate_escalation_opened` rows WHOLE, and census the `codex-cli` alias grain.

Two questions the join census raised and cannot answer itself:

  1. It reported `answers_deny` present on 0/288 opened rows. That is either a real
     wire gap or my reader keying on the wrong spelling — the same trap chain_walk.py's
     header documents four times over. So: print the raw payload keys of every opened
     row, unnormalised, and let the key census answer it. A reader that never sees the
     key it looked for must show what keys DID arrive before it claims absence.

  2. There is exactly one `identity_alias` on the chain (`codex-cli` -> `codex`). The
     alias-split defect only bites where events actually landed under the alias
     spelling, so census every event type by plugin_id for both spellings. Zero rows
     under `codex-cli` means the split is latent; nonzero means it is live and I can
     price it.
"""
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

key_census = Counter()
samples = []
grain = defaultdict(Counter)   # plugin_id -> eventType -> n
seen = 0

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    seen += 1
    et = e.get("eventType")
    if et == "gate_escalation_opened":
        raw = e.get("eventData") or {}
        key_census.update(raw.keys())
        if len(samples) < 3:
            samples.append((e.get("chainPosition"), raw))
    p = payload(e)
    pid = p.get("plugin_id") or p.get("subject_plugin_id")
    if pid in ("codex", "codex-cli"):
        grain[pid][et] += 1

print(f"entries walked: {seen}\n")
print("-- keys present on gate_escalation_opened payloads (raw, unnormalised) --")
for k, n in key_census.most_common():
    print(f"  {n:5d}  {k}")
print("\n-- three whole opened rows --")
for pos, raw in samples:
    print(f"  @{pos}: {json.dumps(raw, sort_keys=True)[:900]}")

print("\n-- the one alias pair, per event type --")
for pid in ("codex", "codex-cli"):
    tot = sum(grain[pid].values())
    print(f"  {pid!r}: {tot} rows")
    for et, n in grain[pid].most_common():
        print(f"      {n:6d}  {et}")
