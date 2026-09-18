#!/usr/bin/env python3
"""Did the reviewer actually READ the path its factor names? Ask the seat, not the prose.

WHY THIS EXISTS. `tools/peer_review_is_out_of_band.py` classifies a factor's PROSE to
decide whether the peer reached the asker's filesystem. kimi-code's review of notice 13081
showed the prose cannot settle it: the vocabulary is open-ended natural language, and four
independent passes over the same 144 factors put the local-disk floor at 44, 26, 22 and 16.
Every pass undercounts in the same direction and none of them converges, because "clean at
HEAD", "no diff at review time" and "old_string matches once" are filesystem observations
written in words no regex list anticipated.

The question does not have to be answered from prose. Every answering seat is a systemd
wake on this one box, and each seat writes a structured session transcript. So for a factor
filed at time T by seat S there is a record of what S actually RAN before filing it.

WHAT THIS MEASURES. A factor is READ-CONFIRMED when the seat's own transcript shows a
reader command (cat/sed/rg/git/stat/...) whose text contains a concrete path that the
factor also names, executed in the window before the factor was filed. No vocabulary is in
the loop: the evidence is an invocation, not an adjective.

THE JOIN IS BY TIME, AND THAT IS THE DEFECT. `gate_escalation_corroborated` carries
`corroborated_by` and `corroborated_role` and NOTHING ELSE about provenance -- no
`session_id`, no host, strictly less than `gate_escalation_opened`, which at least carries
`session_id`/`host_session_id`. So a factor cannot be joined to the session that produced
it; it can only be matched to whichever of that seat's sessions was open at the time. One
recorded `session_id` on the corroborate row would make this exact instead of heuristic --
and would make "is naming a worktree evidence of reading one" a lookup rather than a
definition question.

SEAT COVERAGE IS PARTIAL, AND NAMED. Only codex is implemented. Its rollout jsonl records
every shell invocation as a `custom_tool_call` named `exec` with the command under `input`.
claude-code and kimi-code keep session jsonl too, but with different shapes; their
extractors are NOT written, so this tool reports codex and says so rather than reporting a
fleet number it did not measure.

INSTRUMENT DEFECT, MEASURED. The first version read `payload["arguments"]` on
`function_call` items -- codex's actual shell calls are `custom_tool_call`/`input`. It saw
5 commands where there were 304 and returned a perfectly plausible ZERO confirmed reads.
Caught only because zero was implausible for a seat whose factors say "I inspected the
named worktree". Fourth instrument defect in this thread, same class every time.

Usage:
    python3 tools/factor_reads_ground_truth.py --max 60000 --window 30
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

CORROBORATED = "gate_escalation_corroborated"
OPENED = "gate_escalation_opened"
CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")

#: A concrete path a factor can name. Bounded below so bare directory words do not qualify.
RE_PATH = re.compile(r"(?:/tmp/[\w./-]{4,}|(?:scratchpad|plugins|core|tools|findings|\.wt)/[\w./-]{4,})")
#: Paths every wake touches for its own bookkeeping -- not evidence about the asker.
RE_NOISE = re.compile(r"hestia-mesh-primers|notice-\w+\.json")
#: A command that dereferences a path. `git` is in: `git status`/`diff`/`show` in a named
#: worktree is exactly the dereference this asks about.
RE_READER = re.compile(r"\b(?:cat|head|tail|sed|nl|wc|grep|rg|ls|stat|find|diff|"
                       r"md5sum|sha256sum|cmp|git)\b")


def T(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def index_codex_sessions() -> list[dict]:
    """Every codex rollout that carries at least one tool call, with its span."""
    out = []
    for f in glob.glob(os.path.join(CODEX_SESSIONS, "2026/**/*.jsonl"), recursive=True):
        first = last = None
        cmds = []
        try:
            fh = open(f, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                ts = o.get("timestamp")
                if ts:
                    first = first or ts
                    last = ts
                p = o.get("payload") or {}
                # TRAP: codex shell calls are custom_tool_call/input, NOT
                # function_call/arguments. Reading the wrong pair returns a plausible zero.
                if o.get("type") == "response_item" and p.get("type") in (
                        "function_call", "custom_tool_call"):
                    cmds.append((ts, ((p.get("input") or p.get("arguments")) or "")[:8000]))
        if first and cmds:
            out.append({"file": f, "start": first, "end": last, "cmds": cmds})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=60000)
    ap.add_argument("--window", type=int, default=30,
                    help="minutes before the factor in which a read counts")
    ap.add_argument("--show", action="store_true", help="print the confirming commands")
    args = ap.parse_args()

    w = ChainWalker()
    opens: dict[str, dict] = {}
    factors = []
    for e in w.walk(max_entries=args.max):
        et = e.get("eventType")
        if et == OPENED:
            p = payload(e)
            eid = p.get("escalation_id")
            if eid and eid not in opens:
                opens[eid] = p
        elif et == CORROBORATED:
            p = payload(e)
            if (p.get("corroborated_by") or "") != "codex":
                continue
            factors.append({"escalation_id": p.get("escalation_id"),
                            "argument": p.get("argument") or "",
                            "ts": e.get("timestamp")})
    factors = [f for f in factors
               if f["argument"].strip() and f["escalation_id"] in opens and f["ts"]]

    sessions = index_codex_sessions()
    verdict = collections.Counter()
    rows = []
    for f in factors:
        ts = T(f["ts"])
        paths = {p for p in RE_PATH.findall(f["argument"]) if not RE_NOISE.search(p)}
        if not paths:
            verdict["no-path-named"] += 1
            continue
        live = [s for s in sessions if T(s["start"]) <= ts <= T(s["end"])]
        if not live:
            verdict["no-session-open"] += 1
            continue
        hits = []
        for s in live:
            for cts, txt in s["cmds"]:
                lag = (ts - T(cts)).total_seconds() / 60.0
                if not (0 <= lag <= args.window) or not RE_READER.search(txt):
                    continue
                for p in paths:
                    if p in txt:
                        hits.append((round(lag, 1), p, " ".join(txt.split())[:160]))
        verdict["READ-CONFIRMED" if hits else "named-not-read"] += 1
        if hits:
            rows.append({"escalation_id": f["escalation_id"], "hits": hits[:3]})

    print(f"codex factors (controlled, non-empty): {len(factors)}")
    print(f"codex rollouts carrying tool calls    : {len(sessions)}")
    print(f"read window                           : {args.window} min before the factor")
    for k, n in verdict.most_common():
        print(f"    {k:18s} {n}")
    if args.show:
        for r in rows:
            print(f"\n[{r['escalation_id'][:12]}]")
            for lag, p, txt in r["hits"]:
                print(f"   -{lag:5.1f}m  {p}\n            {txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
