#!/usr/bin/env python3
"""Where the unanswered fold ENDS, and what that hides.

`hestia_member_unanswered` is the only member-reachable ledger of mesh responsiveness,
and it is a 7-day sliding window: `INBOX_TTL_SECS` (inbox.rs) deletes local notices
older than the cutoff on every enqueue and every drain. So a row leaves the fold by two
paths that look identical from outside -- somebody bound a reply to it, or the clock
deleted it -- and no surface says which.

This measures both edges:

  1. the right edge of the live fold (expected: nothing older than 7d), and the
     TERMINAL cohort at 6.0-7.0d whose fate is hours from being settled by deletion;
  2. the archived wake primers on disk, which are the only member-side record that
     OUTLIVES the store, giving the denominator the fold cannot report;
  3. a cross-reference of `i_owe` against that archive, which is the discriminator for
     issue #884: rows that never reached a primer, and whether the fold hands you their
     id anyway (it does -- `member_unanswered` returns `id` for every row).

Read-only. Needs the fold as JSON:

    HESTIA_MESH_PLUGIN=claude-code python3 .../hestia-mesh.py unanswered 0 > /tmp/fold.json
    python3 tools/fold_edge_census.py /tmp/fold.json
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import sys

PRIMERS = "/home/dp/.claude/hestia-mesh-primers/notice-*.json"
FOLD_KINDS = {"review_request", "reply"}  # MEMBER_KINDS_AWAIT_RESPONSE


def _parse(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_primer_notices(pattern: str = PRIMERS) -> dict:
    """Every notice this seat was ever handed, by id. Unparsable primers are counted,
    not skipped silently -- a truncated primer is a hole in the denominator."""
    out, bad, files = {}, 0, sorted(glob.glob(pattern))
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            bad += 1
            continue
        for n in d.get("notices") or []:
            if n.get("id") is not None:
                out.setdefault(n["id"], n)
    return {"notices": out, "files": len(files), "unparsable": bad}


def main(fold_path: str) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    fold = json.load(open(fold_path))
    arch = load_primer_notices()
    prim = arch["notices"]

    print(f"primers: {arch['files']} files ({arch['unparsable']} unparsable), "
          f"{len(prim)} distinct notices")

    for key in ("i_owe", "owed_to_me"):
        rows = fold.get(key) or []
        ages = sorted((now - _parse(r["queued_at"])).total_seconds() / 86400 for r in rows)
        if not ages:
            print(f"{key}: empty")
            continue
        beyond = [a for a in ages if a > 7.0]
        print(f"{key}: n={len(rows)} oldest={ages[-1]:.3f}d beyond-7d={len(beyond)}")
        term = [r for r in rows
                if 6.0 < (now - _parse(r["queued_at"])).total_seconds() / 86400 <= 7.0]
        print(f"  terminal cohort (6.0-7.0d): {len(term)} rows, "
              f"kinds={dict(collections.Counter(r['kind'] for r in term))}, "
              f"from={dict(collections.Counter(r['from_plugin'] for r in term))}")

    debt = {i: n for i, n in prim.items() if n.get("kind") in FOLD_KINDS}
    age = {i: (now - _parse(n["queued_at"])).total_seconds() / 86400 for i, n in debt.items()}
    old = [i for i in debt if age[i] > 7.0]
    print(f"debt notices ever delivered: {len(debt)}; past TTL (unauditable): "
          f"{len(old)} = {len(old) / max(1, len(debt)):.1%}")

    iowe = fold.get("i_owe") or []
    absent = [r for r in iowe if r["id"] not in prim]
    print(f"i_owe rows never carried by a primer (#884 class): {len(absent)} of {len(iowe)}; "
          f"fold row carries own id for {sum(1 for r in absent if r.get('id') is not None)} "
          f"of {len(absent)} -- bindable now")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fold.json")
