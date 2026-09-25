#!/usr/bin/env python3
"""Per-seat prior-exposure grep for a drawn probe list. Prints HIT COUNTS per location
class only, never the matching text: the context around an escalation id is exactly
where a ruling would be quoted, and reading it to classify the hit is the exposure.

Usage: blind_coreview_exposure.py <draw.json> <dir-or-file>...   (each arg = one location)
"""
import json, os, sys
draw = json.load(open(sys.argv[1]))
eids = [p["eid"] for p in draw["picks"]]
for rsv in draw["reserve"].values():
    eids += rsv                          # the whole reserve: replacement then needs no re-grep
hits = {e: {} for e in eids}
for loc in sys.argv[2:]:
    paths = [loc] if os.path.isfile(loc) else [os.path.join(r, f) for r, _, fs in os.walk(loc) for f in fs]
    for p in paths:
        try:
            s = open(p, errors="ignore").read()
        except OSError:
            continue
        for e in eids:
            if e in s:
                hits[e][loc] = hits[e].get(loc, 0) + 1
json.dump(hits, sys.stdout, indent=1, sort_keys=True)
