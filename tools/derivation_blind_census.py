#!/usr/bin/env python3
"""How much of the witness chain can the trust fold actually see?

Two seats argued the `member_notice` exclusion entirely from source: kimi computed
gate two's key intersection BY HAND against the mint's ten literals; I tabulated the
same file from the other side. Neither of us asked the chain. This does.

It answers three things source-reading cannot:

  1. THE POPULATION, per event type, as-of a named chain head — including the
     population EXCLUDED by `DERIVATION_EVENT_TYPES`. `member_notice` is one member of
     that set; the interesting number is the set's size and share, because that
     reframes "one producer got missed" as "the fold reads N% of what is witnessed."

  2. GATE TWO, MEASURED. kimi's ∅ intersection is a claim about the keys the mint
     EMITS. Rows on the chain are the keys that were emitted, across every mint
     version that ever ran. If any historical `member_notice` row carries a
     `DERIVATION_KEYS` name, the hand-computed ∅ is a statement about today's source,
     not about the data — and the fold would fold a content-free row rather than skip
     it. Per-row intersection, not per-source-literal.

  3. THE OTHER ALLOWLISTS. `actor_liveness` carries its own `ACT_TYPES` (4 literals).
     Its excluded population is a different, larger set than derivation's. Reported
     alongside, because the repair surface is a list of lists and a census of one list
     certifies only that list.

Reads only. Quotes counts as-of the head hash it started from, because the population
moves under you (695 -> 696 in twenty minutes, measured 2026-08-03).

    python3 tools/derivation_blind_census.py [--max 200000]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

# Transcribed verbatim from core/src/derivation.rs:144-148 (pin recorded at runtime).
DERIVATION_EVENT_TYPES = {
    "adjudication", "amnesty", "appeal", "exoneration", "gate_escalation_decided",
    "gate_escalation_opened", "outcome", "policy_decision", "scope_attestation",
    "identity_alias",  # IDENTITY_ALIAS_EVENT
}
# core/src/derivation.rs:133-140
DERIVATION_KEYS = {
    "about_deny_hash", "alias", "alias_of", "answers_deny", "attempted", "axis", "data",
    "decision", "deny_hash", "enforced", "escalation_id", "method", "plugin_id", "reason",
    "ref", "requested_by", "role_lct", "score", "session_id", "status",
    "subject_plugin_id", "subject_role", "success", "target", "tool_name", "upheld",
    "verdict", "verdict_available",
}
# core/src/server/handler.rs:2441 — actor_liveness
ACT_TYPES = {"outcome", "policy_decision", "adjudication", "appeal"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200000)
    ap.add_argument("--focus", default="member_notice",
                    help="event type to report key-level detail for")
    args = ap.parse_args()

    w = ChainWalker()
    by_type: Counter[str] = Counter()
    focus_keysets: Counter[tuple] = Counter()
    focus_key_hits: Counter[str] = Counter()
    focus_derivable = 0
    head = None
    oldest = None
    n = 0

    for e in w.walk(max_entries=args.max):
        n += 1
        if head is None:
            head = e.get("hash")
        oldest = e
        et = e.get("eventType") or "<none>"
        by_type[et] += 1
        if et == args.focus:
            p = payload(e) or {}
            keys = tuple(sorted(p.keys()))
            focus_keysets[keys] += 1
            for k in keys:
                focus_key_hits[k] += 1
            if DERIVATION_KEYS & set(keys):
                focus_derivable += 1

    seen = set(by_type)
    excl_deriv = seen - DERIVATION_EVENT_TYPES
    excl_act = seen - ACT_TYPES
    rows_deriv = sum(c for t, c in by_type.items() if t in DERIVATION_EVENT_TYPES)
    rows_act = sum(c for t, c in by_type.items() if t in ACT_TYPES)

    out = {
        "as_of_head": head,
        "entries_walked": n,
        "oldest_reached": (oldest or {}).get("timestamp"),
        "distinct_event_types": len(seen),
        "derivation": {
            "types_visible": sorted(seen & DERIVATION_EVENT_TYPES),
            "types_declared_never_seen": sorted(DERIVATION_EVENT_TYPES - seen),
            "types_excluded": sorted(excl_deriv),
            "rows_visible": rows_deriv,
            "rows_excluded": n - rows_deriv,
            "share_visible": round(rows_deriv / n, 4) if n else None,
        },
        "actor_liveness": {
            "types_excluded": sorted(excl_act),
            "rows_visible": rows_act,
            "share_visible": round(rows_act / n, 4) if n else None,
        },
        "focus": {
            "event_type": args.focus,
            "rows": by_type.get(args.focus, 0),
            "distinct_keysets": [
                {"count": c, "keys": list(k),
                 "derivation_keys_present": sorted(DERIVATION_KEYS & set(k))}
                for k, c in focus_keysets.most_common()
            ],
            "rows_with_any_derivation_key": focus_derivable,
        },
        "by_type": by_type.most_common(),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
