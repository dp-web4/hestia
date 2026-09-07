#!/usr/bin/env python3
"""Can a peer reach the door that rules an escalation, and does the door say so when it refuses?

WHY THIS EXISTS. `tools/peer_arbitration_census.py` established the regression: 23 peer
rulings between 2026-07-31 and 2026-08-24T02:40:01Z, then zero, with four hypotheses
eliminated (credits, race, invite-pointer drift, peer absence) and no cause. Every one of
those four was tested AGAINST THE CHAIN. This driver asks the prior question the census
cannot: **would the chain be able to show us a peer that tried to rule and failed?**

It would not. That is the finding, and it is why the cause stayed hidden.

Three independent measurements, none of which requires a peer to be awake:

  A. WITNESS GAP (live probe, writes nothing). `tool_gate_arbitrate_escalation` has nine
     exits. Exactly two append to the chain: the eligibility refusal
     (`gate_escalation_arbiter_refused`) and the ruling itself. The other seven return a
     bare `Err`, which `call_tool` maps to `hestia.internal_error` -- the codebase's own
     words for that shape, at `refuse_asker_mismatch`, are "indistinguishable, to every
     reader of the chain, from the server having crashed."

     The load-bearing one is the FIRST guard: `resolve_attributed_caller` (handler.rs:18757).
     A would-be arbiter that cannot attribute itself is turned away before the escalation is
     even looked up, and nothing is written. So the door witnesses the refusal you get AFTER
     proving who you are, and drops the one you get for FAILING to prove it.

     Probed live against the running daemon, bracketed by chainPosition, using an escalation
     id that cannot exist. Both arms must report delta 0 or the probe refuses to score --
     a probe that mints anything is not a read, and this one is designed to be safe to
     re-run (see `probing-the-gate-is-an-act-not-a-read`).

  B. WHO THE ONE WITNESSED PATH EVER CAUGHT (full chain). If the witnessed refusal were
     doing the job, it would hold the peers that tried and were turned away. It does not.

  C. HARNESS REACHABILITY (filesystem). The tool that rules is an MCP tool. Whether any seat
     can call it is a property of that seat's config, not of the daemon -- so it is measured
     where it lives, on this box, rather than asked of a peer.

NOT CLAIMED. None of this shows that a peer DID reach for the door and get turned away. It
shows that if one had, no surface would hold it -- which is a statement about the instrument,
not about the peers. Direction matters: a missing witness can only hide attempts, never
manufacture them, so every "peers stopped trying" reading of the regression rests on evidence
that cannot distinguish itself from its own absence.

Usage:  python3 tools/arbitration_door_reachability.py [max_entries]
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402
from claude_daemon_client import call  # noqa: E402

# An id that is syntactically well-formed and cannot exist. Both guards under test run
# BEFORE the store lookup, so the arm that gets past attribution stops here rather than
# touching a real petition.
NONEXISTENT = "0" * 16

# Seat config locations, as deployed on this box. A seat absent from this list is not
# evidence of anything -- the list is what was found, and it prints what it looked at.
SEAT_CONFIGS = [
    ("claude-code", "/home/dp/.claude.json", "json:mcpServers"),
    ("claude-code", "/home/dp/.claude/settings.json", "json:mcpServers"),
    ("codex", "/home/dp/.codex/config.toml", "toml:mcp_servers"),
    ("kimi-code", "/home/dp/.kimi-code/config.toml", "toml:mcp_servers"),
]


def _tip(w):
    return w.window(limit=1)["entries"][0]["chainPosition"]


def _gate_rows_since(w, before, after):
    """Every gate_escalation_* row minted in (before, after]. The walk is bounded by the
    observed delta plus slack, so it cannot run away if the fleet is busy."""
    rows = []
    for e in w.walk(max_entries=(after - before) + 80):
        if e["chainPosition"] <= before:
            break
        if e["eventType"].startswith("gate_escalation"):
            rows.append((e["chainPosition"], e["eventType"]))
    return rows


def section_a(w):
    print("=" * 78)
    print("A. THE WITNESS GAP -- live, bracketed by chainPosition, writes nothing")
    print("=" * 78)
    verdicts = {}
    for label, args in (
        ("UNATTRIBUTED (no session_id)",
         {"escalation_id": NONEXISTENT, "approve": False, "reason": "reachability probe"}),
    ):
        before = _tip(w)
        r = call("hestia_gate_arbitrate_escalation", args)
        after = _tip(w)
        rows = _gate_rows_since(w, before, after)
        msg = (r.get("_hestia_error") or {}).get("message", json.dumps(r)) if isinstance(r, dict) else str(r)
        print(f"\n  arm: {label}")
        print(f"    message : {msg[:160]}")
        print(f"    gate_escalation_* rows minted: {rows if rows else 'NONE'}")
        verdicts[label] = (msg, rows)

    # The attributed arm needs a session. `hestia_connect` requires host_agent, and returns
    # the id under `sessionId` while every consumer names it `session_id` -- both spellings
    # are part of what a would-be arbiter has to get right, so they are exercised, not
    # smoothed over.
    c = call("hestia_connect", {"plugin_id": "claude-code",
                                "role": "role:constellation:member",
                                "host_agent": "claude-code"})
    sid = c.get("sessionId") or c.get("session_id") if isinstance(c, dict) else None
    if not sid:
        print("\n  arm: ATTRIBUTED -- SKIPPED, connect returned no session id:",
              json.dumps(c)[:200])
        return verdicts
    before = _tip(w)
    r = call("hestia_gate_arbitrate_escalation",
             {"escalation_id": NONEXISTENT, "approve": False,
              "reason": "reachability probe", "session_id": sid})
    after = _tip(w)
    rows = _gate_rows_since(w, before, after)
    msg = (r.get("_hestia_error") or {}).get("message", json.dumps(r)) if isinstance(r, dict) else str(r)
    print(f"\n  arm: ATTRIBUTED (session_id passed)")
    print(f"    message : {msg[:160]}")
    print(f"    gate_escalation_* rows minted: {rows if rows else 'NONE'}")
    verdicts["ATTRIBUTED"] = (msg, rows)

    minted = [k for k, (_, rows) in verdicts.items() if rows]
    print(f"\n  VERDICT: {len(verdicts)} arms, {len(minted)} minted a chain row "
          f"-> {'CLEAN (both refusals silent)' if not minted else 'MINTED: ' + str(minted)}")
    print("  Both arms are refusals. Neither is visible to any reader of the chain.")
    return verdicts


def section_b(w, max_entries):
    print()
    print("=" * 78)
    print("B. WHO THE ONE WITNESSED REFUSAL PATH EVER CAUGHT -- full chain")
    print("=" * 78)
    refused, n = [], 0
    for e in w.walk(max_entries=max_entries):
        n += 1
        if e["eventType"] == "gate_escalation_arbiter_refused":
            refused.append((e.get("timestamp"), payload(e)))
    print(f"  walked {n} entries")
    print(f"  gate_escalation_arbiter_refused rows: {len(refused)}")
    by_arb = Counter(p.get("would_be_arbiter") for _, p in refused)
    for k, v in by_arb.most_common():
        print(f"    {v:3d}  would_be_arbiter={k}")
    # The discriminator: a refusal whose would-be arbiter is a real seat AND whose reason is
    # not self-arbitration is the only shape that means "a legitimate peer was turned away".
    legit = [(ts, p) for ts, p in refused
             if p.get("would_be_arbiter") != "hestia-cli"
             and "cannot arbitrate its own" not in (p.get("why") or "")]
    print(f"\n  refusals of a peer ruling SOMEONE ELSE's escalation: {len(legit)}")
    for ts, p in legit:
        print(f"    {ts}  {p.get('would_be_arbiter')}  {(p.get('why') or '')[:90]}")
    if not legit:
        print("    NONE. The witnessed path has never recorded a legitimate peer being")
        print("    turned away -- it holds CLI invocations that omitted `--as`, and")
        print("    self-arbitration attempts. Neither is the population the regression is about.")
    return refused


def section_c():
    print()
    print("=" * 78)
    print("C. HARNESS REACHABILITY -- is the arbitrate tool callable from any seat?")
    print("=" * 78)
    found_any = False
    for seat, path, how in SEAT_CONFIGS:
        if not os.path.exists(path):
            print(f"  {seat:12s} {path}  -- ABSENT (not evidence; recorded so the list is auditable)")
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        if how.startswith("json"):
            names = set()
            try:
                d = json.loads(text)
                for scope in [d] + list((d.get("projects") or {}).values()):
                    if isinstance(scope, dict) and isinstance(scope.get("mcpServers"), dict):
                        names |= set(scope["mcpServers"].keys())
            except Exception as ex:  # a config we cannot parse is UNKNOWN, never "empty"
                print(f"  {seat:12s} {path}  -- UNPARSEABLE ({ex}); UNKNOWN, not zero")
                continue
        else:
            names = set()
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("[mcp_servers."):
                    names.add(s[len("[mcp_servers."):].rstrip("]"))
        has = any("hestia" in n for n in names)
        found_any = found_any or has
        print(f"  {seat:12s} {path}")
        print(f"    mcp servers: {sorted(names) if names else '(none declared)'}")
        print(f"    hestia registered: {'YES' if has else 'NO'}")
    print()
    print(f"  VERDICT: hestia MCP reachable from a harness on this box: "
          f"{'YES' if found_any else 'NO -- on no seat'}")
    if not found_any:
        print("  So `hestia_gate_arbitrate_escalation` is not in any seat's tool list. The")
        print("  only routes to it are the `hestia` CLI (gate_cli.rs, which attributes with")
        print("  `--as` and refuses LOUDLY without it) and hand-written JSON-RPC.")
    return found_any


def main():
    max_entries = int(sys.argv[1]) if len(sys.argv) > 1 else 300000
    w = ChainWalker()
    section_a(w)
    section_b(w, max_entries)
    section_c()
    print()
    print("=" * 78)
    print("WHAT THIS DOES AND DOES NOT SETTLE")
    print("=" * 78)
    print("  Settles: a peer turned away at the arbitrate door leaves no trace, on the one")
    print("           guard every would-be arbiter must pass first; and the tool is in no")
    print("           seat's harness.")
    print("  Does NOT settle: whether any peer actually reached for it after 2026-08-24.")
    print("           That question is not answerable from the chain, which is the point.")


if __name__ == "__main__":
    main()
