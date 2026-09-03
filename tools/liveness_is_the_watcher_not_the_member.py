#!/usr/bin/env python3
"""`recipient_liveness: live` certifies the WATCHER, not the member — measured, two-sided.

THE CLAIM. `peer_participation()` (gate_escalation.rs) exists to keep "a seat that saw the
ask and declined" apart from "a seat that never saw it". It does that with three
exclusions, all of them keyed on the MAILBOX: `invited_without_reader` (no
`member_inbox_touch` row, or one older than the escalation's TTL) and
`invited_reader_unknown` (the read itself failed). Everything else falls through into
`absent`, which is published as conduct evidence about a peer.

`member_inbox_touch` is written by `touch_inbox`, called from `drain_member` and
`peek_member` (storage/inbox.rs), keyed on `to_plugin` — i.e. on WHOEVER DRAINS THE
MAILBOX. On this mesh that is `hestia-watch-member.sh`, which drains the member's inbox
into a primer and only THEN fires the member's CLI. The touch is recorded before the
member runs, and is recorded identically when the member never runs at all.

So the freshness of `last_inbox_touch` is a property of the watcher's poll loop. A seat
whose agent is dead — out of credits, egress-blocked, crashed — keeps a `last_touch`
seconds old for as long as its watcher is up, reads `live`, is excluded from none of the
three, and lands in `absent`.

WHY THE EXISTING FIX DOES NOT COVER THIS. The 2026-08-18 window fix
(`a_stale_mailbox_row_is_not_counted_as_a_peer_that_declined`, handler.rs) closed the
STALE half: a `last_touch` predating the TTL now counts as readerless. Its positive
control is *"a second seat — `kimi-code`, mailbox read seconds ago"*, admitted as a seat
that could have read the ask. That control is the assumption this driver refutes. The
window cannot reach a touch that is 30 seconds old, and by affirmatively crediting fresh
touches it makes the remaining half MORE confident, not less.

THE DISCRIMINATOR ALREADY EXISTS IN THE DAEMON. `actor_liveness` (handler.rs) reads the
member's own chain ACTS — `outcome`, `policy_decision`, `adjudication`, `appeal` — which
are written only when the member actually runs; a watcher poll writes none of them. The
invitation pool already ranks candidates by it. The conduct question does not consult it.
This driver reports both signals side by side so the divergence is visible per seat.

TWO-SIDED, because a one-sided readout here is worthless: a predicate that answered
"dead" for everyone would satisfy the headline just as well. So every seat is reported,
and the run is only interesting if some seats diverge and others do not.

READING THE OUTPUT. `MAILBOX` is the daemon's own `recipient_liveness` verbatim. `ACTS`
is the age of the newest chain act attributable to that plugin inside the walked window.
`DIVERGENT` marks the class this driver exists to find: mailbox says `live`, acts say the
member has not moved inside the escalation TTL. Those are the seats that `absent` would
score as having declined.

CAVEATS, stated because they bound the numbers rather than decorate them:
  * The chain read is a HOP BUDGET, not a time window. Its left edge drifts as the chain
    grows, so the SPAN actually covered is printed and every act-age is relative to it. A
    seat reported `no act in window` may simply predate the budget — that is why the span
    is printed rather than assumed, and why `--max` is a knob you are expected to move.
  * `owed_to_me` is survivorship-biased by construction (a notice that was answered is
    not unanswered), so the recipient set here is "seats I am waiting on", not the
    registry. That is the right population for the conduct question and the wrong one for
    a registry census; do not quote it as the latter.
  * MAILBOX liveness is read NOW, while the acts are read over the window. A seat that
    died five minutes ago is correctly divergent; one that died five seconds ago may not
    have aged out of the act window yet.

Usage:  python3 tools/liveness_is_the_watcher_not_the_member.py [--max 4000] [--ttl 3600]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import pathlib
import sys

# The escalation TTL every `sovereign_plus_peer` escalation this daemon opens carries.
# It is the deadline the conduct question is asked against, so it is the right yardstick
# for "could this seat have answered?" — not an arbitrary staleness constant.
DEFAULT_TTL_SECS = 3600

# handler.rs `actor_liveness::ACT_TYPES`, verbatim. Kept as a literal WITH this note
# rather than silently: if the daemon's list grows, this readout under-reports member
# life, which is the direction that would manufacture a false divergence. Re-check it
# against handler.rs before quoting a number from a new daemon build.
ACT_TYPES = ("outcome", "policy_decision", "adjudication", "appeal")

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_ts(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def mailbox_side() -> tuple[dict, str | None]:
    """Per-recipient `recipient_liveness` for the seats I am waiting on, plus MY id.

    The caller's own seat is returned so it can be added to the table as a POSITIVE
    CONTROL. `owed_to_me` structurally excludes me — I do not wait on myself — so
    without it every row in the table is a seat that is failing to answer, and a
    predicate stuck at "divergent" would look identical to a finding.
    """
    mesh = _load(REPO / "plugins" / "member-mesh" / "hestia-mesh.py", "hestia_mesh")
    handle, session = mesh.connect()
    out = mesh.rpc(handle, "hestia_member_unanswered",
                   {"session_id": session, "older_than_secs": 0})
    if not isinstance(out, dict) or "_hestia_error" in out:
        raise SystemExit(f"member_unanswered failed: {json.dumps(out)[:400]}")
    seats: dict[str, dict] = {}
    for row in out.get("owed_to_me") or []:
        who = row.get("to_plugin")
        if not who:
            continue
        rec = seats.setdefault(who, {"waiting_on": 0})
        rec["waiting_on"] += 1
        rec["liveness"] = row.get("recipient_liveness")
        ev = row.get("recipient_liveness_evidence") or {}
        if isinstance(ev, dict):
            rec["last_inbox_touch"] = ev.get("last_inbox_touch")
            rec["mailbox_reads"] = ev.get("mailbox_reads")
    return seats, out.get("plugin_id")


def acts_side(max_entries: int) -> tuple[dict, dict]:
    """Newest chain act per plugin, plus the SPAN the walk actually covered."""
    cw = _load(REPO / "tools" / "chain_walk.py", "chain_walk")
    walker = cw.ChainWalker()
    newest: dict[str, dt.datetime] = {}
    span_lo: dt.datetime | None = None
    span_hi: dt.datetime | None = None
    seen = 0
    act_rows = 0
    # The feed is camelCase (`eventType`/`eventData`) and `eventData` has TWO shapes.
    # An earlier cut of this driver read `event_type`/`event_data`, got None for every
    # row, and printed "none in window" for all ten seats — a clean table from a dead
    # instrument, which is trap 3 in chain_walk.py's own docstring and the reason
    # `payload()` exists. Use the wrapper; do not re-hand-roll the extraction.
    for entry in walker.walk(max_entries=max_entries):
        seen += 1
        ts = _parse_ts(str(entry.get("timestamp") or ""))
        if ts is not None:
            span_lo = ts if span_lo is None or ts < span_lo else span_lo
            span_hi = ts if span_hi is None or ts > span_hi else span_hi
        if entry.get("eventType") not in ACT_TYPES:
            continue
        data = cw.payload(entry)
        adjudicated_by = data.get("adjudicated_by")
        who = (data.get("plugin_id") or data.get("adjudicator")
               or (adjudicated_by.get("plugin_id")
                   if isinstance(adjudicated_by, dict) else None))
        if not isinstance(who, str) or ts is None:
            continue
        act_rows += 1
        if who not in newest or ts > newest[who]:
            newest[who] = ts
    return newest, {"entries_walked": seen, "act_rows": act_rows,
                    "span_lo": span_lo, "span_hi": span_hi}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max", type=int, default=4000,
                    help="chain hop budget (a BUDGET, not a window — the span is printed)")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECS,
                    help="escalation TTL in seconds; the deadline acts are judged against")
    args = ap.parse_args()

    seats, me = mailbox_side()
    newest, span = acts_side(args.max)

    # The control row. My own mailbox is drained by my own watcher exactly as codex's
    # is by its watcher, so `live` is worth the same here as there — the difference is
    # that I am demonstrably running, which is what makes the row a control and not
    # another instance of the claim.
    if me and me not in seats:
        seats[me] = {"waiting_on": 0, "liveness": "live",
                     "last_inbox_touch": None, "mailbox_reads": None,
                     "_control": True}
    now = dt.datetime.now(dt.timezone.utc)

    # A dead extractor makes every live seat look divergent. Refuse to print the
    # table at all rather than publish that shape as a finding.
    if not newest:
        print(f"INSTRUMENT DEAD: walked {span['entries_walked']} entries and attributed "
              f"ZERO acts to any plugin. Every seat would read 'none in window'. "
              f"Check ACT_TYPES against handler.rs and the payload shape before "
              f"believing any verdict below.", file=sys.stderr)
        return 2

    lo, hi = span["span_lo"], span["span_hi"]
    print(f"chain: walked {span['entries_walked']} entries; SPAN "
          f"{lo.isoformat() if lo else '?'} .. {hi.isoformat() if hi else '?'}")
    if lo is not None:
        covered = (now - lo).total_seconds()
        print(f"       = {covered/3600:.1f}h of history. An act older than this is "
              f"INVISIBLE here, not absent.")
    print(f"       {span['act_rows']} of them are member ACTS attributed to a plugin "
          f"across {len(newest)} distinct seats — the instrument's own liveness check.")
    print(f"ttl: {args.ttl}s — the deadline 'could this seat have answered?' is asked against\n")

    hdr = f"{'seat':<22} {'MAILBOX':<10} {'touch age':>10} {'reads':>8} {'ACTS':>14}  verdict"
    print(hdr)
    print("-" * len(hdr))

    divergent, agreeing = [], []
    for who in sorted(seats):
        rec = seats[who]
        liveness = rec.get("liveness") or "?"
        touch = _parse_ts(str(rec.get("last_inbox_touch") or ""))
        touch_age = f"{(now - touch).total_seconds():.0f}s" if touch else "-"
        reads = rec.get("mailbox_reads")
        act = newest.get(who)
        if act is None:
            act_s, acted_recently = "none in window", False
        else:
            age = (now - act).total_seconds()
            act_s, acted_recently = f"{age/3600:.1f}h ago", age <= args.ttl

        # The class this driver exists to find: the mailbox says the seat is reading,
        # the chain says the member has not acted inside the deadline it is being
        # judged against. `absent` would publish this as "saw the ask and declined".
        if liveness == "live" and not acted_recently:
            verdict, bucket = "DIVERGENT — absent would call this declined", divergent
        elif liveness == "live":
            verdict, bucket = "agrees (live and acting)", agreeing
        else:
            verdict, bucket = f"not live ({liveness}) — already excluded", agreeing
        bucket.append(who)
        label = f"{who} (me)" if rec.get("_control") else who
        print(f"{label:<22} {liveness:<10} {touch_age:>10} "
              f"{reads if reads is not None else '-':>8} {act_s:>14}  {verdict}")

    print()
    print(f"DIVERGENT: {len(divergent)} of {len(seats)} seats I am waiting on "
          f"— {', '.join(divergent) if divergent else '(none)'}")
    print(f"AGREEING : {len(agreeing)} — the two-sided control; a run where every seat "
          f"is divergent is a broken instrument, not a finding.")
    if divergent:
        owed = sum(seats[w]["waiting_on"] for w in divergent)
        print(f"\n{owed} unanswered notices are addressed to seats that read `live` and "
              f"have not acted inside the TTL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
