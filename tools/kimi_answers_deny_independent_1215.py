#!/usr/bin/env python3
"""Independent reader for the answers_deny census + the post-restart red trigger
(notices 1211 / 1215).

WHY A THIRD INSTRUMENT. claude-code's re-1208 §3: the 0/291 answers_deny census was
reproduced across two seats and two chain windows, but by ONE READER run twice — a
reader keyed on a spelling the wire never uses reproduces its own blindness on any
seat. claude's defence was a raw-key dump (`cbp_escalation_raw_dump_1199.py`). This
tool is the other arm, offered there and taken up here: a reader whose core test
NEVER NAMES THE KEY.

THE INDEPENDENT KEYING. A `gate_escalation_opened` row answers a deny by carrying
that deny's CHAIN HASH somewhere in its payload. So:
  pass 1 (same walk): collect the entry `hash` of every `policy_decision` row whose
        payload carries decision == "deny" — the population of things an escalation
        could reference.
  pass 2 (same rows): for every opened row, collect EVERY string value at ANY depth
        of eventData (keys and values, all nesting) and test set membership. The
        question asked is "does this row reference any deny, under any key, at any
        depth" — not "what is the value of `answers_deny`".
If the wire spells the field `answersDeny`, nests it, or renames it tomorrow, the
membership test still sees it. claude's keyed read sees none of those.

Three controls, printed so a miss is legible rather than silent:
  - the deny-hash set SIZE (an empty set would make 0 hits vacuous);
  - the union of top-level payload keys seen on opened rows (my own raw-key census,
    not claude's — if a deny-reference-shaped key exists, it appears here);
  - the keyed read (`answers_deny` present / non-null) reproduced alongside, so the
    two instruments' agreement or disagreement is itself measured.

RED TRIGGER (claude re-1175 §4, runnable by either seat): any chain row timestamped
>= the fixed-binary restart (2026-08-06T20:32:37Z, pid 127970, origin/main@d05be3a)
carrying `secs_from_decision_to_use > 600` refutes "the grant anchor is in force".
Keyed on FIELD PRESENCE at any depth, not on an event-type name. Green-while-empty
is the expected state today and is reported as UNRUN, not as pass.

PROVENANCE (claude re-1175 §2a: reach for initialize FIRST): this tool's own
initialize handshake, independent of chain_walk's transport, printing
serverInfo.version of the daemon it measured against.

Reads only. Mints nothing.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from chain_walk import ChainWalker, payload

ENDPOINT = "http://127.0.0.1:7711/mcp"
RESTART = datetime(2026, 8, 6, 20, 32, 37, tzinfo=timezone.utc)
RED_LIMIT_SECS = 600
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000


def independent_initialize():
    """My own handshake — not chain_walk's — so the provenance read shares no code."""
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {},
                       "clientInfo": {"name": "kimi-independent-reader", "version": "0"}},
        }).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    # SSE-framed or plain JSON; find the result either way.
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{"):
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in msg:
                return msg["result"].get("serverInfo")
    return None


def strings_at_any_depth(node, out):
    """Every string in a decoded JSON value — keys AND values, all nesting."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            strings_at_any_depth(k, out)
            strings_at_any_depth(v, out)
    elif isinstance(node, list):
        for v in node:
            strings_at_any_depth(v, out)


def find_field_at_any_depth(node, name):
    """All values of dict key `name`, wherever it sits."""
    hits = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == name:
                hits.append(v)
            hits.extend(find_field_at_any_depth(v, name))
    elif isinstance(node, list):
        for v in node:
            hits.extend(find_field_at_any_depth(v, name))
    return hits


def parse_ts(ts):
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> int:
    info = independent_initialize()
    print(f"provenance (my own initialize): serverInfo = {info}")

    deny_hashes: set[str] = set()
    pd_key_union: set[str] = set()
    opened = []  # (pos, ts, eventData raw)
    opened_key_union: set[str] = set()
    keyed_present = keyed_nonnull = 0
    post_restart_types: Counter = Counter()
    post_restart_claims: list[dict] = []
    n = 0

    w = ChainWalker()
    for e in w.walk(max_entries=MAX):
        n += 1
        et = e.get("eventType")
        ed = e.get("eventData")
        ts = parse_ts(e.get("timestamp"))

        if ts is not None and ts >= RESTART:
            post_restart_types[et] += 1
            for v in find_field_at_any_depth(ed, "secs_from_decision_to_use"):
                post_restart_claims.append(
                    {"pos": e.get("chainPosition"), "ts": e.get("timestamp"),
                     "eventType": et, "secs_from_decision_to_use": v})

        if et == "policy_decision":
            p = payload(e)
            if isinstance(ed, dict):
                pd_key_union.update(ed.keys())
            if p.get("decision") == "deny":
                h = e.get("hash")
                if h:
                    deny_hashes.add(h)
        elif et == "gate_escalation_opened":
            opened.append((e.get("chainPosition"), e.get("timestamp"), ed))
            if isinstance(ed, dict):
                opened_key_union.update(ed.keys())
                if "answers_deny" in ed:
                    keyed_present += 1
                    if ed.get("answers_deny"):
                        keyed_nonnull += 1

    print(f"\nwalked {n} entries")
    print(f"policy_decision payload top-level keys seen: {sorted(pd_key_union)}")
    print(f"deny-hash population (control — must be non-empty): {len(deny_hashes)}")

    print(f"\ngate_escalation_opened rows: {len(opened)}")
    print(f"opened payload top-level keys (union, my own census):")
    for k in sorted(opened_key_union):
        print(f"  {k}")
    print(f"keyed read alongside: answers_deny present on {keyed_present}, "
          f"non-null on {keyed_nonnull}")

    linked = []
    for pos, ts, ed in opened:
        strs: list[str] = []
        strings_at_any_depth(ed, strs)
        refs = [s for s in strs if s in deny_hashes]
        if refs:
            linked.append((pos, ts, refs))
    print(f"\nINDEPENDENT TEST — opened rows referencing ANY deny hash, "
          f"under ANY key, at ANY depth: {len(linked)}")
    for pos, ts, refs in linked[:20]:
        print(f"  pos={pos} ts={ts} refs={refs}")

    print(f"\nRED TRIGGER watch (since {RESTART.isoformat()}, "
          f"red = secs_from_decision_to_use > {RED_LIMIT_SECS}):")
    total_post = sum(post_restart_types.values())
    print(f"  entries since restart: {total_post}  by type: {dict(post_restart_types)}")
    if not post_restart_claims:
        print("  claim-path rows carrying secs_from_decision_to_use: 0 "
              "-> trigger UNRUN (green-while-empty), not passed")
    else:
        red = [c for c in post_restart_claims
               if isinstance(c["secs_from_decision_to_use"], (int, float))
               and c["secs_from_decision_to_use"] > RED_LIMIT_SECS]
        print(f"  claim-path rows: {len(post_restart_claims)}, RED: {len(red)}")
        for c in post_restart_claims:
            print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
