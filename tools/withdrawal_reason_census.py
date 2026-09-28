#!/usr/bin/env python3
"""What is `self_withdrawn` actually USED for, and does anything read it?

A withdrawal is recorded as status=denied, bar_met=false, assurance="NONE -- the asker
refused its own request". To every counter that groups by status, it is indistinguishable
from a governance write that a reviewer refused. This asks what the population actually
contains, by reading the free-text reason the asker wrote.

Classes are decided by SEMANTIC MARKERS the askers themselves used, and each row is
printed with its class so the classification can be audited rather than trusted.
"""
from __future__ import annotations
import sys, re
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000

# Markers kept here, never on a command line, so this run does not enter the corpus.
FALSE_POSITIVE = re.compile(
    r"read-only|readonly|no write|not a write|no governed write|false positive|"
    r"out of grammar|marker appeared|marker-text|loop data|do not want this write|"
    r"do not need this write", re.I)
DUPLICATE = re.compile(r"duplicat|redundant|already approved|already been|re-file|refile", re.I)


def main() -> int:
    w = ChainWalker()
    rows, scanned = [], 0
    first = last = None
    for e in w.walk(max_entries=MAX):
        scanned += 1
        ts = e.get("timestamp")
        if ts:
            last = last or ts
            first = ts
        if (e.get("eventType") or "") != "gate_escalation_withdrawn":
            continue
        p = payload(e)
        rows.append({"eid": p.get("escalation_id"), "by": p.get("decided_by"),
                     "via": p.get("decided_via"), "marker": p.get("marker"),
                     "status": p.get("status"), "bar_met": p.get("bar_met"),
                     "reason": p.get("reason") or "", "ts": ts})

    cls = Counter(); by_asker = Counter(); by_marker = Counter()
    detail = defaultdict(list)
    for r in rows:
        fp, du = bool(FALSE_POSITIVE.search(r["reason"])), bool(DUPLICATE.search(r["reason"]))
        c = "false_positive" if (fp and not du) else "duplicate" if (du and not fp) else \
            "both" if (fp and du) else "other"
        r["class"] = c
        cls[c] += 1; by_asker[r["by"]] += 1; by_marker[r["marker"]] += 1
        detail[c].append(r)

    print(f"SPAN: {scanned} entries, {first} .. {last}")
    print(f"withdrawals: {len(rows)}")
    print(f"  status values recorded: {Counter(r['status'] for r in rows)}")
    print(f"  bar_met values:         {Counter(r['bar_met'] for r in rows)}")
    print(f"  decided_via:            {Counter(r['via'] for r in rows)}")
    print()
    print("-- what the asker said it was --")
    for c, n in cls.most_common():
        print(f"  {c:<16} {n:>3}  ({100*n/len(rows):.0f}%)")
    print()
    print("-- by asker --");  [print(f"  {k:<14} {v}") for k, v in by_asker.most_common()]
    print()
    print("-- markers most often tripped and then withdrawn --")
    for k, v in by_marker.most_common(8):
        print(f"  {k!r:<34} {v}")
    print()
    for c in ("other", "both"):
        if detail[c]:
            print(f"-- audit: class={c} --")
            for r in detail[c]:
                print(f"  {r['eid']} {r['reason'][:170]!r}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
