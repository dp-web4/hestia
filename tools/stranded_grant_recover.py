#!/usr/bin/env python3
"""Recover and spend a gate approval whose asking wake is already dead.

WHY THIS EXISTS. A mesh wake is short; the escalation decision window is 3600s. So the
common case is: a seat opens an escalation, the wake ends, the operator approves, and the
approval reaches the seat one wake later as a `disposition` notice. By then the act string
the approval is BOUND to (#539 — "you must re-issue the SAME string to claim it") is gone
with the asking wake's context. The fire log keeps only a wake's final output; the daemon's
`hestia_gate_escalation_poll` does not return the act; the chain stores only `act_digest`.

So the seat is told "you hold an approval" and cannot spend it. That is exactly the failure
#667 was built to stop ("a member working asynchronously watched five grants die unspent").
#667 fixed the CLOCK — the claim fuse now burns from observation, so a later wake still has
its 600s. Nothing fixed the ACT.

WHAT MAKES RECOVERY POSSIBLE, AND WHY THAT IS UNCOMFORTABLE. `act_digest` is
sha256(stated_reason.strip()), and `stated_reason` IS on the chain. That identity is #627 —
filed and closed as a DEFECT, because the digest binds a 220/400-char TRUNCATED preview
rather than the act, so prefix-colliding commands share a grant. This tool is the same fact
read from the other side: the only reason a stranded grant is recoverable at all is that the
thing it is bound to was persisted. Bind the digest to the real act without persisting the
act, and every cross-wake grant becomes permanently unspendable.

Read `--census` before quoting a recovery rate: a row whose digest does NOT reproduce from
its `stated_reason` has an act that exists nowhere durable, and no later wake can spend it.

    python3 tools/stranded_grant_recover.py --as claude-code            # what can I spend?
    python3 tools/stranded_grant_recover.py --as claude-code --census   # how much is lost?
    python3 tools/stranded_grant_recover.py --as claude-code --claim <escalation_id>

Read-only unless --claim. --claim SPENDS the approval (single use) and witnesses the spend;
perform the act afterwards or you have burned a grant for nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402


def recompute(stated_reason: str | None) -> str | None:
    if stated_reason is None:
        return None
    return hashlib.sha256(stated_reason.strip().encode()).hexdigest()


def collect(w: ChainWalker, max_entries: int):
    """Newest-first walk. Returns (opened_rows_by_id, decided_rows_by_id, span)."""
    opened: dict[str, dict] = {}
    decided: dict[str, dict] = {}
    first = last = None
    for e in w.walk(max_entries=max_entries):
        ts = e.get("timestamp")
        if first is None:
            first = ts
        last = ts
        t = e.get("eventType")
        if t not in ("gate_escalation_opened", "gate_escalation_decided",
                     "gate_escalation_withdrawn"):
            continue
        p = payload(e)
        eid = p.get("escalation_id")
        if not eid:
            continue
        p = dict(p, _ts=ts)
        if t == "gate_escalation_opened":
            opened.setdefault(eid, p)
        else:
            decided.setdefault(eid, p)
    return opened, decided, (last, first)


def session(w: ChainWalker, plugin_id: str) -> str:
    body = w._call("hestia_connect", {"plugin_id": plugin_id, "host_agent": plugin_id,
                                      "role": "role:constellation:member"})
    return body["sessionId"]


def cmd_list(w: ChainWalker, args) -> int:
    sid = session(w, args.as_)
    opened, decided, span = collect(w, args.max)
    rows = []
    for eid, o in opened.items():
        if o.get("plugin_id") != args.as_:
            continue
        d = decided.get(eid)
        if not d or d.get("status") != "approved":
            continue
        poll = w._call("hestia_gate_escalation_poll",
                       {"session_id": sid, "escalation_id": eid, "plugin_id": args.as_})
        if not poll.get("permits_write"):
            continue
        sr = o.get("stated_reason")
        ok = recompute(sr) == o.get("act_digest")
        rows.append((eid, o, poll, sr, ok))
    print(f"span {span[0]} .. {span[1]}  ({args.max} hops)")
    if not rows:
        print(f"no spendable approval for {args.as_}")
        return 0
    for eid, o, poll, sr, ok in rows:
        print(f"\n=== {eid}  marker={o.get('marker')!r} tool={o.get('tool_name')!r}")
        print(f"    claim window {poll.get('claim_window_secs_remaining')}s"
              f"  decided_by={poll.get('decided_by')}  reason={poll.get('reason')!r}")
        print(f"    act RECOVERABLE: {ok}"
              + ("" if ok else "  <-- digest does not reproduce; the act is LOST"))
        if ok:
            truncated = sr.rstrip().endswith("…")
            print(f"    act ({len(sr)} chars, truncated={truncated}): {sr[:160]}")
    return 0


def cmd_census(w: ChainWalker, args) -> int:
    opened, decided, span = collect(w, args.max)
    tot = bound = reproduces = truncated = no_reason = 0
    approved = approved_reproduces = 0
    for eid, o in opened.items():
        tot += 1
        d = o.get("act_digest")
        sr = o.get("stated_reason")
        if not d:
            continue
        bound += 1
        if sr is None:
            no_reason += 1
            continue
        hit = recompute(sr) == d
        reproduces += hit
        truncated += sr.rstrip().endswith("…")
        dec = decided.get(eid)
        if dec and dec.get("status") == "approved":
            approved += 1
            approved_reproduces += hit
    print(f"span {span[0]} .. {span[1]}  ({args.max} hops)")
    print(f"opened rows              {tot}")
    print(f"  carrying act_digest    {bound}")
    print(f"  digest reproduces      {reproduces}"
          + (f"  ({100*reproduces//bound}%)" if bound else ""))
    print(f"  reason TRUNCATED       {truncated}"
          + (f"  ({100*truncated//bound}%)" if bound else "")
          + "   <-- #627: the grant binds a PREFIX")
    print(f"  no stated_reason       {no_reason}   <-- act unrecoverable by any later wake")
    print(f"APPROVED, act recoverable {approved_reproduces} of {approved}")
    return 0


def cmd_claim(w: ChainWalker, args) -> int:
    sid = session(w, args.as_)
    opened, _decided, _span = collect(w, args.max)
    o = opened.get(args.claim)
    if o is None:
        print(f"no gate_escalation_opened row for {args.claim} within {args.max} hops")
        return 2
    if o.get("plugin_id") != args.as_:
        print(f"that escalation was opened by {o.get('plugin_id')!r}, not {args.as_!r}")
        return 2
    sr = o.get("stated_reason")
    if recompute(sr) != o.get("act_digest"):
        print("REFUSING: sha256(stated_reason) does not reproduce act_digest. The act this "
              "grant is bound to is not on the chain, so it cannot be re-issued. This grant "
              "is stranded; nothing this tool can do will spend it.")
        return 1
    body = w._call("hestia_gate_escalation_claim", {
        "session_id": sid, "plugin_id": args.as_, "role": "role:constellation:member",
        "tool_name": o.get("tool_name"), "marker": o.get("marker"), "act": sr,
        "reason": args.reason,
    })
    print(json.dumps(body, indent=1))
    if body.get("claimed"):
        print("\nSPENT. Now PERFORM the act — a claimed-and-unperformed grant is a burned one:")
        print(f"  {sr}")
    return 0 if body.get("claimed") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as", dest="as_", required=True, help="your plugin_id")
    ap.add_argument("--max", type=int, default=6000, help="hop budget (a budget, not a date)")
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--claim", metavar="ESCALATION_ID")
    ap.add_argument("--reason", default="Re-issuing my own act, reconstructed from the "
                    "chain's stated_reason, to spend a grant whose asking wake has ended.")
    args = ap.parse_args()
    w = ChainWalker()
    if args.claim:
        return cmd_claim(w, args)
    if args.census:
        return cmd_census(w, args)
    return cmd_list(w, args)


if __name__ == "__main__":
    raise SystemExit(main())
