#!/usr/bin/env python3
"""Pass 2: the seeded stratified draw for the blind co-review pilot. Re-runnable by the
auditing seat: same pool dump + same seed => same list, byte for byte.

Filter (fixed before the seed exists):
  1. terminal before CUTOFF (the beacon timestamp): nothing is authorized by a probe;
  2. asker is neither reviewer: your own petition is prior exposure to its whole record;
  3. no peer factor filed by either reviewer before CUTOFF (so a later walk reproduces the pool);
  4. opened payload present (the packet needs the act as asked).
Strata are PRE-DECISION fields only (see STRATUM). The proposal's "clean approvals" and
"self-withdrawals" strata are outcome-defined, so stratifying on them would show the
drawer — who is also a reviewer — each probe's ruling by its stratum label. They are
dropped here; the outcome mix is reported by the auditor after both seals, not before.
Output: ids and pre-decision strata only. The outcome is never read.
Usage: python3 tools/blind_coreview_draw.py /tmp/pool.json <seed hex> <cutoff timestamp>
"""
import hashlib, json, random, sys
from collections import defaultdict
REVIEWERS = ("claude-code", "kimi-code")
N = 20

def stratum(o):
    # Measured on the eligible pool before the seed existed: payload_basis, gate_path and
    # payload_stated_but_not_measured are None on all 180 (older schema), and marker is set
    # on all 180, so the proposal's record-shape strata are degenerate here. Asker x tool
    # class are the pre-decision fields that actually vary.
    shell = "shell" if o.get("tool_name") == "Bash" else "non-shell"
    return f"{o.get('plugin_id')}/{shell}"

def main(pool_path, seed_hex, cutoff):
    pool = json.load(open(pool_path))
    factored = {f["eid"] for f in pool["factors"] if f["by"] in REVIEWERS and f["ts"] < cutoff}
    strata = defaultdict(list)
    for eid, o in pool["opened"].items():
        t = pool["terminal_at"].get(eid)
        if t is None or t >= cutoff or o.get("plugin_id") in REVIEWERS or eid in factored:
            continue
        strata[stratum(o)].append(eid)
    rng = random.Random(int(seed_hex, 16))
    keys = sorted(strata)
    # equal allocation, remainder to the largest strata; capped by stratum size
    alloc = {k: 0 for k in keys}; left = N
    while left:
        open_ = [k for k in keys if alloc[k] < len(strata[k])]
        if not open_: break
        for k in sorted(open_, key=lambda k: -len(strata[k])):
            if left and alloc[k] < len(strata[k]): alloc[k] += 1; left -= 1
    # Each stratum is fully shuffled; the first alloc[k] are the probes, the rest are the
    # REPLACEMENT ORDER. A probe dropped for prior exposure (either seat's grep) is replaced
    # by the next reserve id of its stratum, so replacement is not a choice either.
    picks, reserve = [], {}
    for k in keys:
        order = rng.sample(sorted(strata[k]), len(strata[k]))
        picks += [{"eid": eid, "stratum": k} for eid in order[:alloc[k]]]
        reserve[k] = order[alloc[k]:]
    report = {"seed": seed_hex, "cutoff": cutoff,
              "pool_sizes": {k: len(strata[k]) for k in keys}, "alloc": alloc,
              "picks": picks, "reserve": reserve}
    body = json.dumps(report, indent=1, sort_keys=True)
    print(body); print("list_sha256", hashlib.sha256(body.encode()).hexdigest(), file=sys.stderr)

if __name__ == "__main__":
    main(*sys.argv[1:4])
