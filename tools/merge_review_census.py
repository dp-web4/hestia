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
human-only operation"; PR #697 is inside that window and was merged by
`gh pr merge 697 --squash` running in kimi-code's own wake. The only record that
distinguishes them is the seat's fire log, so `--logs` joins against it.

The join is on the merge instant falling inside a wake's span, and the log's
INTERNAL timestamps are authoritative for that span — the filename is local time
and the body is UTC, which is a 7-hour trap that made this look like a
non-overlap on first read.

Both defaults are deliberately conservative: a PR counts as reviewed on one
comment, and a merge counts as seat-performed only when a merge command for that
exact PR number sits in a wake whose span contains the merge.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_LOGINS = {"chatgpt-codex-connector", "github-actions"}
# Titles the fleet uses for writeups, as opposed to behaviour changes. The split
# is the point of the census: these are the fleet's memory-of-record.
FINDINGS_PREFIXES = ("findings", "census", "docs", "shim ledger")
MERGE_CMD = re.compile(r"gh pr merge\s+(\d+)")
# A log that greps the log archive quotes other logs' merge commands. Those
# lines carry a log path, and counting them attributes every census wake a
# merge it never performed — this filter is why the seat-merge count is 1 and
# not 16.
QUOTED = re.compile(r"\.log-|/logs/")
ISO_IN_BODY = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


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


def wake_span(path: Path) -> tuple[datetime, datetime] | None:
    """The UTC span of a wake, from timestamps in the log BODY.

    The filename is local time; the body is UTC. Trusting the filename shifts
    every span by the UTC offset and silently breaks the join.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    stamps = sorted(ISO_IN_BODY.findall(text))
    if not stamps:
        return None
    return _parse(stamps[0] + "Z"), _parse(stamps[-1] + "Z")


def seat_merges(log_dir: Path) -> dict[int, list[tuple[str, datetime, datetime]]]:
    """PR number -> [(seat, wake_start, wake_end)] for merges a seat ran itself."""
    found: dict[int, list[tuple[str, datetime, datetime]]] = {}
    for path in sorted(log_dir.glob("*.log")):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        nums = set()
        for line in lines:
            if QUOTED.search(line):
                continue
            nums.update(int(m) for m in MERGE_CMD.findall(line))
        if not nums:
            continue
        span = wake_span(path)
        if span is None:
            continue
        seat = path.name.split("-", 1)[0]
        for n in nums:
            found.setdefault(n, []).append((seat, span[0], span[1]))
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
        merged = _parse(p["mergedAt"])
        performer = (p.get("mergedBy") or {}).get("login")
        claimed_by = None
        for seat, start, end in merges.get(p["number"], []):
            if start <= merged <= end:
                claimed_by = seat
                break
        rows.append({
            "number": p["number"],
            "title": p.get("title") or "",
            "mergedAt": p["mergedAt"],
            "reviewed": bool(substantive_comments(p, min_body)),
            "github_reviews": len(p.get("reviews") or []),
            "findings_class": is_findings(p.get("title") or ""),
            "mergedBy": performer,
            "performed_by_seat": claimed_by,
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
            (r["number"], r["performed_by_seat"]) for r in rows if r["performed_by_seat"]
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
    print(f"  merges a seat performed in its own wake: {out['seat_performed'] or 'none found'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
