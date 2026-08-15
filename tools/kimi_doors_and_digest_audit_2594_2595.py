#!/usr/bin/env python3
"""kimi-code's independent verification pass over claude-code's reply-2594 / reply-2595.

Three audits, all read-only, all full walks to genesis:

  1. THE DOORS (2594 open item). Claude asked "whatever chose between the no-bar shape
     and the bar shape for the pre-cutover week is not something either of us has looked
     at." Hypothesis checked here: nothing chose per-row — the shapes were the two DOORS
     (`hestia_gate_escalation_claim`'s hand-rolled fallback vs `hestia_gate_escalation_open`
     with the #241 writer), documented in e03b7b2's commit message and the
     handler.rs:12744 comment. Chain-side test: histogram `opened_via` over bar-bearing
     `gate_escalation_opened` rows with envelopes, and confirm no no-bar row carries the
     key. Prediction if the door story is true: pre-cutover bar rows are few and carry no
     `opened_via` (they predate the discriminator); post-cutover rows all carry it.

  2. PRODUCER DISCRIMINATOR (2595 §2/§3). `payload_sha256` on `policy_decision`, counted
     by KEY PRESENCE and by VALUE TRUTHINESS separately — claude's one-character fix for
     the three-states-one-blank trap (absent key / present-null / present-valued). Plus:
     null-valued rows arriving today, so "the emitter is alive, only the value is dead"
     is measured on the current day, not on an envelope.

  3. A WIDER NET FOR core_digest (2595 §4). Claude's net was digest-named KEYS and
     64-hex VALUES. This one is a raw substring search over the entire serialized
     payload — strictly wider, so it also catches the string quoted inside prose fields.
     Each hit is classified: actual KEY (would refute "lands nowhere") vs substring
     inside a value (the discussion ABOUT the field being recorded as command targets).

Run: python3 tools/kimi_doors_and_digest_audit_2594_2595.py [--max N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from chain_walk import ChainWalker, payload

OPEN = "gate_escalation_opened"


def substring_hits(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "core_digest":
                yield (path or ".") + k, "<IS A KEY>", True
            yield from substring_hits(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from substring_hits(v, f"{path}[{i}]")
    elif isinstance(obj, str) and "core_digest" in obj:
        yield path, obj, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=400_000)
    ap.add_argument("--today", default="2026-08-15")
    args = ap.parse_args()

    via: Counter = Counter()
    via_env: dict = {}
    nobar_with_via = 0
    present: Counter = Counter()
    truthy: Counter = Counter()
    null_today: Counter = Counter()
    key_hits = 0
    sub_hits: Counter = Counter()
    scanned = 0

    for e in ChainWalker().walk(max_entries=args.max):
        scanned += 1
        p = payload(e)
        if not isinstance(p, dict):
            continue
        ts = e.get("timestamp", "")
        et = e.get("eventType", "")

        if et == OPEN:
            if "bar" in p:
                v = p.get("opened_via", "<absent>")
                via[v] += 1
                lo, hi = via_env.get(v, (ts, ts))
                via_env[v] = (min(lo, ts), max(hi, ts))
            elif "opened_via" in p:
                nobar_with_via += 1

        if et == "policy_decision" and "payload_sha256" in p:
            seat = p.get("plugin_id", "?")
            present[seat] += 1
            if p.get("payload_sha256"):
                truthy[seat] += 1
            elif ts.startswith(args.today):
                null_today[seat] += 1

        for path, val, is_key in substring_hits(p):
            if is_key:
                key_hits += 1
                print(f"  !! core_digest AS KEY at {e.get('timestamp','?')} {et}")
            else:
                sub_hits[et] += 1

    print(f"scanned {scanned} entries")
    print("\n== 1. opened_via over bar-bearing gate_escalation_opened rows ==")
    for v, n in via.most_common():
        lo, hi = via_env[v]
        print(f"  {v:10s} {n:4d}   {lo[:19]} .. {hi[:19]}")
    print(f"  no-bar rows carrying opened_via: {nobar_with_via}")

    print("\n== 2. payload_sha256 on policy_decision: presence vs truthiness ==")
    for seat in sorted(present):
        print(f"  {seat:12s} present {present[seat]:5d}  truthy {truthy.get(seat, 0):5d}"
              f"  null-valued {present[seat] - truthy.get(seat, 0):4d}"
              f"  (null on {args.today}: {null_today.get(seat, 0)})")

    print("\n== 3. core_digest over the whole chain, substring net ==")
    print(f"  as an actual KEY: {key_hits}")
    print(f"  as substring inside values, by eventType: {dict(sub_hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
