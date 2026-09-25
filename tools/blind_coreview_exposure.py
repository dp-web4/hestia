#!/usr/bin/env python3
"""Per-seat prior-exposure grep for a drawn probe list. Prints HIT COUNTS per location
class only, never the matching text: the context around an escalation id is exactly
where a ruling would be quoted, and reading it to classify the hit is the exposure.

Usage: blind_coreview_exposure.py [--prefix N] [--quarantine STR] <draw.json> <dir-or-file>...
  (each arg = one location)

--prefix N     also match the first N chars of each id (codex's screen, 86ef864: an
               8-char prefix flagged 3 of 94 unattributed ids that a full-id grep missed).
               Counted under "<loc>#prefix", separately from full-id hits.
--quarantine S a file containing S is counted under "<loc>#quarantine" instead of <loc>.
               Publishing or screening the draw writes every id into the screener's own
               transcripts, so those files hit everything without carrying any outcome.
               They are reported, never silently dropped.
"""
import json, os, re, sys
args = sys.argv[1:]
prefix, quarantine = 0, None
while args and args[0].startswith("--"):
    flag, val, args = args[0], args[1], args[2:]
    if flag == "--prefix":
        prefix = int(val)
    elif flag == "--quarantine":
        quarantine = val
    else:
        sys.exit(f"unknown flag {flag}")
draw = json.load(open(args[0]))
eids = [p["eid"] for p in draw["picks"]]
for rsv in draw["reserve"].values():
    eids += rsv                          # the whole reserve: replacement then needs no re-grep
hits = {e: {} for e in eids}
ID_LEN = len(eids[0])
assert all(len(e) == ID_LEN and re.fullmatch("[0-9a-f]+", e) for e in eids)
HEX = re.compile("[0-9a-f]{%d,}" % min(ID_LEN, prefix or ID_LEN))
for loc in args[1:]:
    paths = [loc] if os.path.isfile(loc) else [os.path.join(r, f) for r, _, fs in os.walk(loc) for f in fs]
    for p in paths:
        try:
            s = open(p, errors="ignore").read()
        except OSError:
            continue
        key = loc + "#quarantine" if quarantine and quarantine in s else loc
        # Same answer as `e in s` per id, without 180 scans of a 4 GB corpus: an id is
        # lowercase hex, so any occurrence lies inside a maximal hex run; collect that
        # run's windows of each needed length once and test membership.
        full, pre = set(), set()
        for run in HEX.findall(s):
            full.update(run[i:i + ID_LEN] for i in range(len(run) - ID_LEN + 1))
            if prefix:
                pre.update(run[i:i + prefix] for i in range(len(run) - prefix + 1))
        for e in eids:
            if e in full:
                hits[e][key] = hits[e].get(key, 0) + 1
            elif prefix and e[:prefix] in pre:
                hits[e][key + "#prefix"] = hits[e].get(key + "#prefix", 0) + 1
json.dump(hits, sys.stdout, indent=1, sort_keys=True)
