#!/usr/bin/env python3
"""Two openers, one chain: which door actually wrote each `gate_escalation_opened`?

Independent check of claude-code's notice 1419 ("PR241 DEPLOYED AND REFUTED AT THE
LAST RUNG"). The claim under test:

  - `tool_gate_escalation_open` (handler.rs:10294) carries the PR #241 invitation
    writer: `asker_basis`, `invited_peers`, `invitation_evidence`,
    `invitation_withheld`, `invitation_passed_over`, and `bar`.
  - `tool_gate_escalation_claim` (handler.rs:10841) — the entry point the gate hook
    actually calls (plugins/claude-code/hooks/pre_tool_use.py:1205) — has its OWN
    `open()` + `append_chain` fallback (handler.rs:10906-10929) whose payload has
    none of those keys, not even `bar`.
  - So production escalations keep the pre-#241 shape and the invitation writer is
    on a door nobody walks through.

Method: walk the whole witness chain (`chain_walk.ChainWalker`, prevHash pointer
lookups — the window path caps at 500 and lies about it), fingerprint every
`gate_escalation_opened` payload by KEY SET (a key present with a null/empty value
still counts as present — the claim is about which fields reach the chain at all),
and split by deploy era. Also prints the two specimens the notice names
(91020e61… = Bash, 3c6d7c10… = Write) in full, so the shape claim is checkable
against the entries themselves rather than against a count.

Shapes (derived from the source, named so the reader can re-derive them):
  A. "claim-path"     : `stated_reason` key present, `bar` absent
                        (handler.rs:10912-10928; the ONLY writer with stated_* keys)
  B. "open-post-241"  : `asker_basis` present (handler.rs:10499 — PR #241 and later)
  C. "open-pre-241"   : `bar` present, `asker_basis` absent (5555b71 shape)
  D. "pre-bar"        : neither `bar` nor `stated_reason` (before the Bar existed)
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 400_000
SPECIMENS = ("91020e61", "3c6d7c10")

# Daemon restart markers: session_started entries carry the build. PR #246's merge
# (8a84a7e, containing #241) is what claude-code's notice says is live; any opened
# entry NEWER than the first session_started advertising that build was written by
# the deployed code under test.


def shape_of(p: dict) -> str:
    has = p.__contains__
    if has("stated_reason") and not has("bar"):
        return "A.claim-path"
    if has("asker_basis"):
        return "B.open-post-241"
    if has("bar"):
        return "C.open-pre-241"
    return "D.pre-bar"


def main() -> int:
    w = ChainWalker()
    shapes: Counter = Counter()
    shape_tools: dict[str, Counter] = {}
    shape_plugins: dict[str, Counter] = {}
    shape_first: dict[str, str] = {}
    shape_last: dict[str, str] = {}
    key_counts: Counter = Counter()
    opened_total = 0
    walked = 0
    specimens: dict[str, tuple] = {}
    dated_shapes: list[tuple[str, str]] = []  # (timestamp, shape) per opened entry

    for e in w.walk(max_entries=MAX):
        walked += 1
        et = e.get("eventType") or ""
        ts = e.get("timestamp") or ""
        h = e.get("hash") or ""
        if et != "gate_escalation_opened":
            continue
        opened_total += 1
        p = payload(e) or {}
        # The notice's specimens are ESCALATION-ID prefixes (the pointer itself is
        # hestia://escalation/91020e61faf87e59), not chain-entry hashes — matching
        # `hash` here was this tool's first-draft bug and reported both NOT FOUND.
        eid = str(p.get("escalation_id") or "")
        for pref in SPECIMENS:
            if eid.startswith(pref) or h.startswith(pref):
                specimens[pref] = (e, p)
        key_counts.update(p.keys())
        s = shape_of(p)
        shapes[s] += 1
        dated_shapes.append((ts, s))
        shape_tools.setdefault(s, Counter())[p.get("tool_name") or "?"] += 1
        shape_plugins.setdefault(s, Counter())[p.get("plugin_id") or "?"] += 1
        # walk is newest -> oldest
        shape_last.setdefault(s, ts)
        shape_first[s] = ts

    # Deploy-day split. The chain does not record daemon restarts (the only
    # session_started entries are from 2026-05-17), so the boundary is a DATE, not
    # a witnessed marker: PR #246 (8a84a7e, containing #241) merged 2026-08-07
    # ~01:20-07:30 and the live daemon's `initialize` reported
    # "0.0.3 (app-v0.1.2-653-g8a84a7e)" when this census ran. Every opened entry
    # stamped 2026-08-07 post-merge was written by code containing BOTH PRs.
    cutoff = "2026-08-07"
    deploy_day: Counter = Counter()
    for ts, s in dated_shapes:
        if ts >= cutoff:
            deploy_day[s] += 1

    print(f"chain entries walked      : {walked}")
    print(f"gate_escalation_opened    : {opened_total}")
    print()
    print("=== shapes over ALL opened entries (newest->oldest walk) ===")
    for s, c in shapes.most_common():
        print(f"  {s:16s} n={c:4d}  span {shape_first[s]} .. {shape_last[s]}")
        print(f"    tools  : {dict(shape_tools[s].most_common(6))}")
        print(f"    plugins: {dict(shape_plugins[s].most_common(6))}")
    print()
    print("=== key census over opened payloads (key present at all) ===")
    for k, c in key_counts.most_common():
        print(f"  {k:26s} {c}")
    print()
    print("=== the 1419 fingerprint: `bar` present on opened payloads ===")
    bar_count = key_counts.get("bar", 0)
    print(f"  bar on {bar_count} of {opened_total}")
    print(f"  invited_peers on {key_counts.get('invited_peers', 0)} of {opened_total}")
    print(f"  asker_basis on {key_counts.get('asker_basis', 0)} of {opened_total}")
    print()
    print(f"=== opened entries on/after {cutoff} (deploy day; live daemon reports "
          "app-v0.1.2-653-g8a84a7e) ===")
    print(f"  {dict(deploy_day) or 'none'}")
    print()
    print("=== specimens named in notice 1419 (escalation-id prefixes) ===")
    for pref in SPECIMENS:
        hit = specimens.get(pref)
        if hit is None:
            print(f"  {pref}…: NOT FOUND on chain")
            continue
        e, p = hit
        print(f"  --- escalation {p.get('escalation_id')} (chain entry "
              f"{(e.get('hash') or '')[:16]}…, {e.get('timestamp') or ''})")
        print(json.dumps(p, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
