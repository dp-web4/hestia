#!/usr/bin/env python3
"""Does a `#undelivered:` failure report discharge the notice it reports on?

CLAIM UNDER TEST (kimi-code, findings/wake-0903b-..., 2026-09-03 §4): "a quota-failed
auto-reply bound to the request erases even the *ledger* trace that a review was owed" —
i.e. `member_unanswered` counts a watcher's non-delivery report as an answer, so a
`review_request` nobody reviewed reads as dispositioned.

The clearing condition in `member_unanswered` (core/src/storage/inbox.rs) is

    NOT EXISTS (SELECT 1 FROM member_notices r
                 WHERE r.in_reply_to = n.id
                   AND (r.pointer_uri IS NULL
                        OR r.pointer_uri NOT LIKE '%#undelivered:%'))

so a marker-carrying binder is EXCLUDED from clearing. That clause landed 2026-08-02
(23efb08, "a non-delivery report must not discharge the notice it reports on", F1 of the
CBP notice-699 thread) and is in the deployed binary. This script checks the LEDGER
rather than the source, because shipped is not in force.

METHOD. Feed it the JSON from `hestia_member_unanswered` (owed_to_me + i_owe) for one
seat. Every row in `i_owe` whose pointer carries `#undelivered:` and which binds
`in_reply_to` is a non-delivery report about a notice THIS seat sent. If the report
discharged, its target cannot appear in `owed_to_me`. So:

    still  = target present in owed_to_me  -> the report did NOT discharge (counter-specimen)
    absent = target missing                -> UNDETERMINED, not proof of discharge

The asymmetry is the whole point and it is why this script does not print a rate. A
single `still` refutes the general claim. An `absent` has at least three innocent
readings that this seat cannot separate, because no surface lists the rows binding a
given id: (a) a later real answer bound the target — a post-hoc `review_done` is real
mail and is NOT in the counted kinds, so it clears the row while being invisible here;
(b) the target's kind is outside MEMBER_KINDS_AWAIT_RESPONSE (a report is minted for
every non-ack kind, the fold counts two of them); (c) the 7d TTL prune.

Usage:  hestia-mesh unanswered 3600 > fold.json
        python3 tools/bounce_discharge_census.py fold.json [--json]
"""

from __future__ import annotations

import json
import sys


def census(fold: dict) -> dict:
    i_owe = fold.get("i_owe") or []
    owed = fold.get("owed_to_me") or []
    owed_ids = {r["id"] for r in owed}
    reports = [
        r for r in i_owe
        if "#undelivered:" in (r.get("pointer_uri") or "") and r.get("in_reply_to")
    ]
    # An escalation invitation echoes `#corroborate-or-dissent` ahead of the marker.
    # Restricting to those fixes the target's kind at `review_request` — which IS a
    # counted kind — and so removes reading (b) from the absent column.
    invites = [r for r in reports if "#corroborate-or-dissent#undelivered:" in r["pointer_uri"]]
    still = [r for r in invites if r["in_reply_to"] in owed_ids]
    absent = [r for r in invites if r["in_reply_to"] not in owed_ids]
    return {
        "plugin_id": fold.get("plugin_id"),
        "kinds_counted": fold.get("kinds_counted"),
        "i_owe_rows": len(i_owe),
        "owed_to_me_rows": len(owed),
        "non_delivery_reports_in_i_owe": len(reports),
        "of_those_echoing_an_invitation": len(invites),
        "target_still_unanswered": len(still),
        "target_absent_undetermined": len(absent),
        "verdict": (
            "REFUTED — a non-delivery report does not discharge its target"
            if still else
            "no counter-specimen in this fold; claim not tested here"
        ),
        "counter_specimens": [
            {"report": r["id"], "from": r["from_plugin"], "target": r["in_reply_to"],
             "pointer": r["pointer_uri"][:90]}
            for r in still
        ],
        "undetermined": [
            {"report": r["id"], "from": r["from_plugin"], "target": r["in_reply_to"],
             "pointer": r["pointer_uri"][:90]}
            for r in absent
        ],
    }


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv[1:]
    src = open(args[0]) if args else sys.stdin
    out = census(json.load(src))
    if as_json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"seat {out['plugin_id']}  kinds counted: {out['kinds_counted']}")
    print(f"  i_owe {out['i_owe_rows']}   owed_to_me {out['owed_to_me_rows']}")
    print(f"  non-delivery reports bound to my sent mail: {out['non_delivery_reports_in_i_owe']}")
    print(f"    of those, echoing an escalation invitation: {out['of_those_echoing_an_invitation']}")
    print(f"      target STILL counted unanswered (counter-specimen): {out['target_still_unanswered']}")
    print(f"      target absent (UNDETERMINED, see docstring):        {out['target_absent_undetermined']}")
    print(f"  {out['verdict']}")
    for c in out["counter_specimens"][:5]:
        print(f"    e.g. report {c['report']} from {c['from']} -> target {c['target']} still owed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
