#!/usr/bin/env python3
"""Does the gate's act binding (#539) bind the ACT, or only its DESTINATION?

`EscalationStore::act_digest_of` is sha256(attempted_act.trim()) and
`EscalationStore::claim(plugin_id, marker, attempted_act, now)` takes NO tool_name
(core/src/server/gate_escalation.rs:1531 / :1537-1591 on origin/main). So a grant is
a token keyed on (plugin_id, marker, digest). This probe asks, FROM THE WIRE, what
string that digest is actually over -- by recomputing sha256(stated_reason) for every
`gate_escalation_opened` row and comparing.

If digest == sha256(stated_reason) and stated_reason is a bare destination path, then
the bound "act" carries no content and no tool name: an approval to Edit a path is a
bearer token for a full-file Write of the same path.

Reports the SPAN scanned so no rate can be quoted without its denominator.
"""
from __future__ import annotations
import hashlib, json, sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 6000


def main() -> int:
    w = ChainWalker()
    opened, matched, no_digest, no_reason = 0, 0, 0, 0
    scanned = 0
    first = last = None
    by_digest: dict[str, list[dict]] = defaultdict(list)
    mismatches = []
    for e in w.walk(max_entries=MAX):
        scanned += 1
        ts = e.get("timestamp")
        if first is None:
            first = ts
        last = ts
        if e.get("eventType") != "gate_escalation_opened":
            continue
        p = payload(e)
        opened += 1
        d = p.get("act_digest")
        r = p.get("stated_reason")
        if not d:
            no_digest += 1
            continue
        if not r:
            no_reason += 1
            continue
        recomputed = hashlib.sha256(r.strip().encode()).hexdigest()
        rec = {
            "id": p.get("escalation_id"),
            "tool": p.get("tool_name"),
            "plugin": p.get("plugin_id"),
            "marker": p.get("marker"),
            "reason": r,
            "at": ts,
            "opened_via": p.get("opened_via"),
        }
        by_digest[d].append(rec)
        if recomputed == d:
            matched += 1
        else:
            mismatches.append(rec)

    # A digest carried by >1 escalation is a reusable join key.
    shared = {d: v for d, v in by_digest.items() if len(v) > 1}
    cross_tool = {
        d: v for d, v in shared.items() if len({r["tool"] for r in v}) > 1
    }
    out = {
        "span": {"scanned": scanned, "newest": first, "oldest": last, "cap": MAX,
                 "hit_cap": scanned >= MAX},
        "opened_rows": opened,
        "digest_over_stated_reason": matched,
        "digest_mismatch": len(mismatches),
        "no_act_digest": no_digest,
        "no_stated_reason": no_reason,
        "distinct_digests": len(by_digest),
        "digests_shared_by_multiple_escalations": len(shared),
        "shared_and_cross_tool": len(cross_tool),
        "cross_tool_detail": {
            d: {"n": len(v), "tools": sorted({r["tool"] for r in v}),
                "plugins": sorted({r["plugin"] for r in v}),
                "markers": sorted({r["marker"] for r in v}),
                "reason": v[0]["reason"], "ids": [r["id"] for r in v]}
            for d, v in list(cross_tool.items())[:20]
        },
        "mismatch_sample": mismatches[:5],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
