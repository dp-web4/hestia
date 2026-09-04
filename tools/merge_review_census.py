#!/usr/bin/env python3
"""Did the merges that landed on main carry any peer review?

`tools/merge_order_census.py` (#861) asked whether the open queue was *tangled*
and found it was not — 59/64 land clean. It answered a throughput question. This
answers the one underneath it: of the PRs that actually landed, how many had
been read by anybody first?

Two measurements, because they refute two different beliefs:

**REVIEW.** A merge is `unreviewed` when no non-bot comment on it exceeds
`--min-body` characters. The threshold is doing real work: the codex connector
posts a 90-char "create an environment for this repo" advert on many PRs, and
counting that as review would report the queue as universally reviewed. The
GitHub *review* channel is counted separately and is empty fleet-wide (0 of 337
per #519's census, re-measured 0 of 31 here), so comments are the only channel
that carries review at all.

**PERFORMER.** `mergedBy` cannot answer "who merged this". Every seat
authenticates as the same GitHub identity (`dp-web4`), so a seat merge and a
human merge are the same row. #861 read 200 such rows and concluded "merge is a
human-only operation"; four of those rows were performed by seats.

The performer is read from the witness chain, not from the log text. Every
executed command leaves an action/outcome record carrying its own `plugin_id`,
`target` and `action_id`. That record is SELF-ATTRIBUTING: whichever log you
find it in — the seat's own, or a later seat's that grepped the archive and
quoted it — it still names the seat that ran it. De-duplicating on `action_id`
therefore makes quoting harmless by construction, and no time-window join is
needed at all.

The first version of this tool did none of that. It matched `gh pr merge N`
against raw log TEXT, guessed the seat from the log FILENAME, and joined on a
"wake span" taken as the lexical min/max of every ISO timestamp in the body.
codex refuted all three on PR #891, and it was right on the evidence:

  * the span was a CONTENT range, not a wake — primers, quoted findings and
    inspected witness rows carry historical timestamps, so one "wake" ran from
    2026-07-23 to 2026-09-04 and another began at year 0001;
  * the quoted-text filter keyed on `.log-`/`/logs/`, which catches grep output
    but not prose or a diff — so this file's own docstring, which contains the
    string `gh pr merge 697`, contaminated every log that read it;
  * and the filename guess mis-attributed 2 of the 4 real merges, including
    #532, which this census originally published as codex and which the
    outcome record two seconds after the merge names `claude-code`.

That last one is the same error one altitude down. The census exists to say
that `mergedBy` measures the CREDENTIAL rather than the performer — and then
attributed the performer from the CONTAINER (which file the string sat in)
rather than from the record. Asking the artifact who ran it is the fix at both
altitudes.

Both defaults are conservative: a PR counts as reviewed on one comment, and a
merge counts as seat-performed only when a successful witness record names that
exact PR number. Where two records for one PR name different seats the census
reports the conflict instead of picking one.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BOT_LOGINS = {"chatgpt-codex-connector", "github-actions"}
# Titles the fleet uses for writeups, as opposed to behaviour changes. The split
# is the point of the census: these are the fleet's memory-of-record.
FINDINGS_PREFIXES = ("findings", "census", "docs", "shim ledger")
MERGE_CMD = re.compile(r"gh pr merge\s+(\d+)")
# One witness action/outcome record: the keys are emitted in alphabetical order,
# so `action_id` opens it and `tool_name` closes it. Matching the whole record
# (rather than a line) is what lets the seat be read from `plugin_id` INSIDE the
# record instead of guessed from the filename outside it.
WITNESS_REC = re.compile(
    r'"action_id"\s*:\s*"([0-9a-fA-F-]{8,})"(.{0,4000}?)"tool_name"\s*:\s*"[^"]*"', re.S
)
REC_PLUGIN = re.compile(r'"plugin_id"\s*:\s*"([^"]*)"')
REC_TARGET = re.compile(r'"target"\s*:\s*"((?:[^"\\]|\\.)*)"')
REC_SUCCESS = re.compile(r'"success"\s*:\s*(true|false|null)')
# codex's transcripts do not emit witness JSON; they echo each exec as its own
# line, `/bin/bash -lc "<cmd>" in <cwd>`. That is still an execution-specific
# structure, but it carries no plugin_id, so its seat comes from the filename —
# a WEAKER basis, and the census labels it as such rather than blending the two.
EXEC_LINE = re.compile(r'^/bin/bash -lc (.*)$')
# grep -n output re-prints a whole line behind `<path>.log-<n>-`, which is how a
# quoted exec survives into another seat's log. The anchor above is what rejects
# it: a quoted exec never starts its line.
GREP_PREFIX = re.compile(r'^\S*\.log[-:]\d+[-:]')
# A third shape of the same trap, and the one that fooled both reviewers of
# #891: an exec line that is GENUINE and anchored, but whose command is
# `rg 'gh pr merge 697' logs/` — the merge string is a search PATTERN, not a
# command. Searching for a merge is the opposite of performing one.
SEARCH_TOOL = re.compile(r'\b(rg|grep|egrep|fgrep|ag|ack)\b')


def substantive_comments(pr: dict, min_body: int) -> list[dict]:
    out = []
    for c in pr.get("comments") or []:
        login = (c.get("author") or {}).get("login")
        if login in BOT_LOGINS:
            continue
        if len(c.get("body") or "") > min_body:
            out.append(c)
    return out


def is_findings(title: str) -> bool:
    t = (title or "").lower()
    return any(t.startswith(p) for p in FINDINGS_PREFIXES)


def seat_merges(log_dir: Path) -> dict[int, dict]:
    """PR number -> {seat, action_ids, seats} for merges a seat ran itself.

    Scans every log for witness action/outcome records, but attributes each one
    to the `plugin_id` the record carries. A record quoted in three other seats'
    logs is still one merge by one seat, because de-duplication is on
    `action_id`. Text that merely MENTIONS a merge command — prose, a diff, this
    module's own docstring — carries no record and is therefore never counted.
    """
    by_action: dict[str, tuple[int, str, str]] = {}
    for path in sorted(log_dir.glob("*.log")):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "gh pr merge" not in text:
            continue

        # Basis 1: the witness record, which names its own seat.
        for m in WITNESS_REC.finditer(text):
            action_id, body = m.group(1), m.group(2)
            target = REC_TARGET.search(body)
            if not target:
                continue
            success = REC_SUCCESS.search(body)
            if success and success.group(1) != "true":
                continue
            seat = REC_PLUGIN.search(body)
            if not seat:
                continue
            for n in MERGE_CMD.findall(target.group(1)):
                by_action[f"{action_id}:{n}"] = (int(n), seat.group(1), "record")

        # Basis 2: an anchored exec line, whose seat can only come from the file.
        for lineno, line in enumerate(text.splitlines(), 1):
            if GREP_PREFIX.match(line):
                continue
            m = EXEC_LINE.match(line)
            if not m or SEARCH_TOOL.search(m.group(1)):
                continue
            for n in MERGE_CMD.findall(m.group(1)):
                key = f"{path.name}#{lineno}:{n}"
                by_action[key] = (int(n), path.name.split("-", 1)[0], "filename")

    found: dict[int, dict] = {}
    for key, (number, seat, basis) in sorted(by_action.items()):
        row = found.setdefault(number, {"seat": seat, "seats": set(), "basis": basis,
                                        "action_ids": []})
        row["seats"].add(seat)
        row["action_ids"].append(key.split(":", 1)[0])
        # A record beats a filename guess wherever both exist for one PR.
        if basis == "record":
            row["basis"] = "record"
    for row in found.values():
        # Two sources naming different seats is a real ambiguity, not a tie to
        # break by ordering. Say so rather than publishing the first one.
        row["seats"] = sorted(row["seats"])
        if len(row["seats"]) > 1:
            row["seat"] = None
            row["conflict"] = row["seats"]
    return found


def fetch(repo: str, limit: int) -> list[dict]:
    cmd = [
        "gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", str(limit),
        "--json", "number,title,mergedAt,mergedBy,comments,reviews",
    ]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def census(prs: list[dict], min_body: int, merges: dict) -> dict:
    rows = []
    for p in prs:
        if not p.get("mergedAt"):
            continue
        performer = (p.get("mergedBy") or {}).get("login")
        record = merges.get(p["number"]) or {}
        claimed_by = record.get("seat")
        rows.append({
            "number": p["number"],
            "title": p.get("title") or "",
            "mergedAt": p["mergedAt"],
            "reviewed": bool(substantive_comments(p, min_body)),
            "github_reviews": len(p.get("reviews") or []),
            "findings_class": is_findings(p.get("title") or ""),
            "mergedBy": performer,
            "performed_by_seat": claimed_by,
            "seat_conflict": record.get("conflict"),
            "seat_basis": record.get("basis"),
        })
    n = len(rows)
    unrev = [r for r in rows if not r["reviewed"]]
    fnd = [r for r in rows if r["findings_class"]]
    code = [r for r in rows if not r["findings_class"]]
    return {
        "n": n,
        "unreviewed": len(unrev),
        "unreviewed_pct": round(100 * len(unrev) / n, 1) if n else 0.0,
        "github_review_objects": sum(r["github_reviews"] for r in rows),
        "findings_class": len(fnd),
        "findings_unreviewed": sum(1 for r in fnd if not r["reviewed"]),
        "code_class": len(code),
        "code_unreviewed": sum(1 for r in code if not r["reviewed"]),
        "distinct_mergedBy": sorted({r["mergedBy"] for r in rows if r["mergedBy"]}),
        "seat_performed": sorted(
            (r["number"], r["performed_by_seat"], r["seat_basis"])
            for r in rows if r["performed_by_seat"]
        ),
        "seat_conflicts": sorted(
            (r["number"], r["seat_conflict"]) for r in rows if r.get("seat_conflict")
        ),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="dp-web4/hestia")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--min-body", type=int, default=200,
                    help="comment length above which a comment counts as review")
    ap.add_argument("--logs", default="/home/dp/.local/state/hestia-mesh/logs")
    ap.add_argument("--since", default=None, help="only merges on/after this ISO date")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    prs = fetch(args.repo, args.limit)
    if args.since:
        prs = [p for p in prs if (p.get("mergedAt") or "") >= args.since]
    merges = seat_merges(Path(args.logs)) if Path(args.logs).is_dir() else {}
    out = census(prs, args.min_body, merges)

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"merged PRs examined: {out['n']}")
    print(f"  unreviewed (no non-bot comment > {args.min_body} chars): "
          f"{out['unreviewed']} ({out['unreviewed_pct']}%)")
    print(f"  GitHub review objects, all PRs pooled: {out['github_review_objects']}")
    print(f"  findings-class: {out['findings_class']}, of which unreviewed "
          f"{out['findings_unreviewed']}")
    print(f"  code-class:     {out['code_class']}, of which unreviewed "
          f"{out['code_unreviewed']}")
    print(f"  distinct mergedBy identities: {out['distinct_mergedBy']}")
    print(f"  merges a seat performed itself: {out['seat_performed'] or 'none found'}")
    if out["seat_conflicts"]:
        print(f"  AMBIGUOUS (records disagree on the seat): {out['seat_conflicts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
