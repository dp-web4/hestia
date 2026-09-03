#!/usr/bin/env python3
"""Arms for merge_review_census. Each arm asserts one claim from the findings doc.

Run: python3 tools/merge_review_census_test.py

Sabotage-verified — the mutation that would make each arm vacuous is named in
the arm's docstring, and each arm fails on its own assert rather than on a
shared fixture, so a red arm names the defect.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_review_census import (  # noqa: E402
    census, is_findings, seat_merges, substantive_comments, wake_span,
)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILURES.append(name)


def pr(number, title, merged, comments=(), reviews=(), by="dp-web4"):
    return {
        "number": number, "title": title, "mergedAt": merged,
        "mergedBy": {"login": by},
        "comments": [{"author": {"login": a}, "body": b} for a, b in comments],
        "reviews": list(reviews),
    }


def arm_bot_advert_is_not_review() -> None:
    """The codex connector's 90-char advert must not count as review.

    Sabotage: drop the BOT_LOGINS filter, or set --min-body to 0, and this arm
    goes red because the advert alone would mark the PR reviewed.
    """
    advert = "To use Codex here, [create an environment for this repo](https://chatgpt.com/codex/cloud/settings/environments)."
    p = pr(1, "findings: x", "2026-09-03T04:47:00Z", [("chatgpt-codex-connector", advert)])
    check("bot advert is not review", substantive_comments(p, 200) == [])


def arm_short_human_comment_is_not_review() -> None:
    """A one-line human "lgtm" is not the review this census is counting.

    Sabotage: lower min_body below the comment length and the arm goes red.
    """
    p = pr(2, "findings: y", "2026-09-03T04:47:00Z", [("dp-web4", "nice, lgtm")])
    check("short human comment is not review", substantive_comments(p, 200) == [])
    long = pr(3, "gate: z", "2026-09-03T04:47:00Z", [("dp-web4", "x" * 201)])
    check("long human comment IS review", len(substantive_comments(long, 200)) == 1)


def arm_class_split() -> None:
    """findings-class and code-class must be separable by title.

    Sabotage: add "gate" to FINDINGS_PREFIXES and the stratification the doc
    reports collapses to one bucket.
    """
    check("findings title classified", is_findings("findings: the drain"))
    check("census title classified", is_findings("census: the lapse rate"))
    check("gate title NOT findings", not is_findings("gate: a ruling projects"))
    check("fix title NOT findings", not is_findings("fix(watch): primer_spent"))


def arm_headline_rates() -> None:
    """The census reports per-class unreviewed counts, not just a pooled rate.

    Sabotage: report only the pooled rate and this arm cannot distinguish a
    fleet that reviews nothing from one that reviews code and skips findings —
    which is the whole finding.
    """
    prs = [
        pr(10, "findings: a", "2026-09-03T04:47:00Z"),
        pr(11, "findings: b", "2026-09-03T04:47:10Z"),
        pr(12, "gate: c", "2026-09-03T04:47:20Z", [("dp-web4", "x" * 500)]),
    ]
    out = census(prs, 200, {})
    check("n counted", out["n"] == 3, f"got {out['n']}")
    check("unreviewed counted", out["unreviewed"] == 2, f"got {out['unreviewed']}")
    check("findings all unreviewed", out["findings_unreviewed"] == 2)
    check("code fully reviewed", out["code_unreviewed"] == 0)


def arm_mergedby_cannot_separate_seats() -> None:
    """One identity for every performer — the census must SAY so, not hide it.

    Sabotage: attribute performer from mergedBy and this arm goes red, because
    a seat-performed merge and a human merge are the same login.
    """
    prs = [
        pr(20, "findings: a", "2026-09-03T04:47:00Z", by="dp-web4"),
        pr(21, "gate: b", "2026-09-03T04:47:10Z", by="dp-web4"),
    ]
    out = census(prs, 200, {})
    check("all merges wear one identity", out["distinct_mergedBy"] == ["dp-web4"])
    check("no seat claimed without a log", out["seat_performed"] == [])


def arm_seat_merge_join_needs_the_span() -> None:
    """A seat merge is attributed only when the merge falls inside its wake.

    This is the #697 case: kimi ran `gh pr merge 697` and GitHub logged
    dp-web4. Sabotage: attribute on the log CONTAINING the number regardless of
    time, and an unrelated later merge of the same number is misattributed.
    """
    merges = {
        697: [("kimi", datetime(2026, 8, 28, 5, 54, tzinfo=timezone.utc),
                       datetime(2026, 8, 28, 6, 30, tzinfo=timezone.utc))],
    }
    inside = census([pr(697, "fix(witness): fail-open", "2026-08-28T06:03:42Z")], 200, merges)
    check("merge inside the wake is seat-attributed",
          inside["seat_performed"] == [(697, "kimi")], f"got {inside['seat_performed']}")

    outside = census([pr(697, "fix(witness): fail-open", "2026-08-29T06:03:42Z")], 200, merges)
    check("merge outside the wake is NOT attributed",
          outside["seat_performed"] == [], f"got {outside['seat_performed']}")


def arm_quoted_merge_is_not_a_merge() -> None:
    """A log that greps the archive quotes other logs' merge commands.

    This is the contamination that made 16 logs look like merge performers when
    exactly one was. Sabotage: drop the QUOTED filter and the quoting log is
    credited with a merge it only ever read.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "kimi-20260827-231037.log").write_text(
            "2026-08-28T05:54:47 start\n"
            "exec gh pr merge 697 --squash --delete-branch\n"
            "2026-08-28T06:30:37 end\n"
        )
        (logs / "codex-20260831-175622.log").write_text(
            "2026-08-31T18:00:00 start\n"
            "/home/dp/.local/state/hestia-mesh/logs/codex-20260807-015109.log-794-"
            "gh pr merge 236 --merge\n"
            "2026-08-31T18:30:00 end\n"
        )
        found = seat_merges(logs)
        check("real merge command found", 697 in found, f"got {sorted(found)}")
        check("quoted merge command ignored", 236 not in found, f"got {sorted(found)}")


def arm_span_is_read_from_the_body() -> None:
    """The filename is local time, the body is UTC — a 7h trap.

    Sabotage: derive the span from the filename and the #697 join fails, which
    is exactly the false non-overlap this census hit on first read.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "kimi-20260827-231037.log"
        p.write_text("2026-08-28T05:54:47 a\n2026-08-28T06:30:37 b\n")
        span = wake_span(p)
        check("span read from body, not filename",
              span is not None and span[0].hour == 5 and span[1].hour == 6,
              f"got {span}")
        check("span contains the 06:03Z merge",
              span is not None
              and span[0] <= datetime(2026, 8, 28, 6, 3, 42, tzinfo=timezone.utc) <= span[1])


def main() -> int:
    for arm in (
        arm_bot_advert_is_not_review,
        arm_short_human_comment_is_not_review,
        arm_class_split,
        arm_headline_rates,
        arm_mergedby_cannot_separate_seats,
        arm_seat_merge_join_needs_the_span,
        arm_quoted_merge_is_not_a_merge,
        arm_span_is_read_from_the_body,
    ):
        print(f"{arm.__name__}:")
        arm()
    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}: {', '.join(FAILURES)}")
        return 1
    print("all arms passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
