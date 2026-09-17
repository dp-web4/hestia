#!/usr/bin/env python3
"""Where does a corroborating peer's evidence come from — the invitation, or the disk?

THE QUESTION. #615/#616/#678 measured what the invitation CARRIES (an act string, often
cut, never a payload). #1056 measured what the chain BINDS for a later auditor (a pointer,
not the bytes). Neither asked the positive question: when a peer does file a factor, what
did it actually look at? The factors are prose, they are stored verbatim, and they are the
only surface on which a reviewer's sources are legible at all.

The answer matters because of what #1050 step 2 proposes to do next — grow the answering
population. If peer review is being performed by opening files on the asker's box, then
every reviewer added on a DIFFERENT box reviews a strictly smaller record, and the system
records neither the difference nor the fact that there is one. `gate_escalation_opened`
carries `host_session_id` and `session_id`; it carries no host. So "can this reviewer see
what it is approving" is not a question the chain can answer about any row it holds.

WHAT COUNTS AS OUT-OF-BAND. A factor is out-of-band if its argument asserts something that
CANNOT be derived from the invitation surface the peer was given. The surface is exactly
what `resolve_escalation_pointer` re-emits (handler.rs) plus what
`hestia_gate_pending_escalations` re-emits: `tool_name`, `marker`, `stated_reason`,
`stated_detail`, `bar`, invited peers, asker basis. Of those only `stated_reason` can carry
the act; `stated_detail` is a gate-authored constant on the auto-open path.

THE CONTROL IS THE WHOLE MEASUREMENT. A detector that just greps the argument for hashes
and `file:line` scores an echo of the invitation as independent work. So every candidate
signal token is checked against the invitation text for THAT escalation, and a token that
appears in the invitation is discarded. A factor scores `out_of_band` only on a token the
peer could not have read in its wake-up. `--show-discarded` prints what the control threw
away, because a control that never fires is not a control.

NEGATIVE CONTROL. `record_only` is a real class, not a residue: a factor that reasons about
the act string alone (shell ordering, target path, blast radius) is legitimate review of
the thing the peer was actually shown. If that class is empty the detector is too loose;
if it is everything the detector is broken. Both are reported.

TRAP, MEASURED. `factors_present` on a `gate_escalation_corroborated` row repeats the whole
factor set, including the row's OWN factor. Counting arguments out of `factors_present`
double-counts every earlier factor once per later corroboration. This reads the top-level
`argument`/`corroborated_by` only, one factor per row, and asserts the invariant.

STORE, NAMED. The witness chain over the daemon at $HESTIA_ENDPOINT (default
127.0.0.1:7711), walked with `chain_walk.ChainWalker` — imported, never re-hand-rolled.

Usage:
    python3 tools/peer_review_is_out_of_band.py --max 60000
    python3 tools/peer_review_is_out_of_band.py --max 60000 --show-discarded --json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

CORROBORATED = "gate_escalation_corroborated"
OPENED = "gate_escalation_opened"

#: A `path.ext:LINE` citation. The reviewer opened a source file and read a line number;
#: no invitation field carries one.
RE_FILELINE = re.compile(r"\b[\w./-]+\.(?:py|rs|md|sh|toml|json|yml|yaml|txt):\d+\b")

#: A content hash. 8 hex is the fleet's short form (`8c1a5bef`); anything longer is a full
#: digest. Bounded below at 8 so that ordinary hex-ish words do not qualify — but the bound
#: alone does NOT stop a compact 8-digit date: `20260902` is 8 hex chars, and scored as a
#: hash in two factors whose only "hash" was a filename date (kimi review of notice 13081:
#: dc1315dbf755 flipped class on it — its real hash had been correctly discarded by the
#: invitation control — moving the census 92→91, 64%→63%). The lookahead refuses exactly
#: 19/20-prefix 8-digit dates; longer digit strings are not dates and still qualify.
RE_HASH = re.compile(r"\b(?!(?:19|20)\d{6}\b)[0-9a-f]{8,64}\b")

#: A count the reviewer had to compute by running something: diff stats, line counts, row
#: counts. The invitation carries no numbers about the payload.
RE_COUNT = re.compile(
    r"\b\d+\s+(?:insertions?|deletions?|added|additions?|removed|lines?|rows?|hunks?|"
    r"files?\s+changed|bytes?)\b",
    re.IGNORECASE,
)

#: An assertion about filesystem state at review time. Each of these is a claim about a
#: file the peer opened (or failed to open) — the dereference this census is looking for.
RE_FSSTATE = re.compile(
    r"\b(?:does not exist|doesn't exist|already exists|is empty|nothing staged|"
    r"no other hunk|byte-for-byte|working tree|worktree|untracked|uncommitted|"
    r"overwrites nothing|currently exist)\b",
    re.IGNORECASE,
)

SIGNALS = (
    ("file_line", RE_FILELINE),
    ("hash", RE_HASH),
    ("computed_count", RE_COUNT),
    ("fs_state", RE_FSSTATE),
)

#: THE CONSERVATIVE FLOOR. `hash` and `computed_count` prove the peer had a source the
#: invitation did not carry, but not WHERE it came from — a hash can arrive in a mesh
#: notice. `file_line` and `fs_state` can only come from opening the asker's filesystem:
#: a line number in a source file, or an assertion about whether a path exists right now.
#: Reported separately so the locality claim rests on the arm that supports it.
LOCAL_DISK_SIGNALS = frozenset({"file_line", "fs_state"})

#: A `record_only` factor that says so. These are peers that stayed on the record — the
#: behaviour the remedy wants — and reported the record could not support a review. The
#: class matters because it is the measured preview of what an OFF-BOX reviewer gets.
#:
#: NO TRAILING `\b`. The first draft anchored both ends, and `truncat\b` can never match
#: `truncated` — the stem is followed by a letter, not a boundary. It scored 8 where an
#: unanchored pass scored 18, and it failed SILENTLY, with a plausible number. Every
#: alternative here is a stem or a phrase prefix by design; the leading `\b` is what stops
#: mid-word hits, and it is the only one that is correct to have.
RE_INSUFFICIENT = re.compile(
    r"\b(?:cannot corroborate|can't corroborate|insufficient|truncat|ends at the|"
    r"not enough|no way to|unreviewable|preview|is unknown|supplies no|does not carry|"
    r"withheld)",
    re.IGNORECASE,
)


def invitation_text(opened: dict) -> str:
    """Exactly what an invited peer is handed, concatenated for a substring control.

    Deliberately GENEROUS: it includes every field the resolver re-emits, so a token is
    only scored out-of-band if it is absent from ALL of them. An over-wide control can
    only shrink the finding, which is the direction an honest control should err.
    """
    parts = [
        opened.get("stated_reason") or "",
        opened.get("stated_detail") or "",
        opened.get("marker") or "",
        opened.get("tool_name") or "",
        opened.get("bar") or "",
        opened.get("act_digest") or "",
        opened.get("escalation_id") or "",
        opened.get("plugin_id") or "",
        opened.get("gate_path") or "",
        " ".join(opened.get("invited_peers") or []),
    ]
    return " ".join(parts).lower()


def classify(argument: str, invitation: str) -> tuple[dict, list]:
    """Return (signals kept, tokens discarded by the control)."""
    kept: dict[str, list[str]] = {}
    discarded: list[tuple[str, str]] = []
    for name, rx in SIGNALS:
        for m in rx.findall(argument or ""):
            tok = m if isinstance(m, str) else m[0]
            if tok.lower() in invitation:
                discarded.append((name, tok))
                continue
            kept.setdefault(name, [])
            if tok not in kept[name]:
                kept[name].append(tok)
    return {k: v for k, v in kept.items() if v}, discarded


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=60000, help="chain entries to walk")
    ap.add_argument("--show-discarded", action="store_true",
                    help="print the tokens the invitation control removed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    w = ChainWalker()
    opens: dict[str, dict] = {}
    factors: list[dict] = []
    span_new = span_old = None
    walked = 0

    for e in w.walk(max_entries=args.max):
        walked += 1
        ts = e.get("timestamp") or e.get("createdAt")
        if ts:
            span_new = span_new or ts
            span_old = ts
        et = e.get("eventType")
        if et == OPENED:
            p = payload(e)
            eid = p.get("escalation_id")
            if eid and eid not in opens:
                opens[eid] = p
        elif et == CORROBORATED:
            p = payload(e)
            # TRAP: one factor per ROW. `factors_present` repeats the whole set.
            factors.append({
                "escalation_id": p.get("escalation_id"),
                "by": p.get("corroborated_by"),
                "role": p.get("corroborated_role"),
                "dissent": bool(p.get("dissent")),
                "argument": p.get("argument") or "",
                "bar": p.get("bar"),
                "ts": ts,
            })

    out_of_band = []
    record_only = []
    no_argument = []
    orphan = []            # factor whose open is outside the window — cannot be controlled
    discarded_all: list[tuple[str, str, str]] = []
    by_seat = collections.defaultdict(lambda: collections.Counter())
    signal_hist = collections.Counter()

    for f in factors:
        if not f["argument"].strip():
            no_argument.append(f)
            by_seat[f["by"]]["no_argument"] += 1
            continue
        op = opens.get(f["escalation_id"])
        if op is None:
            orphan.append(f)
            by_seat[f["by"]]["uncontrolled"] += 1
            continue
        inv = invitation_text(op)
        kept, disc = classify(f["argument"], inv)
        for name, tok in disc:
            discarded_all.append((f["escalation_id"], name, tok))
        if kept:
            f["signals"] = kept
            f["act"] = op.get("stated_reason")
            out_of_band.append(f)
            by_seat[f["by"]]["out_of_band"] += 1
            for name in kept:
                signal_hist[name] += 1
        else:
            f["act"] = op.get("stated_reason")
            record_only.append(f)
            by_seat[f["by"]]["record_only"] += 1

    controlled = len(out_of_band) + len(record_only)
    local_disk = [f for f in out_of_band
                  if LOCAL_DISK_SIGNALS & set(f["signals"])]
    insufficient = [f for f in record_only if RE_INSUFFICIENT.search(f["argument"])]
    # The only class that is a review the invitation actually supported.
    on_record_and_sufficient = len(record_only) - len(insufficient)
    result = {
        "walked": walked,
        "span_newest": span_new,
        "span_oldest": span_old,
        "opens_in_window": len(opens),
        "factors": len(factors),
        "controlled": controlled,
        "out_of_band": len(out_of_band),
        "out_of_band_local_disk_floor": len(local_disk),
        "record_only": len(record_only),
        "record_only_declared_insufficient": len(insufficient),
        "on_record_and_sufficient": on_record_and_sufficient,
        "by_seat_local_disk": dict(collections.Counter(f["by"] for f in local_disk)),
        "by_seat_insufficient": dict(collections.Counter(f["by"] for f in insufficient)),
        "no_argument": len(no_argument),
        "uncontrolled_open_outside_window": len(orphan),
        "signal_histogram": dict(signal_hist),
        "control_discarded_tokens": len(discarded_all),
        "by_seat": {k: dict(v) for k, v in sorted(by_seat.items())},
    }

    if args.json:
        result["out_of_band_rows"] = [
            {"escalation_id": f["escalation_id"], "by": f["by"], "signals": f["signals"],
             "act": f["act"]}
            for f in out_of_band
        ]
        result["record_only_rows"] = [
            {"escalation_id": f["escalation_id"], "by": f["by"], "act": f["act"],
             "argument": f["argument"][:400]}
            for f in record_only
        ]
        print(json.dumps(result, indent=2))
        return 0

    print(f"walked {walked} entries  {span_oldest_str(span_old)} .. {span_newest_str(span_new)}")
    print(f"opens in window: {len(opens)}   peer factors: {len(factors)}")
    print()
    print(f"  controlled (factor + its open both in window): {controlled}")
    print(f"    out-of-band evidence : {len(out_of_band)}"
          f"  ({pct(len(out_of_band), controlled)})")
    print(f"      of which local-disk (file:line / fs state) : {len(local_disk)}"
          f"  ({pct(len(local_disk), controlled)})  <- conservative floor")
    print(f"    record-only          : {len(record_only)}"
          f"  ({pct(len(record_only), controlled)})")
    print(f"      of which declared the record INSUFFICIENT  : {len(insufficient)}"
          f"  ({pct(len(insufficient), controlled)})")
    print()
    print(f"  reviews the invitation actually supported      : {on_record_and_sufficient}"
          f"  ({pct(on_record_and_sufficient, controlled)})")
    print(f"  empty argument                               : {len(no_argument)}")
    print(f"  uncontrolled (open outside window)           : {len(orphan)}")
    print()
    print("signal histogram (factors carrying at least one of each):")
    for name, n in signal_hist.most_common():
        print(f"    {name:16s} {n}")
    print()
    print(f"invitation control discarded {len(discarded_all)} echoed tokens")
    if args.show_discarded:
        for eid, name, tok in discarded_all[:40]:
            print(f"    {eid[:12]}  {name:16s} {tok[:60]}")
    print()
    print("by seat:")
    for seat, c in sorted(by_seat.items()):
        print(f"    {seat:14s} " + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))
    print()
    if record_only:
        print("record-only factors (the negative control — these reviewed the act string):")
        for f in record_only[:8]:
            print(f"    {f['escalation_id'][:12]} {f['by']:12s} {f['argument'][:110]}")
    else:
        print("NEGATIVE CONTROL EMPTY — every controlled factor scored out-of-band. "
              "Treat the detector as suspect before treating the result as a finding.")
    return 0


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.0f}%" if d else "n/a"


def span_newest_str(ts) -> str:
    return str(ts or "?")


def span_oldest_str(ts) -> str:
    return str(ts or "?")


if __name__ == "__main__":
    raise SystemExit(main())
