#!/usr/bin/env python3
"""Independent re-measure of re-1190 probe 4 (kimi, not CBP's code).

Reads ~/.hestia/reputation-deltas.jsonl directly: total rows, how many carry a
contributing_factors field, how many non-empty, same for witnesses, plus the
source census. Written from scratch against the raw file so the verification
does not ride CBP's parsing choices.
"""
import json
from collections import Counter

rows = unparsable = field = nonempty_f = nonempty_w = 0
src = Counter()
sample_nonempty = []
for line in open("/home/dp/.hestia/reputation-deltas.jsonl", errors="replace"):
    line = line.strip("\x00 \n")
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        unparsable += 1
        continue
    rows += 1
    s = str(d.get("source") or d.get("reason") or d.get("kind") or "<none>")
    src[s[:60]] += 1
    if "contributing_factors" in d:
        field += 1
    if d.get("contributing_factors"):
        nonempty_f += 1
        if len(sample_nonempty) < 3:
            sample_nonempty.append(d)
    if d.get("witnesses"):
        nonempty_w += 1

print(json.dumps({
    "rows": rows,
    "unparsable": unparsable,
    "field_present": field,
    "nonempty_contributing_factors": nonempty_f,
    "nonempty_witnesses": nonempty_w,
    "sources_top": dict(src.most_common(12)),
    "sample_nonempty": sample_nonempty,
}, indent=2, sort_keys=True, default=str))
