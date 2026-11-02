#!/usr/bin/env python3
"""Did the merges that landed on main carry any peer review — and who performed them?

`tools/merge_order_census.py` (#861) asked whether the open queue was *tangled*.
This instrument measures pre-merge discussion and candidate performer evidence;
neither proxy proves an independent review or identifies a merger by itself.

**DISCUSSION PROXY.** `unreviewed` is a historical field name: it counts PRs
with no qualifying, demonstrably pre-merge discussion in either GitHub channel,
not PRs proved unread. A long body can be the author's status note or unrelated
discussion; a shared account also cannot establish reviewer independence. Bodies
with ambiguous timestamps or later edits are counted separately as unknown.
Qualifying means a non-bot body over `--min-body` characters. The threshold is
doing real work: the codex connector posts a 90-char "create an environment for
this repo" advert on many PRs, and counting that as review would report the
queue as universally reviewed.

  Reading BOTH channels is a correction to this census, not a design choice.
  v1 and v2 counted comments only, on the stated ground that "the GitHub review
  channel is counted separately and is empty fleet-wide (0 of 337 per #519, 0 of
  31 re-measured here)." That is false and this tool refutes it: 134 of 551
  merged PRs carry a review object, all 182 of them `COMMENTED` with a body over
  200 characters. `gh pr review --comment` — which is how seats on this fleet
  post review — writes to the review channel and leaves the comment channel
  empty, so 64 PRs that WERE read were published as unread.

  This is the same error as the performer defect, one altitude over: a channel
  was declared empty rather than measured, and the census inherited the
  declaration. The headline moves from 53.4% unread to 41.7% as a result.

**PERFORMER.** `mergedBy` cannot answer "who merged this". Every seat
authenticates as the same GitHub identity (`dp-web4`), so a seat merge and a
human merge are the same row.

THE PERFORMER IS READ FROM THE WITNESS CHAIN, NOT FROM LOG TEXT. This is the
third version of that reader, and the first one that is not measuring itself.

  v1 matched the merge command against raw log TEXT, guessed the seat from the
  log FILENAME, and joined on a "wake span" taken as the lexical min/max of
  every ISO timestamp in the body. codex refuted all three on #891.

  v2 kept the logs but read the seat from a witness record quoted inside them,
  arguing that a record is SELF-ATTRIBUTING so quotation is harmless and
  de-duplication on `action_id` is sufficient. codex refuted that too, and the
  refutation is the interesting one: quotation is harmless only when it is
  TOTAL. A record quoted in PART — an excerpt that stops mid-envelope — leaves
  a dangling `action_id` that the next complete record closes, and the field
  extractors then splice a `plugin_id` from one action onto a `target` from
  another. codex produced that state merely by PRINTING an excerpt during
  review: the census's answer for #353 changed from `claude-code` to AMBIGUOUS
  with no merge occurring. **Reading the corpus wrote to the corpus.**

  That is not a regex bug with a regex fix. It is what a log-derived census
  IS. The fleet's logs are where seats paste what they are investigating, so
  an instrument that greps logs for X accumulates its own searches for X. This
  is now the dominant signal: of the 172 merge-mentioning targets in the whole
  chain, the 5 most recent are all *searches for merges* performed while
  reviewing this file. None is a merge.

  v3 therefore does not read logs at all. It walks the witness chain through
  `chain_walk.ChainWalker`, where each entry carries its own `plugin_id`,
  `success`, `target` and `timestamp` as STRUCTURED FIELDS. There is no
  quotation, no splicing, no filename guess, and no de-duplication to get
  wrong. The corresponding discipline for the CALLER is in this module's
  layout: the merge pattern lives in this file and never on a command line,
  because the command line is itself the corpus.

Three filters stand between a chain entry and a counted merge, and each closes
a defect codex demonstrated:

  1. COMMAND POSITION. `gh pr merge N` is counted only when it opens a command
     segment after shell lexing — not when it appears inside a quoted argument.
     This is structural, not a tool blacklist: `rg 'gh pr merge 697' logs/` and
     `printf 'gh pr merge 532'` both lex to a single token that is not at a
     command position, so both are rejected without naming `rg` or `printf`.
     v2 guarded only the codex-exec branch and let these through on the record
     branch, which is the basis the finding treated as authoritative.

  2. OUTCOME, SUCCESS, NO ERROR. Only `outcome` entries with `success is True`
     and a null `error` count. v2 accepted an entry with NO `success` key at
     all, which meant `policy_decision` events — records of a merge the gate
     BLOCKED — were counted as merges performed.

  3. CORROBORATION AGAINST THE MERGE INSTANT. `success: true` is the shell
     wrapper's exit status, not the merge's: the #532 target ends
     `2>&1 | tail -5; echo "rc=$?"`, where the pipeline observes `tail` and the
     `echo` makes the shell succeed regardless. So a successful command is not
     evidence of a successful merge. A seat merge is counted only when the
     outcome's timestamp falls within `--merge-window` seconds AFTER the PR's
     GitHub `mergedAt`. Commands that pass 1 and 2 but land nowhere near a
     merge instant are reported separately as `uncorroborated` — that bucket
     is where a masked failure lives, and it is 30 rows deep.

The corroboration is tight rather than tuned: the median gap between the merge
instant and the outcome record is under 5 seconds, and the count moves by 3
rows between a 60-second window and a 30-minute one. The result is not an
artifact of the window.

WHAT THIS STILL CANNOT SEE. The chain records actions taken through the
governed hook. A merge performed outside it — the GitHub web UI, an ungoverned
shell, a seat whose hook was not installed — leaves no entry and is invisible
here. The timing join can also produce false positives, such as a failed wrapped
command near an independent merge. This is a candidate estimate, not a strict
lower bound; the human-performed remainder is not a measurement.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BOT_LOGINS = {"chatgpt-codex-connector", "github-actions"}
# Titles the fleet uses for writeups, as opposed to behaviour changes. The split
# is the point of the census: these are the fleet's memory-of-record.
FINDINGS_PREFIXES = ("findings", "census", "docs", "shim ledger")

# The subject of the census, spelled ONCE and only here. It is deliberately not
# a module constant a caller could pass on a command line: every command a seat
# runs is chained with its `target` verbatim, so a census invoked as
# `... --pattern "gh pr merge"` would enter its own corpus on the next run. v2
# learned this the expensive way (see the module docstring); the layout is the
# fix.
_GH, _PR, _MERGE = "gh", "pr", "merge"
# Shell metacharacters that END a command segment. shlex with
# punctuation_chars=True emits these as their own tokens, so a segment boundary
# is a token test rather than a regex on raw text.
_SEGMENT_BREAK = set("&|;()")


def merge_calls(target: str) -> list[tuple[int, str | None]]:
    """(pr_number, explicit_repo) for every `gh pr merge N` at a COMMAND position.

    The whole defence against counting a search as a merge lives here, and it is
    structural rather than a blacklist. After shell lexing, `rg 'gh pr merge 697'`
    is three tokens — `rg`, `-n`, and the single token `gh pr merge 697` — and
    that token does not open a segment. `printf 'gh pr merge 532'` is the same
    shape. A real merge lexes to `['gh','pr','merge','532',...]` with `gh` first.

    Lexing is per LINE because a heredoc body or an unbalanced quote elsewhere in
    a multi-line target would otherwise raise and discard the whole entry. An
    unlexable line is skipped, which UNDER-counts: the conservative direction for
    a census whose claim is that seats merge more than anyone believes.
    """
    calls: list[tuple[int, str | None]] = []
    for line in (target or "").splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        segment: list[str] = []
        for token in tokens + [";"]:
            if token and set(token) <= _SEGMENT_BREAK:
                calls.extend(_merge_in_segment(segment))
                segment = []
            else:
                segment.append(token)
    return calls


def _merge_in_segment(seg: list[str]) -> list[tuple[int, str | None]]:
    if len(seg) < 4 or seg[:3] != [_GH, _PR, _MERGE] or not seg[3].isdigit():
        return []
    repo = None
    for i, tok in enumerate(seg):
        if tok == "--repo" and i + 1 < len(seg):
            repo = seg[i + 1]
        elif tok.startswith("--repo="):
            repo = tok.split("=", 1)[1]
    return [(int(seg[3]), repo)]


def _epoch(ts: str) -> float:
    """ISO-8601 -> epoch seconds, tolerating the chain's nanosecond precision.

    The chain stamps `2026-09-04T03:49:06.986438057+00:00`; `fromisoformat` on
    3.10 rejects more than 6 fractional digits. GitHub stamps `...Z`.
    """
    ts = ts.replace("Z", "+00:00")
    if "." in ts:
        head, _, rest = ts.partition(".")
        m = re.match(r"(\d+)(.*)", rest)
        ts = f"{head}.{m.group(1)[:6]}{m.group(2)}"
    return datetime.fromisoformat(ts).timestamp()


def scan_chain(max_entries: int, cache: Path | None) -> list[dict]:
    """Every successful `outcome` entry whose target merges something.

    Walking 230k entries costs ~6 minutes at ~1.6 ms/hop, so the scan is
    cacheable. The cache holds only entries that already passed the command-
    position filter, which is why it is small enough to commit to a scratch path
    and re-read.
    """
    if cache and cache.is_file():
        return json.loads(cache.read_text())

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chain_walk import ChainWalker  # noqa: E402  (optional dep: needs the daemon)

    found: list[dict] = []
    for entry in ChainWalker().walk(max_entries=max_entries):
        if entry.get("eventType") != "outcome":
            continue
        data = entry.get("eventData") or {}
        if data.get("success") is not True or data.get("error"):
            continue
        calls = merge_calls(data.get("target") or "")
        if not calls:
            continue
        found.append({
            "action_id": data.get("action_id"),
            "plugin_id": data.get("plugin_id"),
            "ts": entry.get("timestamp"),
            "chain_position": entry.get("chainPosition"),
            "calls": [[n, r] for n, r in calls],
        })
    if cache:
        cache.write_text(json.dumps(found, indent=1))
    return found


def _substantive(items, min_body: int) -> list[dict]:
    out = []
    for it in items or []:
        if ((it.get("author") or {}).get("login")) in BOT_LOGINS:
            continue
        if len(it.get("body") or "") > min_body:
            out.append(it)
    return out


def _before_merge(items, min_body: int, merged_at: str, time_key: str):
    """Return (prior, unknown), never promoting post-merge text to prior review.

    Equal timestamps are ambiguous at GitHub's timestamp precision. An edited
    body can have changed after merge even if its creation time was earlier.
    """
    prior, unknown = [], []
    for item in _substantive(items, min_body):
        stamp = item.get(time_key)
        try:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            if instant.tzinfo is None or merged.tzinfo is None:
                raise ValueError("timestamp lacks timezone")
        except (AttributeError, TypeError, ValueError):
            unknown.append(item)
            continue
        if instant == merged or (instant < merged and item.get("includesCreatedEdit")):
            unknown.append(item)
        elif instant < merged:
            prior.append(item)
    return prior, unknown


def substantive_comments(pr: dict, min_body: int) -> list[dict]:
    return _before_merge(pr.get("comments"), min_body, pr.get("mergedAt"), "createdAt")[0]


def substantive_reviews(pr: dict, min_body: int) -> list[dict]:
    """Review objects carrying real text.

    Separate from comments because they are a separate channel with separate
    tooling — `gh pr review --comment` lands here and NOWHERE in `comments` —
    and because the two were conflated in the opposite direction by v1/v2,
    which assumed this one was empty. Counting it required measuring it.
    """
    return _before_merge(pr.get("reviews"), min_body, pr.get("mergedAt"), "submittedAt")[0]


def is_findings(title: str) -> bool:
    t = (title or "").lower()
    return any(t.startswith(p) for p in FINDINGS_PREFIXES)


def seat_merges(hits: list[dict], prs: list[dict], repo: str,
                window: float, back_slack: float = 30.0) -> dict:
    """PR number -> who merged it, corroborated against the GitHub merge instant.

    `hits` are chain outcome entries that already passed `merge_calls`. Passing
    that filter means the seat RAN a merge command that exited zero — it does
    NOT mean the merge happened, because the zero can belong to a wrapper
    (`... 2>&1 | tail -5; echo "rc=$?"` succeeds whether or not `gh` did). The
    corroboration below is what supplies the missing link: the outcome is
    accepted only if it lands within `window` seconds AFTER the PR's `mergedAt`.

    `back_slack` allows a small NEGATIVE gap for clock skew between the GitHub
    API's stamp and the local chain's. It is deliberately much tighter than
    `window`, because the outcome record is written when the command RETURNS and
    therefore genuinely follows the merge.

    Two rejections are reported rather than dropped, because each is a claim:
      * `uncorroborated` — a successful merge command with no merge instant near
        it. A masked failure and a stale retry both land here.
      * `foreign_repo`   — an explicit `--repo` naming something else. Without
        this, `gh pr merge 31 --repo dp-web4/private-context` matches THIS
        repo's #31, 26 days away, and reads as a wild clock error rather than
        the different repository it is.
    """
    merged_at = {p["number"]: p["mergedAt"] for p in prs if p.get("mergedAt")}
    best: dict[int, dict] = {}
    uncorroborated: list[dict] = []
    foreign = 0
    for hit in hits:
        try:
            outcome_ts = _epoch(hit["ts"])
        except (ValueError, TypeError):
            continue
        for number, explicit_repo in hit["calls"]:
            if explicit_repo and explicit_repo != repo:
                foreign += 1
                continue
            stamp = merged_at.get(number)
            if not stamp:
                continue
            gap = outcome_ts - _epoch(stamp)
            row = {"seat": hit["plugin_id"], "gap_s": round(gap, 2),
                   "action_id": hit["action_id"],
                   "chain_position": hit["chain_position"]}
            if -back_slack <= gap <= window:
                if number not in best or abs(gap) < abs(best[number]["gap_s"]):
                    best[number] = row
            else:
                uncorroborated.append(dict(row, number=number))
    return {"corroborated": best, "uncorroborated": uncorroborated,
            "foreign_repo": foreign}


def fetch(repo: str, limit: int) -> list[dict]:
    cmd = [
        "gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", str(limit),
        "--json", "number,title,mergedAt,mergedBy,comments,reviews",
    ]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def census(prs: list[dict], min_body: int, merges: dict) -> dict:
    corroborated = merges.get("corroborated") or {}
    rows = []
    for p in prs:
        if not p.get("mergedAt"):
            continue
        record = corroborated.get(p["number"]) or {}
        comments, uncertain_comments = _before_merge(p.get("comments"), min_body, p["mergedAt"], "createdAt")
        reviews, uncertain_reviews = _before_merge(p.get("reviews"), min_body, p["mergedAt"], "submittedAt")
        discussion = True if comments or reviews else (None if uncertain_comments or uncertain_reviews else False)
        rows.append({
            "number": p["number"],
            "title": p.get("title") or "",
            "mergedAt": p["mergedAt"],
            # A long comment is a discussion proxy, not proof of independent
            # review or that a reviewer saw this version of the work.
            "reviewed": discussion,
            "reviewed_via_comment": bool(comments),
            "reviewed_via_review": bool(reviews),
            "github_reviews": len(p.get("reviews") or []),
            "findings_class": is_findings(p.get("title") or ""),
            "mergedBy": (p.get("mergedBy") or {}).get("login"),
            "performed_by_seat": record.get("seat"),
            "seat_gap_s": record.get("gap_s"),
            "seat_action_id": record.get("action_id"),
        })
    n = len(rows)
    unrev = [r for r in rows if r["reviewed"] is False]
    unknown = [r for r in rows if r["reviewed"] is None]
    fnd = [r for r in rows if r["findings_class"]]
    code = [r for r in rows if not r["findings_class"]]
    seated = [r for r in rows if r["performed_by_seat"]]
    by_seat: dict[str, int] = {}
    for r in seated:
        by_seat[r["performed_by_seat"]] = by_seat.get(r["performed_by_seat"], 0) + 1
    gaps = sorted(abs(r["seat_gap_s"]) for r in seated)
    known = n - len(unknown)
    return {
        "n": n,
        "review_proxy_limitations": "Long pre-merge discussion does not prove independent review or head coverage; unknown timing is separate.",
        "performer_proxy_limitations": "Temporal association can be false positive or false negative; not a strict lower bound.",
        "unreviewed": len(unrev),
        "timing_unknown": len(unknown),
        "timing_known": known,
        "unreviewed_pct": round(100 * len(unrev) / known, 1) if known else None,
        "unreviewed_pct_lower": round(100 * len(unrev) / n, 1) if n else None,
        "unreviewed_pct_upper": round(100 * (len(unrev) + len(unknown)) / n, 1) if n else None,
        "github_review_objects": sum(r["github_reviews"] for r in rows),
        # The channel split is reported, not just pooled, because the pooling is
        # what hid the defect: `review_only` is exactly the set v1/v2 published
        # as unread.
        "reviewed_comment_only": sum(1 for r in rows
                                     if r["reviewed_via_comment"] and not r["reviewed_via_review"]),
        "reviewed_review_only": sum(1 for r in rows
                                    if r["reviewed_via_review"] and not r["reviewed_via_comment"]),
        "reviewed_both": sum(1 for r in rows
                             if r["reviewed_via_review"] and r["reviewed_via_comment"]),
        "findings_class": len(fnd),
        "findings_unreviewed": sum(1 for r in fnd if r["reviewed"] is False),
        "findings_timing_unknown": sum(1 for r in fnd if r["reviewed"] is None),
        "code_class": len(code),
        "code_unreviewed": sum(1 for r in code if r["reviewed"] is False),
        "code_timing_unknown": sum(1 for r in code if r["reviewed"] is None),
        "distinct_mergedBy": sorted({r["mergedBy"] for r in rows if r["mergedBy"]}),
        # The headline the credential cannot show: how many of these one GitHub
        # identity's merges were actually performed by a seat.
        "seat_performed": len(seated),
        "seat_performed_pct": round(100 * len(seated) / n, 1) if n else 0.0,
        "seat_performed_by": dict(sorted(by_seat.items())),
        "seat_performed_numbers": sorted(r["number"] for r in seated),
        "median_corroboration_gap_s": gaps[len(gaps) // 2] if gaps else None,
        # Successful merge COMMANDS with no merge instant near them. Not noise:
        # this is the bucket a wrapper-masked failure falls into, and it is the
        # reason `success: true` alone is not evidence of a merge.
        "uncorroborated_commands": len(merges.get("uncorroborated") or []),
        "foreign_repo_commands": merges.get("foreign_repo", 0),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="dp-web4/hestia")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--min-body", type=int, default=200,
                    help="comment length above which a comment counts as review")
    ap.add_argument("--max-chain", type=int, default=250000,
                    help="witness-chain entries to walk (~1.6 ms each)")
    ap.add_argument("--chain-cache", default=None,
                    help="reuse/store the chain scan; a full walk costs ~6 min")
    ap.add_argument("--merge-window", type=float, default=300.0,
                    help="seconds after mergedAt within which a seat's outcome "
                         "record corroborates that seat performed the merge")
    ap.add_argument("--since", default=None, help="only merges on/after this ISO date")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    prs = fetch(args.repo, args.limit)
    if args.since:
        prs = [p for p in prs if (p.get("mergedAt") or "") >= args.since]
    cache = Path(args.chain_cache) if args.chain_cache else None
    try:
        hits = scan_chain(args.max_chain, cache)
    except Exception as exc:  # daemon down, or chain_walk unavailable
        print(f"chain unreadable ({exc.__class__.__name__}: {exc}); "
              f"performer census SKIPPED — review census still valid",
              file=sys.stderr)
        hits = []
    merges = seat_merges(hits, prs, args.repo, args.merge_window)
    out = census(prs, args.min_body, merges)

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"merged PRs examined: {out['n']}")
    known_rate = f"{out['unreviewed_pct']}%" if out['unreviewed_pct'] is not None else "n/a"
    lower = out['unreviewed_pct_lower']
    upper = out['unreviewed_pct_upper']
    bounds = f"{lower}–{upper}%" if lower is not None else "n/a"
    print(f"  no qualifying pre-merge discussion in either channel "
          f"(non-bot body > {args.min_body} chars; proxy, not proof of review): "
          f"{out['unreviewed']} of {out['timing_known']} known ({known_rate}); bounds {bounds}")
    print(f"  qualifying discussion with timing unknown: {out['timing_unknown']}")
    print(f"  GitHub review objects, all PRs pooled: {out['github_review_objects']}")
    print(f"    read via comment only {out['reviewed_comment_only']}, "
          f"via review object only {out['reviewed_review_only']} "
          f"(v1/v2 published these as unread), both {out['reviewed_both']}")
    print(f"  findings-class: {out['findings_class']}, no discussion {out['findings_unreviewed']}, "
          f"timing unknown {out['findings_timing_unknown']}")
    print(f"  code-class:     {out['code_class']}, no discussion {out['code_unreviewed']}, "
          f"timing unknown {out['code_timing_unknown']}")
    print(f"  distinct mergedBy identities: {out['distinct_mergedBy']}")
    print(f"  temporally associated seat-merge candidates: {out['seat_performed']} "
          f"({out['seat_performed_pct']}%) {out['seat_performed_by']}")
    gap = out["median_corroboration_gap_s"]
    print(f"    corroborated within {args.merge_window:.0f}s of the merge instant; "
          f"median gap {f'{gap}s' if gap is not None else 'n/a (none found)'}")
    print(f"    successful merge commands NOT near any merge instant: "
          f"{out['uncorroborated_commands']} (wrapper-masked failure lives here)")
    print(f"    merge commands for another repo, excluded: "
          f"{out['foreign_repo_commands']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
