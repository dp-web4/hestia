#!/usr/bin/env python3
"""How much of the act does a peer reviewer actually get to see?

MOTIVATION (2026-08-15). Two peers — codex (notice 2557) and kimi-code — independently
DISSENTED on escalation abe4db493872dfa7 with the same argument: the pointer they were
handed truncates before the called function, its inputs, and its assertions, so the
"read-only, decision-only" characterisation is a CLAIM they cannot inspect. Neither peer
was wrong about their row. The question this probe asks is whether they were looking at a
per-case accident or at a bound that applies to the population.

TWO NUMBERS, TWO SURFACES, SAME ACT:

  * the PEER surface. An auto-opened escalation's `stated_reason` is not a rationale — the
    daemon comment at the render site says so explicitly ("carries the ATTEMPTED ACT here,
    not a rationale, because the member did not choose to escalate"). The hook composes it
    as `f"{tool}: {' '.join(cmd.split())[:220]}"` plus a " …" marker. `stated_detail` is a
    CONSTANT: the same boilerplate sentence on every auto-opened row. So the peer's entire
    inspectable account of the act is 220 whitespace-collapsed characters.

  * the AUDIT surface. The deny's own chain entry carries `attempted`, cut at
    ATTEMPTED_MAX = 400 chars.

HYPOTHESIS, AND HOW IT CAME OUT (2026-08-15, recorded because the error had a direction):
predicted gap 220-vs-400 — the reviewer shown less than the auditor. Measured, the gap is
**220-vs-nothing**. The refusal class that reaches peers (gate-self / governance-write) is
decided hook-side and never recorded as a `policy_decision`, so no 400-char copy exists:
this seat opened 89 escalations against 14 witnessed denies. The truncated reason is the
only copy of the act on the chain. Only 1 of 19 truncated rows paired to an audit row, and
that 1 is the exception rather than the instrument failing.

Also refuted, in the flattering direction: the peer loop is NOT structurally unmeetable.
19/78 auto-opened rows truncate (24.4%), 5/21 under `sovereign_plus_peer`. Three quarters
fit. The defect is selective — it bites long acts, i.e. scripts, i.e. exactly the class
whose character cannot be read off its opening line.

And the bound is per-SEAT, not per-surface: longest peer-visible reason is 228 chars for
claude-code against 412 for kimi-code and codex. How inspectable an act is depends on who
performed it.

WHAT IS MEASURED (no writes; `hestia_query_history` reads only):
  1. population of `gate_escalation_opened` rows, and how many are auto-opened (the
     constant `detail` is the discriminator — a member-stated why is a different shape).
  2. truncation rate: what share of peer-visible reasons hit the 220 bound.
  3. the SAME acts on the audit surface: paired `attempted` length, so the gap between
     what the record holds and what the reviewer is shown is a number, not an intuition.
  4. split by `bar`, because the defect only bites where a peer factor is REQUIRED.

Run:  python3 tools/claude_corroborate_surface_width_probe.py [--max N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_walk import ChainWalker, payload  # noqa: E402

# The hook's cut, transcribed from the composer rather than inferred from the data — a
# bound read off its own output cannot distinguish "cut at 220" from "nothing longer".
PEER_CUT = 220
AUDIT_CUT = 400  # ATTEMPTED_MAX at the deny recorder
TRUNC_MARK = " …"

# The auto-open boilerplate. Matched on a distinctive prefix, not the whole sentence, so a
# reworded tail does not silently reclassify every auto-opened row as member-stated.
AUTO_DETAIL_PREFIX = "Auto-opened by the gate on a refused write"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=40000)
    args = ap.parse_args()

    w = ChainWalker()
    opens: list[dict] = []
    denies: list[dict] = []
    scanned = 0
    for e in w.walk(max_entries=args.max):
        scanned += 1
        et = e.get("eventType")
        if et == "gate_escalation_opened":
            opens.append(payload(e))
        # `policy_decision` is the deny recorder. Named from a census of the live feed,
        # NOT guessed: a first pass of this probe guessed ("gate_decision", "gate_deny",
        # "outcome") and paired 0/19, which reads as "the audit record holds no more than
        # the peer sees" — the opposite of the truth. The zero indicted the instrument.
        elif et == "policy_decision":
            p = payload(e)
            if isinstance(p.get("attempted"), str):
                denies.append(p)

    print(f"scanned {scanned} entries; {len(opens)} gate_escalation_opened; "
          f"{len(denies)} rows carrying `attempted`")

    if not opens:
        print("NO OPENS IN WINDOW — the zero indicts the window, not the surface.")
        return 1

    auto = [o for o in opens
            if isinstance(o.get("stated_detail"), str)
            and o["stated_detail"].startswith(AUTO_DETAIL_PREFIX)]
    stated = [o for o in opens if o not in auto]
    print(f"\nauto-opened (gate composed the reason): {len(auto)}")
    print(f"member-stated why:                      {len(stated)}")

    # -- 2. truncation on the peer surface ------------------------------------
    def cut(o: dict) -> bool:
        r = o.get("stated_reason")
        return isinstance(r, str) and r.endswith(TRUNC_MARK)

    truncated = [o for o in auto if cut(o)]
    missing = [o for o in auto if not isinstance(o.get("stated_reason"), str)]
    print(f"\n-- peer surface (stated_reason, cut at {PEER_CUT}) --")
    print(f"truncated:        {len(truncated)}/{len(auto)}"
          f"  ({100.0 * len(truncated) / len(auto):.1f}% of auto-opened)")
    print(f"no reason at all: {len(missing)}")

    lens = sorted(len(o["stated_reason"]) for o in auto
                  if isinstance(o.get("stated_reason"), str))
    if lens:
        mid = lens[len(lens) // 2]
        print(f"reason length: min {lens[0]}  median {mid}  max {lens[-1]}")

    # WHOSE cut is 220? A reason LONGER than the composer's bound cannot have come
    # through this seat's composer, so the peer surface's width is a property of the
    # DENIED SEAT, not of the escalation surface. Split it rather than quote one bound
    # for a fleet that does not share it.
    over = [o for o in auto if isinstance(o.get("stated_reason"), str)
            and len(o["stated_reason"]) > PEER_CUT + len(TRUNC_MARK)]
    print(f"\n-- reasons WIDER than this seat's {PEER_CUT} bound: {len(over)} --")
    per_seat: Counter = Counter()
    per_seat_max: dict = {}
    for o in auto:
        r = o.get("stated_reason")
        if not isinstance(r, str):
            continue
        who = o.get("plugin_id") or "(unrecorded)"
        per_seat[who] += 1
        per_seat_max[who] = max(per_seat_max.get(who, 0), len(r))
    for who, n in per_seat.most_common():
        print(f"  {who:<20} n={n:<4} longest reason {per_seat_max[who]}")

    # -- 4. split by bar: where does the truncation actually cost a factor? ----
    print("\n-- truncated rows by bar (a peer factor is only REQUIRED under some) --")
    by_bar: Counter = Counter()
    trunc_by_bar: Counter = Counter()
    for o in auto:
        b = o.get("bar") or "(none recorded)"
        by_bar[b] += 1
        if cut(o):
            trunc_by_bar[b] += 1
    for b, n in by_bar.most_common():
        print(f"  {b:<24} {trunc_by_bar[b]:>4}/{n:<4} truncated")

    # -- 3. the audit surface, same acts ---------------------------------------
    # Pair by the reason's own text: the peer prefix must be a prefix of `attempted`
    # once both are whitespace-collapsed. Exact-prefix, so a near-match is NOT counted —
    # an unpaired row reads as unpaired, never as agreement.
    def body(reason: str) -> str:
        s = reason[: -len(TRUNC_MARK)] if reason.endswith(TRUNC_MARK) else reason
        _, _, rest = s.partition(": ")
        return " ".join((rest or s).split())

    att_index = [" ".join(d["attempted"].split()) for d in denies]
    paired = 0
    gaps: list[int] = []
    for o in truncated:
        b = body(o["stated_reason"])
        if len(b) < 40:
            continue
        for a in att_index:
            if a.startswith(b):
                paired += 1
                gaps.append(len(a) - len(b))
                break
    print(f"\n-- audit surface (attempted, cut at {AUDIT_CUT}) --")
    print(f"truncated peer rows paired to an audit row: {paired}/{len(truncated)}")
    if gaps:
        gaps.sort()
        print(f"extra characters the AUDIT record holds that the PEER was not shown: "
              f"min {gaps[0]}  median {gaps[len(gaps) // 2]}  max {gaps[-1]}")
    else:
        print("no pairs — cannot state the gap from this window; unmeasured, not zero.")

    # -- the specific row two peers dissented on -------------------------------
    print("\n-- the motivating row --")
    for o in opens:
        if str(o.get("escalation_id", "")).startswith("abe4db49"):
            print(json.dumps({k: o.get(k) for k in
                              ("escalation_id", "bar", "tool_name", "marker",
                               "stated_reason", "stated_detail")}, indent=2)[:1400])
            break
    else:
        print("abe4db49… not in window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
