#!/usr/bin/env python3
"""Does a spent permit belong to the session that earned it?

WHY THIS EXISTS. `claim()` matches an approval on `(plugin_id, marker)` and nothing
else. Its doc comment defends that key with a SAME-MEMBER argument:

    "a member lying about `marker` to spend its own approval on a different file
     gains nothing it did not already have."

That is sound while `plugin_id` names one actor. It is not an assumption about the
key, it is an assumption about the NAMESPACE the key is drawn from — and the
namespace has a hole in it. `_escalation_plugin_id()` falls back to the literal
`unattributed` for any agent session started outside the mesh launcher, so every
such session shares one claim key. The chain cannot tell them apart either:
`subject_instance_lct` is a real member LCT for a named plugin and NULL for this
bucket. So "its own approval" is unverifiable on 33% of escalations, by construction.

This joins each escalation event to the agent session that caused it, using the only
surface that still separates them — the transcripts — and asks whether any permit was
OPENED by one session and SPENT by another.

METHOD. The transcript records the assistant's `tool_use` block when the message is
emitted; the PreToolUse hook then runs and writes the chain event. So the causing
record lands shortly BEFORE its chain event — measured on this feed at a very tight
-0.113s..-0.133s, while the nearest unrelated record is seconds to minutes away.
Match BACKWARD and take the nearest.

(Direction matters and is easy to get backwards: a forward match scores 100% unjoined,
which reads like "no data" rather than "wrong sign". Any tightening of the tolerance
here must be checked against the printed offset, not assumed.)

THE CONTROL IS NOT OPTIONAL. Attributed (`claude-code`) permits run through the same
join. They carry a real `subject_instance_lct`, so a cross-session verdict there would
mean the join is matching on ambient activity rather than cause, and the unattributed
result would be worthless. Report both arms always; the attributed arm is the oracle.

A cross-session spend requires the two sessions to overlap in the permit's TTL, so
absence is a bound on THIS window's traffic, never a property of the key.

Usage:
    python3 permit_session_join.py [--max-entries 20000] [--tolerance 2.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

TRANSCRIPT_ROOTS = [
    Path.home() / ".claude" / "projects",
    Path.home() / ".kimi-code" / "sessions",
]
# Tools the gate governs a write through. An escalation's cause is one of these.
CAUSING_TOOLS = {"Write", "Edit", "Bash", "NotebookEdit", "MultiEdit"}


def ts_of(s: str) -> float:
    """Chain and transcript stamps are both RFC3339, but differ in fractional digits."""
    s = s.strip().replace("Z", "+00:00")
    # Python's parser caps fractional seconds at 6 digits; the chain emits 9.
    if "." in s:
        head, _, tail = s.partition(".")
        frac = "".join(c for c in tail if c.isdigit())[:6]
        rest = tail[len(tail) - len(tail.lstrip("0123456789")):]
        s = f"{head}.{frac:<06s}{rest}"
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def collect_events(max_entries: int) -> Tuple[List[Dict[str, Any]], Dict[str, Dict], str, str]:
    """Escalation opens and claims, newest->oldest, with the window actually walked."""
    walker = ChainWalker()
    claims: List[Dict[str, Any]] = []
    opens: Dict[str, Dict[str, Any]] = {}
    first = last = None
    for entry in walker.walk(max_entries=max_entries):
        stamp = entry["timestamp"]
        if last is None:
            last = stamp
        first = stamp
        etype = entry.get("eventType", "")
        if not etype.startswith("gate_escalation_"):
            continue
        body = payload(entry)
        rec = {
            "eid": body.get("escalation_id"),
            "plugin_id": body.get("plugin_id"),
            "marker": body.get("marker"),
            "tool_name": body.get("tool_name"),
            "lct": body.get("subject_instance_lct"),
            "ts": stamp,
            "t": ts_of(stamp),
        }
        if etype == "gate_escalation_claimed":
            claims.append(rec)
        elif etype == "gate_escalation_opened":
            opens[rec["eid"]] = rec
    return claims, opens, first, last


def index_transcripts(lo: float, hi: float) -> Dict[str, List[Tuple[float, str, str]]]:
    """(time -> session) for every tool_use in the window, bucketed by tool name.

    Returns {tool_name: sorted [(t, session_id, source_path)]}.
    """
    by_tool: Dict[str, List[Tuple[float, str, str]]] = defaultdict(list)
    scanned = 0
    for root in TRANSCRIPT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                if path.stat().st_mtime < lo - 3600:
                    continue
            except OSError:
                continue
            scanned += 1
            try:
                with path.open("r", errors="replace") as fh:
                    for line in fh:
                        # Cheap reject before paying for json.loads.
                        if '"tool_use"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        stamp = rec.get("timestamp")
                        if not stamp:
                            continue
                        try:
                            t = ts_of(stamp)
                        except ValueError:
                            continue
                        if not (lo <= t <= hi):
                            continue
                        session = rec.get("sessionId") or path.stem
                        msg = rec.get("message") or {}
                        content = msg.get("content")
                        if not isinstance(content, list):
                            continue
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") != "tool_use":
                                continue
                            name = block.get("name")
                            if name in CAUSING_TOOLS:
                                by_tool[name].append((t, session, str(path)))
            except OSError:
                continue
    for name in by_tool:
        by_tool[name].sort()
    print(f"  indexed {scanned} transcripts, "
          f"{sum(len(v) for v in by_tool.values())} governed tool_use records in window",
          file=sys.stderr)
    return by_tool


def nearest_before(
    index: Dict[str, List[Tuple[float, str, str]]],
    tool: Optional[str],
    t: float,
    tolerance: float,
) -> Optional[Tuple[float, str, str]]:
    """The last matching tool_use at or before t, within tolerance.

    Constrained to the SAME tool the chain recorded: two sessions acting inside the
    same second are exactly the confusion this measurement is about, and the tool name
    is the one discriminator the chain and the transcript both carry.
    """
    rows = index.get(tool, []) if tool else []
    if not rows:
        return None
    i = bisect_left(rows, (t, "", "")) - 1
    if i < 0:
        return None
    cand = rows[i]
    if t - cand[0] > tolerance:
        return None
    # Ambiguous if a DIFFERENT session also acted inside the tolerance window: then the
    # nearest record is not identifiable as the cause and this row must not be counted.
    if i - 1 >= 0 and t - rows[i - 1][0] <= tolerance and rows[i - 1][1] != cand[1]:
        return (cand[0], "AMBIGUOUS", cand[2])
    return cand


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-entries", type=int, default=20000)
    ap.add_argument("--tolerance", type=float, default=2.0,
                    help="seconds after the chain event to look for the causing tool_use")
    args = ap.parse_args()

    print("walking chain...", file=sys.stderr)
    claims, opens, first, last = collect_events(args.max_entries)
    if not claims:
        print("no claims in window", file=sys.stderr)
        return 2
    lo = min(ts_of(first), min(c["t"] for c in claims))
    hi = max(ts_of(last), max(c["t"] for c in claims)) + 60
    print(f"window {first[:19]} -> {last[:19]}", file=sys.stderr)
    index = index_transcripts(lo, hi)

    arms: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        opened = opens.get(claim["eid"])
        row = {
            "eid": claim["eid"],
            "marker": claim["marker"],
            "claim_ts": claim["ts"],
            "claim_tool": claim["tool_name"],
            "open_tool": opened["tool_name"] if opened else None,
            "open_ts": opened["ts"] if opened else None,
            "lct": claim["lct"],
        }
        cm = nearest_before(index, claim["tool_name"], claim["t"], args.tolerance)
        om = nearest_before(index, opened["tool_name"], opened["t"], args.tolerance) if opened else None
        row["claim_session"] = cm[1] if cm else None
        row["open_session"] = om[1] if om else None
        row["offsets"] = [round(cm[0] - claim["t"], 3) if cm else None,
                          round(om[0] - opened["t"], 3) if (om and opened) else None]
        if row["claim_session"] and row["open_session"]:
            if "AMBIGUOUS" in (row["claim_session"], row["open_session"]):
                row["verdict"] = "AMBIGUOUS"
            else:
                row["verdict"] = ("SAME" if row["claim_session"] == row["open_session"]
                                  else "CROSS-SESSION")
        else:
            row["verdict"] = "UNJOINED"
        arms[claim["plugin_id"] or "?"].append(row)

    print(f"\nwindow {first[:19]} -> {last[:19]}  (tolerance {args.tolerance}s)")
    for plugin_id in sorted(arms):
        rows = arms[plugin_id]
        tally = defaultdict(int)
        for r in rows:
            tally[r["verdict"]] += 1
        arm = "CONTROL (attributed)" if plugin_id != "unattributed" else "TEST (shared key)"
        print(f"\n=== {plugin_id}  n={len(rows)}  [{arm}] ===")
        print("   ", dict(tally))
        for r in sorted(rows, key=lambda x: x["claim_ts"]):
            if r["verdict"] in ("CROSS-SESSION", "SAME"):
                print(f"    {r['verdict']:14s} {r['eid']} "
                      f"open[{r['open_tool']}]={str(r['open_session'])[:8]} -> "
                      f"claim[{r['claim_tool']}]={str(r['claim_session'])[:8]}  "
                      f"marker={(r['marker'] or '')[:34]}")

    joined = [r for rows in arms.values() for r in rows if r["verdict"] in ("SAME", "CROSS-SESSION")]
    blind = 1 - (len(joined) / len(claims)) if claims else 1.0
    print(f"\nblind fraction: {blind:.1%} of {len(claims)} claims could not be joined "
          f"(unjoined or ambiguous) — every count above is a FLOOR.")

    # The control must actually RESOLVE before its verdict means anything. An all-unjoined
    # control arm produces "no attributed permit reads as cross-session" — a sentence that
    # is bit-identical between "the join discriminates" and "the join found nothing at all".
    control = [r for pid, rows in arms.items() if pid != "unattributed" for r in rows]
    control_joined = [r for r in control if r["verdict"] in ("SAME", "CROSS-SESSION")]
    control_cross = [r for r in control_joined if r["verdict"] == "CROSS-SESSION"]
    if not control_joined:
        print(f"CONTROL INCONCLUSIVE: 0 of {len(control)} attributed permits joined at all. "
              f"The join resolves nothing, so the test arm proves nothing either — this is "
              f"NOT evidence of same-session behaviour.")
        return 1
    if control_cross:
        print(f"CONTROL FAILED: {len(control_cross)}/{len(control_joined)} joined attributed "
              f"permits also read as cross-session. The join is matching ambient activity "
              f"rather than cause; the test arm proves nothing.")
        return 1
    print(f"control arm: {len(control_joined)}/{len(control)} attributed permits joined, "
          f"0 cross-session — the join resolves and discriminates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
