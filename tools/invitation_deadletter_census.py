#!/usr/bin/env python3
"""Where did the peer INVITATIONS actually go? — the dead-letter share of `invited_peers`.

`resolve_invitation` (handler.rs) builds the invitation pool from
`member_registry.iter_sorted()` — EVERY id that ever connected — ranks it by
ACT-liveness (`actor_liveness`, read from the member's own chain acts), and takes the
first `MAX_INVITED_PEERS`. The comment says the choice is deliberate and fails closed:
*"an unmappable candidate is invited rather than dropped ... an invitation is cheap to
over-issue and expensive to under-issue."*

That reasoning holds for a QUIET member. It does not hold for an id with no mailbox
reader at all. The daemon already draws exactly that line elsewhere — `recipient_liveness`
calls a member with no `member_inbox_touch` row `unknown` and names it *"the dead-letter
class, and only this"* — but the invitation pool never consults it. Since `plugin_id` is
caller-supplied at connect (any probe mints a member), the registry accumulates probe
residue, and every escalation re-invites all of it.

Why that is not merely untidy: `peer_participation()` retains the peer conjunct AS
EVIDENCE — `invited` vs who answered, so that "three invited seats that all declined to
look is a finding". An invited id whose mailbox nobody reads lands in `absent` exactly
like a peer who read the ask and ignored it. The statistic the invitation exists to
produce is the one the residue corrupts.

TWO POPULATIONS, kept apart, because they answer different questions and only the first
is complete:

  A. CHAIN (complete over opened escalations): who was invited, at what act-liveness,
     how many were passed over. Every opened escalation is here whether or not anyone
     answered, so shares computed here have an honest denominator.
  B. LEDGER (`hestia_member_unanswered`, owed_to_me): doorbell class per recipient —
     `unknown` = no `member_inbox_touch` row ever = no watcher ever read that mailbox.
     This population is SURVIVORSHIP-BIASED by construction: a notice that was answered
     leaves it. Its counts are therefore NOT a rate over invitations; it is used here
     only as the per-ID doorbell lookup, and any id it cannot classify is reported as
     `doorbell:unmeasured` rather than folded into either side.

The join is per-ID, so B's bias does not leak into A's shares: an id is dead-lettered or
not independently of how many notices to it are outstanding.

Usage: python3 tools/invitation_deadletter_census.py [MAX_ENTRIES] [--json]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from chain_walk import ChainWalker, payload

MAX = 200_000
JSON_OUT = False
DOORBELL_PATH: str | None = None
_argv = sys.argv[1:]
while _argv:
    a = _argv.pop(0)
    if a == "--json":
        JSON_OUT = True
    elif a == "--doorbell":
        DOORBELL_PATH = _argv.pop(0)
    else:
        MAX = int(a)


def doorbell_classes(path: str | None) -> tuple[dict[str, str], str]:
    """Per-id doorbell class, read from a mesh wake primer. Lookup table only.

    Read from the primer rather than by calling `hestia_member_unanswered` for two
    reasons: that tool needs an attributed caller, so this instrument would have to
    `hestia_connect` and MINT a resident session — the very #320 leak the neighbouring
    instrument measures — and the primer already carries the daemon's own verdict,
    stamped. The classes are the daemon's, not this tool's.
    """
    import glob
    import os

    if path is None:
        cands = sorted(
            glob.glob(os.path.expanduser("~/.claude/hestia-mesh-primers/notice-*.json")),
            key=os.path.getmtime,
        )
        if not cands:
            return {}, "no primer found"
        path = cands[-1]
    try:
        with open(path) as fh:
            d = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"# doorbell lookup unavailable: {e}", file=sys.stderr)
        return {}, f"unavailable: {e}"
    out: dict[str, str] = {}
    for row in d.get("unanswered", {}).get("owed_to_me", []):
        to, lv = row.get("to_plugin"), row.get("recipient_liveness")
        if to and lv:
            out[to] = lv
    return out, path


w = ChainWalker()
door, door_src = doorbell_classes(DOORBELL_PATH)

opened: dict[str, dict] = {}
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    if e.get("eventType") != "gate_escalation_opened":
        continue
    p = payload(e)
    esc = p.get("escalation_id") or p.get("id")
    if not esc or esc in opened:
        continue
    opened[esc] = p

with_invites = {k: v for k, v in opened.items() if v.get("invited_peers")}

invite_rows: Counter = Counter()          # id -> how many escalations invited it
liveness_at_invite: Counter = Counter()   # (id, act-liveness recorded on the entry)
withheld_rows: Counter = Counter()
passed_over_rows: Counter = Counter()
per_esc_reachable: Counter = Counter()    # how many NON-dead-letter invitees per escalation

for esc, p in with_invites.items():
    peers = p.get("invited_peers") or []
    ev = {d.get("peer"): d.get("liveness_at_invite") for d in (p.get("invitation_evidence") or []) if isinstance(d, dict)}
    reachable = 0
    for pid in peers:
        invite_rows[pid] += 1
        liveness_at_invite[(pid, ev.get(pid, "not-recorded"))] += 1
        if door.get(pid, "unmeasured") != "unknown":
            reachable += 1
    per_esc_reachable[reachable] += 1
    for d in p.get("invitation_withheld") or []:
        if isinstance(d, dict) and d.get("peer"):
            withheld_rows[d["peer"]] += 1
    for d in p.get("invitation_passed_over") or []:
        if isinstance(d, dict) and d.get("peer"):
            passed_over_rows[d["peer"]] += 1

total_rows = sum(invite_rows.values())
dead = sum(c for pid, c in invite_rows.items() if door.get(pid) == "unknown")
unmeasured = sum(c for pid, c in invite_rows.items() if pid not in door)

result = {
    "chain_entries_walked": n,
    "escalations_opened_seen": len(opened),
    "escalations_carrying_invited_peers": len(with_invites),
    "invitation_rows": total_rows,
    "invitation_rows_to_dead_letter_ids": dead,
    "invitation_rows_doorbell_unmeasured": unmeasured,
    "dead_letter_share_of_measured": (
        round(dead / (total_rows - unmeasured), 4) if total_rows - unmeasured else None
    ),
    "invited_id_x_escalations": dict(invite_rows.most_common()),
    "doorbell_class_per_id": {pid: door.get(pid, "unmeasured") for pid in invite_rows},
    "act_liveness_at_invite": {f"{pid}:{lv}": c for (pid, lv), c in liveness_at_invite.most_common()},
    "reachable_invitees_per_escalation": dict(sorted(per_esc_reachable.items())),
    "withheld_rows": dict(withheld_rows.most_common()),
    "passed_over_rows": dict(passed_over_rows.most_common()),
    "doorbell_source": door_src,
    "scope": {
        "chain": "complete over opened escalations within the walked window",
        "doorbell": "per-ID lookup from this seat's unanswered ledger (survivorship-biased "
                    "as a population; used only as an id->class table)",
        "unmeasured": "invited id this seat has no outstanding notice to — class unknown "
                      "to THIS instrument, counted separately and excluded from the share",
    },
}

if JSON_OUT:
    print(json.dumps(result, indent=2))
else:
    for k, v in result.items():
        if isinstance(v, dict) and k != "scope":
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        elif k == "scope":
            print("scope:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"{k}: {v}")
