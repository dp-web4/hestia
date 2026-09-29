#!/usr/bin/env python3
"""Fold `hestia_member_unanswered.owed_to_me` by recipient: who this seat's outbound
mail is addressed to, and how much of it can never be read.

Why this exists (issue #541, 2026-09-01 re-measurement): the invitation writer fills
`MAX_INVITED_PEERS = 8` slots from `member_registry`, which is minted from the
caller-supplied `plugin_id` at connect and has NO removal surface (`member_registry.rs`
exports get/len/is_empty/iter_sorted/load_members/attach_citizenship/
vouch_witnessing_key/ensure_member — nothing removes). So every id that ever connected
is a permanent invitation candidate, and every gate-auto-opened escalation mints one
`review_request` per slot under the ASKER's name. The dead ones come back to the asker
as `owed_to_me` rows that no watcher will ever drain.

The population is not fixed. `claudecode` (a mistyped `claude-code`, one factor ever)
first appears 2026-08-27T06:37:59Z and, sorting alphabetically inside the
Unknown/no-reader tier, took the slot `egress-drain` held until 2026-08-26T21:59:45Z.
One bare connect re-ordered the roster for every escalation since.

Usage:
    python3 tools/owed_to_me_residue_fold.py <unanswered.json>

where <unanswered.json> is the raw `hestia_member_unanswered` response (call it with
`older_than_secs: 0` so the window is the store's own 7-day TTL, not the 6h default).
Reads a file your OWN run wrote — `stat` it first (a stale fixed-name file is a false
measured value). Prints per-recipient totals, drained counts, invitation rows
(`#corroborate-or-dissent` pointers), first/last queued_at and the mailbox evidence the
daemon attached at send time. Stdlib only.
"""
import collections
import json
import sys


def fold(u):
    rows = u.get("owed_to_me", [])
    d = collections.defaultdict(list)
    for r in rows:
        d[r.get("to_plugin")].append(r)
    out = []
    for t, rs in sorted(d.items(), key=lambda kv: -len(kv[1])):
        q = sorted(r.get("queued_at", "") for r in rs)
        ev = rs[-1].get("recipient_liveness_evidence") or {}
        out.append({
            "to_plugin": t,
            "total": len(rs),
            "drained": sum(1 for r in rs if r.get("drained_at")),
            "invitations": sum(1 for r in rs if "#corroborate-or-dissent" in (r.get("pointer_uri") or "")),
            "first": q[0][:19] if q else "",
            "last": q[-1][:19] if q else "",
            "mailbox_reads": ev.get("mailbox_reads"),
            "last_inbox_touch": str(ev.get("last_inbox_touch", ""))[:19],
        })
    opens = set()
    for r in rows:
        p = r.get("pointer_uri") or ""
        if p.startswith("hestia://escalation/") and "#corroborate-or-dissent" in p:
            opens.add(p.split("/")[3].split("#")[0])
    # "Never drained" is the predicate, not "no mailbox reader": `codex-cli` carries
    # mailbox_reads=1 from a single 07-26 touch and has still drained 0 of 146 rows.
    # `hestia` is excluded — it is the daemon, not a peer, and its rows are replies a
    # session sent to a disposition (a dead route of a different kind).
    undrained = sum(x["total"] for x in out if x["drained"] == 0 and x["to_plugin"] != "hestia")
    return {"owed_to_me": len(rows), "distinct_invitation_opens": len(opens),
            "never_drained_rows": undrained,
            "never_drained_share": (undrained / len(rows)) if rows else None,
            "by_recipient": out}


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open(argv[1]) as f:
        u = json.load(f)
    res = fold(u)
    print("owed_to_me=%d  invitation-bearing opens=%d  rows to never-drained recipients=%d (%.1f%%)" % (
        res["owed_to_me"], res["distinct_invitation_opens"], res["never_drained_rows"],
        100 * (res["never_drained_share"] or 0)))
    print("%-34s %6s %8s %8s  %-19s %-19s %s" % ("to_plugin", "total", "drained", "invites", "first", "last", "reads"))
    for x in res["by_recipient"]:
        print("%-34s %6d %8d %8d  %-19s %-19s %s" % (
            x["to_plugin"], x["total"], x["drained"], x["invitations"], x["first"], x["last"], x["mailbox_reads"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
