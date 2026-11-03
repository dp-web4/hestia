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

HISTORICAL CONTEXT: the earlier reader derived candidate evidence from the
witness chain, not log text. The historical claims below describe earlier
measurements, not validated conclusions from the conservative parser now here.

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
  layout: the merge pattern lives in the parser module and never on a command line,
  because the command line is itself the corpus.

Three filters stand between a chain entry and a counted merge, and each closes
a defect codex demonstrated:

  1. DIRECT COMMAND. Only a simple, direct candidate is recognized. Compound,
     quoted-separator, escaped, expanded, or otherwise ambiguous targets are
     unknown. Other commands may invoke wrappers and are unknown too. This
     deliberately loses recall; syntax alone does not prove execution.

  2. OUTCOME, SUCCESS, NO ERROR. Only `outcome` entries with `success is True`
     and a null `error` become candidates. Failed, malformed or unknown outcomes
     are unknown rather than proof that an attempted effect did not happen.
     v2 accepted an entry with NO `success` key at
     all, which meant `policy_decision` events — records of a merge the gate
     BLOCKED — were counted as merges performed.

  3. CORROBORATION AGAINST THE MERGE INSTANT. `success: true` is the shell
     wrapper's exit status, not the merge's: the #532 target ends
     `2>&1 | tail -5; echo "rc=$?"`, where the pipeline observes `tail` and the
     `echo` makes the shell succeed regardless. So a successful command is not
     evidence of a successful merge. A candidate is retained only when the
     outcome's timestamp falls within `--merge-window` seconds AFTER the PR's
     GitHub `mergedAt`. Commands that pass 1 and 2 but land nowhere near a
     merge instant are reported separately as `uncorroborated`. The previous
     30-row count predates the direct-only parser and is not a current result.

Earlier measurements reported a median gap under 5 seconds and a difference of
3 rows between 60-second and 30-minute windows. They have not been revalidated
for the direct-only parser or proved complete.

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
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if __package__:
    from .merge_review_parser import classify_outcomes, merge_calls
else:
    from merge_review_parser import classify_outcomes, merge_calls

BOT_LOGINS = {"chatgpt-codex-connector", "github-actions"}
# Titles the fleet uses for writeups, as opposed to behaviour changes. The split
# is the point of the census: these are the fleet's memory-of-record.
FINDINGS_PREFIXES = ("findings", "census", "docs", "shim ledger")

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
    instant = datetime.fromisoformat(ts)
    if instant.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return instant.timestamp()


_CACHE_SCHEMA = "merge-candidates-failed-unknown-v4"


def scan_chain(max_entries: int, cache: Path | None) -> list[dict]:
    """Candidate successful outcomes plus a count of unclassifiable outcomes.

    Walking 230k entries costs ~6 minutes at ~1.6 ms/hop, so the scan is
    cacheable. The versioned cache holds candidate metadata and an aggregate
    ambiguous count, not raw targets. Old caches lack the unknown classification
    and must not be silently reused as if they had it. A cache is a historical
    snapshot, not proof that the chain has not changed since it was written.
    """
    if cache and cache.is_file():
        saved = json.loads(cache.read_text())
        if not isinstance(saved, dict) or saved.get("schema") != _CACHE_SCHEMA or not isinstance(saved.get("hits"), list):
            raise ValueError("unversioned or incompatible chain cache; a fresh authorized scan is needed")
        for hit in saved["hits"]:
            if not isinstance(hit, dict) or "calls" not in hit:
                raise ValueError("invalid chain cache entry")
            calls = hit["calls"]
            if calls is None:
                count = hit.get("ambiguous_count")
                if type(count) is not int or count < 1:
                    raise ValueError("invalid ambiguous target count")
            elif not isinstance(calls, list) or any(
                not isinstance(call, list) or len(call) != 2 or type(call[0]) is not int
                or not (call[1] is None or isinstance(call[1], str)) for call in calls
            ):
                raise ValueError("invalid cached merge candidates")
        return saved["hits"]

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chain_walk import ChainWalker  # noqa: E402  (optional dep: needs the daemon)

    found = classify_outcomes(ChainWalker().walk(max_entries=max_entries))
    if cache:
        cache.write_text(json.dumps({"schema": _CACHE_SCHEMA, "hits": found}, indent=1))
    return found


def _author_class(item: dict) -> str:
    """Classify known bots, identifiable logins, and missing attribution.

    A non-bot-looking login is not proof of a human or independent reviewer.
    """
    author = item.get("author")
    if not isinstance(author, dict):
        return "unknown"
    login = author.get("login")
    if (author.get("__typename") == "Bot" or author.get("is_bot") is True or
            (isinstance(login, str) and (login.casefold() in BOT_LOGINS or login.casefold().endswith("[bot]")))):
        return "bot"
    return "identified" if isinstance(login, str) and login.strip() else "unknown"


def _substantive(items, min_body: int) -> list[dict]:
    out = []
    for it in items or []:
        if _author_class(it) != "identified":
            continue
        if len(it.get("body") or "") > min_body:
            out.append(it)
    return out


def _before_merge(items, min_body: int, merged_at: str, time_key: str):
    """Return (prior, unknown), never promoting post-merge text to prior review.

    Equal timestamps are ambiguous at GitHub's timestamp precision. An edited
    body can have changed after merge even if its creation time was earlier.
    This includes a body now below the length threshold: an edit could have
    shortened previously qualifying text, so it is not a known negative.
    """
    prior, unknown = [], []
    for item in items or []:
        author = _author_class(item)
        if author == "bot":
            continue
        substantive = len(item.get("body") or "") > min_body
        if not substantive and not item.get("includesCreatedEdit"):
            continue
        stamp = item.get(time_key)
        try:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            if instant.tzinfo is None or merged.tzinfo is None:
                raise ValueError("timestamp lacks timezone")
        except (AttributeError, TypeError, ValueError):
            unknown.append(item)
            continue
        if instant == merged or (instant < merged and (item.get("includesCreatedEdit") or author == "unknown")):
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
    """PR number -> temporally associated candidate, not a proven performer.

    `hits` are chain outcomes classified by `merge_calls`. A candidate is not
    proof that the shell reached or executed it; zero can belong to a wrapper
    (`... 2>&1 | tail -5; echo "rc=$?"` succeeds whether or not `gh` did). The
    timing association is not proof: a candidate is retained only if its outcome
    lands within `window` seconds AFTER the PR's `mergedAt`.

    `back_slack` allows a small NEGATIVE gap for clock skew between the GitHub
    API's stamp and the local chain's. It is deliberately much tighter than
    `window`, because the outcome record is written when the command RETURNS and
    therefore genuinely follows the merge.

    Two rejections are reported rather than dropped, because each is a claim:
      * `uncorroborated` — a successful merge command with no merge instant near
        it. A masked failure and a stale retry both land here.
      * `foreign_repo`   — an explicit `--repo` naming something else. Without
        this, a merge in `example/other` can match THIS
        repo's #31, 26 days away, and reads as a wild clock error rather than
        the different repository it is.
    """
    merged_at = {p["number"]: p["mergedAt"] for p in prs if p.get("mergedAt")}
    best: dict[int, dict] = {}
    uncorroborated: list[dict] = []
    foreign = 0
    ambiguous_outcomes = 0
    for hit in hits:
        if hit.get("calls") is None:
            ambiguous_outcomes += hit.get("ambiguous_count", 1)
            continue
        if not isinstance(hit.get("plugin_id"), str) or not hit["plugin_id"].strip():
            ambiguous_outcomes += 1
            continue
        try:
            outcome_ts = _epoch(hit["ts"])
        except (AttributeError, KeyError, ValueError, TypeError):
            ambiguous_outcomes += 1
            continue
        ambiguous_hit = False
        for number, explicit_repo in hit["calls"]:
            if explicit_repo is None:
                # The recorded target does not establish the working directory
                # or GitHub's repository selection at the time of invocation.
                ambiguous_hit = True
                continue
            if explicit_repo and explicit_repo != repo:
                foreign += 1
                continue
            stamp = merged_at.get(number)
            if not stamp:
                continue
            try:
                gap = outcome_ts - _epoch(stamp)
            except (AttributeError, ValueError, TypeError):
                ambiguous_hit = True
                continue
            row = {"seat": hit["plugin_id"], "gap_s": round(gap, 2),
                   "action_id": hit["action_id"],
                   "chain_position": hit["chain_position"]}
            if -back_slack <= gap <= window:
                if number not in best or abs(gap) < abs(best[number]["gap_s"]):
                    best[number] = row
            else:
                uncorroborated.append(dict(row, number=number))
        if ambiguous_hit:
            ambiguous_outcomes += 1
    return {"corroborated": best, "uncorroborated": uncorroborated,
            "foreign_repo": foreign, "ambiguous_outcomes": ambiguous_outcomes}


def fetch(repo: str, limit: int) -> list[dict]:
    cmd = [
        "gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", str(limit),
        "--json", "number,title,mergedAt,mergedBy,comments,reviews",
    ]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def census(prs: list[dict], min_body: int, merges: dict | None) -> dict:
    # None means the source could not be observed; an empty mapping is a
    # successful observation with no matches. Neither proves who merged.
    performer_observed = merges is not None
    corroborated = (merges.get("corroborated") or {}) if performer_observed else {}
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
            # A timing match is a candidate association, never proof of who merged.
            "performed_by_seat": None,
            "candidate_seat": record.get("seat"),
            "seat_gap_s": record.get("gap_s"),
            "seat_action_id": record.get("action_id"),
        })
    n = len(rows)
    unrev = [r for r in rows if r["reviewed"] is False]
    unknown = [r for r in rows if r["reviewed"] is None]
    fnd = [r for r in rows if r["findings_class"]]
    code = [r for r in rows if not r["findings_class"]]
    seated = [r for r in rows if r["candidate_seat"]]
    by_seat: dict[str, int] = {}
    for r in seated:
        by_seat[r["candidate_seat"]] = by_seat.get(r["candidate_seat"], 0) + 1
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
        "performer_status": ("unavailable" if not performer_observed else
                             "partial" if merges.get("ambiguous_outcomes", 0) else "observed"),
        "ambiguous_outcomes": merges.get("ambiguous_outcomes", 0) if performer_observed else None,
        # Preserve legacy keys as explicitly unknown, not as actor attribution.
        "seat_performed": None,
        "seat_performed_pct": None,
        "seat_performed_by": None,
        "seat_performed_numbers": None,
        "seat_candidate_count": len(seated) if performer_observed else None,
        "seat_candidate_by": dict(sorted(by_seat.items())) if performer_observed else None,
        "seat_candidate_pct": round(100 * len(seated) / n, 1) if performer_observed and n else None,
        "seat_candidate_numbers": sorted(r["number"] for r in seated) if performer_observed else None,
        "median_corroboration_gap_s": gaps[len(gaps) // 2] if gaps else None,
        # Successful merge COMMANDS with no merge instant near them. Not noise:
        # this is the bucket a wrapper-masked failure falls into, and it is the
        # reason `success: true` alone is not evidence of a merge.
        "uncorroborated_commands": len(merges.get("uncorroborated") or []) if performer_observed else None,
        "foreign_repo_commands": merges.get("foreign_repo", 0) if performer_observed else None,
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
                         "record is associated with a candidate")
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
        hits = None
    merges = seat_merges(hits, prs, args.repo, args.merge_window) if hits is not None else None
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
    if out["performer_status"] == "unavailable":
        print("  performer evidence unavailable (not a measured zero)")
        return 0
    if out["performer_status"] == "partial":
        print(f"  performer evidence partial: {out['ambiguous_outcomes']} outcome(s) could not be "
              "classified or attributed; they cannot be linked reliably to individual PRs")
    percentage = f"{out['seat_candidate_pct']}%" if out["seat_candidate_pct"] is not None else "n/a"
    print(f"  temporally associated seat-merge candidates: {out['seat_candidate_count']} "
          f"({percentage}) {out['seat_candidate_by']}")
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
