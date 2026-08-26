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

STORE, NAMED. `/home/dp/.hestia/witness.db` on CBP, read over the daemon at
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "private-context", "hestia-local", "probes"))
import chainwalk  # noqa: E402  -- located above; see ref_chainwalk_wrapper_exists

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


def classify(stated_reason):
    """attestable | destination-only | redacted | absent, from the STRING, not the tool."""
    if not stated_reason or not str(stated_reason).strip():
        return "absent"
    s = str(stated_reason).strip()
    if _REDACTED.search(s):
        return "redacted"
    if _DEST_ONLY.match(s):
        return "destination-only"
    return "attestable"


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

    chain = chainwalk.Chain()
    rows, hops, seen_ids = [], 0, set()
    span_new = span_old = None
    for entry in chain.walk(max_hops=args.max_hops, progress=2000):
        hops += 1
        ts = entry.get("timestamp")
        if ts:
            span_new = span_new or ts
            span_old = ts
        if entry.get("eventType") != OPENED:
            continue
        p = chainwalk.payload(entry)
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

    if args.json:
        print(json.dumps({"hops": hops, "span": [span_old, span_new],
                          "opened": len(rows), "by_class": dict(by_class),
                          "by_tool": {f"{t}/{c}": n for (t, c), n in by_tool.items()},
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
    unattestable = by_class["destination-only"] + by_class["absent"]  # NOT "redacted"
    if rows:
        print(f"\n{unattestable} of {len(rows)} opened escalations "
              f"({unattestable / len(rows):.0%}) expose no act text to a reviewing peer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
