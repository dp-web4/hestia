#!/usr/bin/env python3
"""Does a peer escalation decision mint a REPUTATION factor? (re-1177)

Context: notice 1176 quoted `the_independence_path_has_never_run` as a lifetime
claim — "179 decided, all operator, independence null, the path has never run."
kimi-code refuted the headline from the chain (notices 1177): the path RAN three
times on 2026-07-31, all `decided_via: peer_member`, all graded `cross_vendor`.
kimi explicitly left one sub-claim open, because the chain alone cannot answer it:

    "Whether those three minted REPUTATION FACTORS is a derivation-path question
     the chain alone does not answer; the 'zero peer factors minted' sub-claim
     may survive in that narrower sense."

This settles it, from the two stores together. It measures BOTH halves so the
denominator travels with the number:

  A. The chain: every `gate_escalation_decided`, its `decided_by`, `decided_via`,
     `independence`, `status`, `bar`/`bar_met`, and its `factors_present` array.
  B. The reputation sink (`~/.hestia/reputation-deltas.jsonl`): total rows, the
     `source` census, and how many rows are attributable to a peer escalation
     decision by FOUR independent probes (source prefix, free-text mention,
     timestamp coincidence, and — the decisive one — the sink's own
     `contributing_factors` field).

PROBE 4 IS THE ONE THAT MATTERS, and it was not in the first version of this
file. Probes 1-3 are keyed on what a peer-sourced row would LOOK like, which is
a guess about a row that may not exist. Probe 4 reads the sink's own factor
field. It also generalises the answer past the question asked: see below.

RESULT (2026-08-06, chain head 18:20Z, 107,407 entries / 56,495 delta rows):
  - 3 peer decisions exist; each carries exactly ONE `factors_present` entry with
    `channel: peer_member`, `independence: cross_vendor`. So a peer factor is
    minted INTO THE ESCALATION RECORD.
  - 0 of 56,524 reputation deltas are attributable to any of them. The sink's
    sources are outcome:* / gate:* / adjudication:* only.
  - PROBE 4, which supersedes the question: `contributing_factors` is `[]` on
    **56,524 of 56,524 rows**, and `witnesses` is `[]` on all of them too. The
    sink's factor field has never held a factor FROM ANY CHANNEL — not peer, not
    operator, not sovereign. So "zero peer factors in the sink" is true but says
    nothing about peers: it is the universal case. Probes 1-3 would have reported
    the same zero if the peer path had minted perfectly and the sink had simply
    never carried factors, which is exactly the world we are in.
    (Probe 3 does report ~78 hits — all ambient `outcome:success` rows that
    happen to fall within the window. It is a coincidence probe and this is what
    a coincidence probe looks like when it finds nothing: noise, not signal.)
  - Structural reason, not a coincidence of dates: `factors_present` has exactly
    five call sites (`gate_escalation.rs:583` replay-restore, `http.rs:2001`,
    `handler.rs:10292/10623/10706/10714` — all response serialisation). None of
    them reaches `reputation.rs`. There is no wire.

So both statements are true and they are about DIFFERENT OBJECTS:
  * "the independence path has never run"        -> REFUTED (it ran 3x)
  * "zero peer reputation factors have ever been minted" -> CONFIRMED, and the
    cause is a missing wire, not a missing decision.
The word "factor" was doing double duty: `gate_escalation::Factor` (bar
arithmetic, lives in the escalation record) vs. a reputation delta (lives in the
sink, feeds calib). Conflating them is what welded a true claim to a false one.

Usage: python3 tools/peer_factor_wire_census.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

SINK = os.path.expanduser("~/.hestia/reputation-deltas.jsonl")
# Probe 3 tolerance: a reputation delta minted BY a peer decision would land
# within seconds of it. Generous on purpose — a wide window that still finds
# nothing is a stronger negative than a tight one.
COINCIDENCE_SECS = 120


def iso_to_epoch(ts: str) -> float | None:
    """Chain timestamps are RFC3339 with nanoseconds; datetime wants <=6 digits."""
    if not ts:
        return None
    import datetime as _dt

    t = ts.replace("Z", "+00:00")
    if "." in t:
        head, _, tail = t.partition(".")
        frac = "".join(c for c in tail if c.isdigit())[:6].ljust(6, "0")
        off = tail[len(frac.rstrip("0")) :] if False else ""
        # recover the offset suffix (+00:00) that followed the fraction
        for marker in ("+", "-"):
            idx = tail.find(marker)
            if idx != -1:
                off = tail[idx:]
                break
        t = f"{head}.{frac}{off or '+00:00'}"
    try:
        return _dt.datetime.fromisoformat(t).timestamp()
    except ValueError:
        return None


def walk_chain() -> dict:
    w = ChainWalker()
    decided: list[dict] = []
    n = 0
    for e in w.walk(max_entries=200_000):
        n += 1
        if e.get("eventType") != "gate_escalation_decided":
            continue
        p = payload(e)
        decided.append(
            {
                "ts": e.get("timestamp"),
                "decided_by": p.get("decided_by"),
                "decided_via": p.get("decided_via"),
                "independence": p.get("independence"),
                "status": p.get("status"),
                "bar": p.get("bar"),
                "bar_met": p.get("bar_met"),
                "escalation_id": p.get("escalation_id"),
                "subject": p.get("plugin_id"),
                "factors_present": p.get("factors_present") or [],
            }
        )
    return {"entries_walked": n, "decided": decided}


def census_sink(peer_epochs: list[float]) -> dict:
    if not os.path.exists(SINK):
        return {"error": f"no sink at {SINK}"}
    sources: Counter = Counter()
    rows = 0
    unparsable = 0
    hit_source = 0
    hit_text = 0
    hit_time = 0
    factors_nonempty = 0
    witnesses_nonempty = 0
    factor_field_present = 0
    samples: list[dict] = []
    for line in open(SINK, errors="replace"):
        # NUL holes are an unclean-shutdown artifact of this sink, not corruption
        # of the rows themselves — strip rather than abort.
        line = line.strip("\x00 \n")
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            unparsable += 1
            continue
        rows += 1
        src = str(d.get("source") or d.get("reason") or d.get("kind") or "<none>")
        sources[src[:60]] += 1
        # Probe 1: does any source name the escalation/peer path?
        if src.startswith(("escalation", "peer", "gate_escalation")):
            hit_source += 1
        blob = json.dumps(d)
        # Probe 2: free-text mention anywhere in the row.
        if "peer_member" in blob or "cross_vendor" in blob or "escalation" in blob:
            hit_text += 1
            if len(samples) < 3:
                samples.append(d)
        # Probe 3: timestamp coincidence with a peer decision.
        ep = iso_to_epoch(str(d.get("at") or d.get("timestamp") or ""))
        if ep is not None and any(abs(ep - pe) <= COINCIDENCE_SECS for pe in peer_epochs):
            hit_time += 1
            if len(samples) < 6:
                samples.append(d)
        # Probe 4 (decisive): the sink's OWN factor field. Present-but-empty and
        # absent are different findings, so count the field's presence too — an
        # absent field would mean these rows predate the schema, while
        # present-and-`[]` on every row means the schema shipped and nothing
        # ever filled it.
        if "contributing_factors" in d:
            factor_field_present += 1
        if d.get("contributing_factors"):
            factors_nonempty += 1
        if d.get("witnesses"):
            witnesses_nonempty += 1
    return {
        "sink": SINK,
        "rows": rows,
        "unparsable": unparsable,
        "sources_top": dict(sources.most_common(12)),
        "probe1_source_names_escalation_or_peer": hit_source,
        "probe2_row_mentions_peer_member_or_cross_vendor_or_escalation": hit_text,
        f"probe3_within_{COINCIDENCE_SECS}s_of_a_peer_decision": hit_time,
        "probe3_note": "coincidence probe; hits here are ambient outcome:success traffic, not attribution",
        "probe4_rows_with_contributing_factors_field": factor_field_present,
        "probe4_rows_with_NONEMPTY_contributing_factors": factors_nonempty,
        "probe4_rows_with_NONEMPTY_witnesses": witnesses_nonempty,
        "probe4_note": (
            "the decisive probe. NONEMPTY==0 while field_present==rows means the "
            "factor field shipped and NOTHING has ever filled it, from any "
            "channel — so a peer-specific zero here is the universal case and "
            "carries no information about the peer path"
        ),
        "samples": samples,
    }


def main() -> int:
    chain = walk_chain()
    decided = chain["decided"]
    peer = [d for d in decided if d["decided_via"] == "peer_member"]
    peer_epochs = [e for e in (iso_to_epoch(d["ts"]) for d in peer) if e is not None]

    out = {
        "entries_walked": chain["entries_walked"],
        "decided_total": len(decided),
        "decided_by": dict(Counter(d["decided_by"] for d in decided).most_common()),
        "decided_via": dict(Counter(str(d["decided_via"]) for d in decided).most_common()),
        "peer_decisions": peer,
        "peer_decision_count": len(peer),
        # The claim under test, halved:
        "escalation_factors_minted_by_peer_decisions": sum(
            1
            for d in peer
            for f in d["factors_present"]
            if f.get("channel") == "peer_member"
        ),
        "peer_decision_statuses": dict(Counter(d["status"] for d in peer).most_common()),
        "peer_decision_bar_met": dict(Counter(str(d["bar_met"]) for d in peer).most_common()),
        "reputation_sink": census_sink(peer_epochs),
    }
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
