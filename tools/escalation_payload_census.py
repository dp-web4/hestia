#!/usr/bin/env python3
"""Which escalations carry a reviewable payload, and which carry only a path?

THE QUESTION. A peer asked to `corroborate-or-dissent` on an escalation sees exactly
what `hestia_gate_pending_escalations` re-emits: `tool_name`, `marker`, `stated_reason`,
`stated_detail`. `stated_detail` is a gate-authored CONSTANT on the auto-open path (the
same 3 sentences on every row), so `stated_reason` is the only field that can carry the
act. The hook fills it from `_attempted_summary(tool_name, tool_input)`, which reads
`tool_input["command"]` and, failing that, falls back to a PATH key. Edit/Write/NotebookEdit
have no `command`, so their `old_string`/`new_string`/`content` reach no field at all.

The mechanism is deterministic, so this census is not asking WHETHER -- it is asking
HOW MUCH: what fraction of the escalation population is structurally unattestable.

WHAT COUNTS AS ATTESTABLE. `stated_reason` matching `^<Tool>: ` carries a command body.
`^<Tool> -> ` (or a bare path) carries a destination only. That split is the whole finding,
so it is computed from the stored string rather than from `tool_name` -- a seat whose hook
someday sends a real Edit summary must show up as attestable without this script changing.

AND A CUT BODY IS ITS OWN CLASS (added 2026-08-27). `_attempted_summary` bounds the act
before it reaches the chain, so a long command arrives as a prefix that stops mid-pipeline.
Until now those rows scored `attestable` -- a name that asserts a peer can attest to the
act, on a record that ends in the middle of a shell pipe. The two seats' markers share no
suffix, so a detector keyed on one of them returns a clean per-seat ZERO for the other and
cannot report an error; `_TRUNCATED` below carries both spellings and `_cap_suspects`
screams if a third ever appears.

STORE, NAMED. `~/.hestia/witness.db` on the seat host, read over the daemon at
$HESTIA_ENDPOINT (default 127.0.0.1:7711). The .db is ENCRYPTED at rest -- `sqlite3` says
"file is not a database" -- so there is no cheap local scan and the hash-chain walk at
~1 hop per HTTP round trip is the only route. Hop cost is the reason for `--max-hops`.

POSITIVE CONTROL, MANDATORY. `--expect <id>[,<id>...]` names escalation ids the walk MUST
find. Absence of Edit-with-payload rows is only evidence if the walk can see rows it is
known to contain; without a control, a broken cursor and a clean population print the
same thing. Exits 3 if any expected id is missing, and says so before any count.
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

OPENED = "gate_escalation_opened"

#: DESTINATION-ONLY is a single path-shaped token, optionally behind a `Tool -> ` prefix:
#: `_attempted_summary`'s path fallback, in either spelling the fleet uses.
#:
#: Keying on the PRESENCE of a `Tool: ` prefix was the first draft and it was wrong. The
#: three seats spell the prefix three ways -- this seat sends `Bash: <cmd>`, kimi sends the
#: command BARE with no prefix at all -- so a prefix test scores a fully attestable kimi row
#: as unclassifiable. Measured, not assumed: a live kimi row reads `mkdir -p /tmp/meter-new
#: /tools && ...`. The discriminator that survives all three spellings is whether the field
#: holds ONE path token or a command body, and whitespace separates those cleanly because a
#: path fallback is always exactly one token.
_DEST_ONLY = re.compile(r"^([A-Za-z][A-Za-z0-9_]*\s*->\s*)?/\S*$")
#: A redaction is not a payload, but it is also not a hook that forgot to send one -- the
#: member is being deliberately withheld from the record. Counted apart so the unattestable
#: total is not inflated by rows that are unattestable ON PURPOSE.
_REDACTED = re.compile(r"\[REDACTED\b")
#: A CUT act, in the TWO renderings the fleet emits -- which share no suffix. At source on
#: origin/main: claude-code appends a 2-char `" …"` after `s[:220]`; codex and kimi both
#: append a 12-char `"…[truncated]"` after `s[:400]`. Nothing matches both.
#:
#: This class did not exist until 2026-08-27 and its absence was not neutral: a cut row fell
#: through to `attestable`, a name that asserts a reviewing peer can attest to the act. On
#: 13674a4dde3475ce a peer dissented for exactly the reason this class now names -- the act
#: stopped mid-pipeline at char 400 and the omitted tail was not inspectable from the record.
#:
#: The lesson is in the SPLIT, not the count. An ad-hoc detector keyed on the bare ellipsis
#: alone -- `r.endswith(" …")`, which is what the driver circulated in this thread used --
#: sees claude-code's cuts and returns a clean, well-formed ZERO for the other two seats.
#: Measured 2026-08-27, 40,000 hops, span 08-18..08-27, 222 rows carrying `stated_reason`:
#: claude-code 76 cuts (all len 228) / 0, kimi-code 0 / 13 (all len 412), codex 0 / 10 (all
#: len 412, running 08-24..08-27). That zero is what "claude-code is the only seat still
#: truncating" was published from, and what codex's marker changing spelling on 2026-08-14
#: was misread as: a detector blind spot reported as a producer cutover. A spelling-keyed
#: test returns a wrong site or a clean zero, never an error -- so `main` below screams when
#: a seat's `attestable` rows pile up at one exact length, which is what a FOURTH rendering
#: would look like from here.
_TRUNCATED = re.compile("(…\\[truncated\\]|\\s…)$")


def classify(stated_reason):
    """attestable | truncated | destination-only | redacted | absent, from the STRING.

    `truncated` is tested BEFORE `destination-only` on purpose: a cut path is still all
    non-whitespace, so `_DEST_ONLY` matches it and the cut goes silently unrecorded.
    """
    if not stated_reason or not str(stated_reason).strip():
        return "absent"
    s = str(stated_reason).strip()
    if _REDACTED.search(s):
        return "redacted"
    if _TRUNCATED.search(s):
        return "truncated"
    if _DEST_ONLY.match(s):
        return "destination-only"
    return "attestable"


def _cap_suspects(rows, floor=3):
    """Seats whose `attestable` rows pile up at one exact length -- an unrecognised cap.

    `_TRUNCATED` knows two spellings because two are what the fleet emits today. A third
    producer, or either of these two changing its marker, would score every cut row as
    `attestable` and this census would report a confident zero for that seat. It could not
    report an error, because a spelling test has no error state.

    A cap leaves a signature the spelling cannot hide: many DISTINCT acts at ONE length,
    and that length the longest the seat produces. Returns [(seat, length, n_distinct,
    total_attestable)] so a caller can say WHICH seat to go read the source of, rather
    than trusting the zero.

    DISTINCT is load-bearing and was learned from live traffic, not reasoned out: the first
    draft counted rows, and on the 2026-08-27 walk it fired on kimi-code -- 5 rows at
    exactly 399 chars -- which turned out to be TWO retried commands, both ending in a
    complete `| tail -3`. A retry piles one act at one length; a cap piles many different
    acts there. Counting rows cannot tell those apart, and a scream that fires on ordinary
    retries is a scream that gets muted.
    """
    lens = collections.defaultdict(list)
    for r in rows:
        if r["class"] == "attestable" and isinstance(r.get("stated_reason"), str):
            lens[r["plugin_id"]].append(r["stated_reason"].strip())
    out = []
    for seat, texts in lens.items():
        longest = max(len(t) for t in texts)
        n_distinct = len({t for t in texts if len(t) == longest})
        if n_distinct >= floor and len({len(t) for t in texts}) > 1:
            out.append((seat, longest, n_distinct, len(texts)))
    return sorted(out, key=lambda t: -t[2])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-hops", type=int, default=20000,
                    help="stop after N hops; the walk is one HTTP round trip per hop")
    ap.add_argument("--expect", default="",
                    help="comma-separated escalation ids the walk MUST find (positive control)")
    ap.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = ap.parse_args(argv)

    expected = {e.strip() for e in args.expect.split(",") if e.strip()}

    chain = ChainWalker()
    rows, hops, seen_ids = [], 0, set()
    span_new = span_old = None
    for entry in chain.walk(max_entries=args.max_hops):
        hops += 1
        ts = entry.get("timestamp")
        if ts:
            span_new = span_new or ts
            span_old = ts
        if entry.get("eventType") != OPENED:
            continue
        p = payload(entry)
        eid = p.get("escalation_id") or p.get("id")
        if eid:
            seen_ids.add(eid)
        rows.append({
            "escalation_id": eid,
            "at": ts,
            "plugin_id": p.get("plugin_id"),
            "tool_name": p.get("tool_name"),
            "marker": p.get("marker"),
            "stated_reason": p.get("stated_reason"),
            "class": classify(p.get("stated_reason")),
        })

    # CONTROL FIRST. A count printed before its control has been read as a result.
    missing = sorted(expected - seen_ids)
    if missing:
        sys.stderr.write(
            f"POSITIVE CONTROL FAILED: {len(missing)} expected id(s) not found in "
            f"{hops} hops: {', '.join(missing)}\n"
            "The walk did not see rows it is known to contain, so its counts are NOT "
            "evidence of anything. Raise --max-hops or fix the cursor.\n")
        return 3

    by_class = collections.Counter(r["class"] for r in rows)
    by_tool = collections.Counter((r["tool_name"], r["class"]) for r in rows)
    by_seat_class = collections.Counter((r["plugin_id"], r["class"]) for r in rows)
    unrecognised_caps = _cap_suspects(rows)

    if args.json:
        print(json.dumps({"hops": hops, "span": [span_old, span_new],
                          "opened": len(rows), "by_class": dict(by_class),
                          "by_tool": {f"{t}/{c}": n for (t, c), n in by_tool.items()},
                          "by_seat": {f"{s or '?'}/{c}": n
                                      for (s, c), n in by_seat_class.items()},
                          "unrecognised_cap_suspects": [
                              {"plugin_id": s, "length": L, "rows_at_length": n,
                               "attestable_rows": tot}
                              for s, L, n, tot in unrecognised_caps],
                          "control_ids_found": sorted(expected),
                          "rows": rows}, indent=1))
        return 0

    print(f"walked {hops} hops, {span_old} -> {span_new}")
    if expected:
        print(f"positive control: {len(expected)} expected id(s) all found")
    print(f"{OPENED}: {len(rows)}")
    for cls, n in by_class.most_common():
        print(f"  {n:5d}  {cls}")
    print("\nby tool:")
    for (tool, cls), n in sorted(by_tool.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {tool or '?':16s} {cls}")
    # BY SEAT, always -- a per-class total hides which producer it came from, and every
    # wrong claim this census has carried was a per-seat zero read as a fleet property.
    print("\nby seat:")
    for (seat, cls), n in sorted(by_seat_class.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {seat or '?':16s} {cls}")
    unattestable = by_class["destination-only"] + by_class["absent"]  # NOT "redacted"
    if rows:
        print(f"\n{unattestable} of {len(rows)} opened escalations "
              f"({unattestable / len(rows):.0%}) expose no act text to a reviewing peer.")
        # Reported SEPARATELY rather than folded into the number above: that number has
        # been published, and silently changing what it counts is how a corrected figure
        # gets read as a changed world.
        cut = by_class["truncated"]
        print(f"{cut} more ({cut / len(rows):.0%}) expose a CUT act -- a prefix, stopping "
              f"wherever the seat's cap fell. Reviewable in part, attestable in none.")
    if unrecognised_caps:
        print("\nUNRECOGNISED CAP SUSPECTS -- attestable rows piling up at one length:")
        for seat, length, n, tot in unrecognised_caps:
            print(f"  {seat or '?':16s} {n} of {tot} attestable rows are exactly {length} "
                  f"chars. Read that seat's `_attempted_summary` before trusting its "
                  f"truncated=0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
