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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_review_census import (  # noqa: E402
    census, is_findings, seat_merges, substantive_comments,
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


def witness(action_id: str, plugin: str, target: str, success: str = "true") -> str:
    """One witness outcome record, in the shape the fire logs actually emit."""
    return (
        '  {"action_id": "%s", "closure_claims": [], "error": null,\n'
        '   "magnitude": 0.8, "plugin_id": "%s",\n'
        '   "role_lct": "role:constellation:mesh-worker", "success": %s,\n'
        '   "target": "%s", "tool_name": "Bash"}\n'
        % (action_id, plugin, success, target)
    )


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


def arm_seat_is_read_from_the_record_not_the_filename() -> None:
    """A record quoted in another seat's log still names the seat that ran it.

    This is the #532 case and it is why the published table was wrong: the only
    copies of that record live in two CODEX logs, and the record itself says
    `claude-code`. Sabotage: guess the seat from `path.name.split("-")[0]` and
    this arm reds with codex, reproducing the original defect exactly.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260826-172116.log").write_text(
            "reading the witness chain\n"
            + witness("18091cec-6430-449a-9400-7d48100fee6a", "claude-code",
                      "gh pr merge 532 --squash --delete-branch")
        )
        found = seat_merges(logs)
        check("seat comes from plugin_id, not the log filename",
              found.get(532, {}).get("seat") == "claude-code", f"got {found.get(532)}")


def arm_quoting_a_record_does_not_double_count() -> None:
    """The same merge, quoted in three logs, is still one merge by one seat.

    De-duplication is on `action_id`, so contamination by quoting cannot change
    the count OR the attribution. Sabotage: key the dict on (file, pr) and this
    arm reds, because the same merge appears three times.
    """
    rec = witness("4ff76068-d585-4bfc-b1ce-761eccbe401d", "kimi-code",
                  "gh pr merge 697 --squash --delete-branch")
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "kimi-20260827-231037.log").write_text("ran it\n" + rec)
        (logs / "codex-20260903-201737.log").write_text("grepped the archive\n" + rec)
        (logs / "claude-20260904-031812.log").write_text("also quoted it\n" + rec)
        found = seat_merges(logs)
        check("quoted record attributes to its own seat",
              found.get(697, {}).get("seat") == "kimi-code", f"got {found.get(697)}")
        check("quoted record is not double-counted",
              found.get(697, {}).get("action_ids") == ["4ff76068-d585-4bfc-b1ce-761eccbe401d"],
              f"got {found.get(697, {}).get('action_ids')}")


def arm_prose_and_diffs_are_not_merges() -> None:
    """The contamination the first version could not see.

    Its filter keyed on `.log-` and `/logs/`, so grep output was excluded but a
    DIFF, a PR body, or this tool's own docstring was not — and every one of
    those contains the literal string `gh pr merge 697`. Only a witness record
    counts now, so none of these register. Sabotage: match on raw text again and
    all three of these lines become merges.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260903-201737.log").write_text(
            "+`gh pr merge 697 --squash` running in kimi-code's own wake. The only\n"
            "| #532 | codex | ran gh pr merge 532 |\n"
            '            "exec gh pr merge 350 --squash\\n"\n'
            "2026-07-23T07:13:32 a historical timestamp from a quoted primer\n"
        )
        found = seat_merges(logs)
        check("prose/diff/table mentions carry no record", found == {}, f"got {found}")


def arm_disagreeing_records_are_a_conflict_not_a_coin_flip() -> None:
    """Two records, two seats, one PR: report it, do not take the first.

    The original took `[0]` of a candidate list and so published one seat with
    no signal that another was equally supported. Sabotage: return the first
    seat instead of None and this arm reds.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260811-145154.log").write_text(
            witness("aaaaaaaa-0000-0000-0000-000000000001", "codex", "gh pr merge 350 --squash")
            + witness("bbbbbbbb-0000-0000-0000-000000000002", "kimi-code", "gh pr merge 350 --squash")
        )
        found = seat_merges(logs)
        check("disagreement is not attributed", found[350]["seat"] is None, f"got {found[350]}")
        check("disagreement names both seats",
              found[350]["conflict"] == ["codex", "kimi-code"], f"got {found[350]}")


def arm_failed_merge_command_is_not_a_merge() -> None:
    """`success: false` is an attempt, not a landing.

    Sabotage: drop the success check and a refused merge counts as performed.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260811-145154.log").write_text(
            witness("cccccccc-0000-0000-0000-000000000003", "codex",
                    "gh pr merge 999 --squash", success="false")
        )
        check("failed merge is not counted", seat_merges(logs) == {}, "got a merge")


def arm_codex_exec_lines_are_execution_too() -> None:
    """codex logs carry no witness JSON — only `/bin/bash -lc` exec echoes.

    A record-only parser silently drops every codex merge, which is how #236
    went missing. Sabotage: parse witness records only and this arm reds.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260807-015109.log").write_text(
            "some prose\n"
            "/bin/bash -lc \"gh pr merge 236 --merge --subject 'Merge #236' && "
            "gh pr view 236 --json state\" in /mnt/c/exe/projects/ai-agents/hestia\n"
        )
        found = seat_merges(logs)
        check("exec-line merge is found", found.get(236, {}).get("seat") == "codex",
              f"got {found.get(236)}")
        check("exec-line basis is labelled weaker",
              found.get(236, {}).get("basis") == "filename", f"got {found.get(236)}")


def arm_searching_for_a_merge_is_not_performing_one() -> None:
    """The third shape of the self-reference trap, and the sharpest.

    `rg 'gh pr merge 697' logs/` is a GENUINE, anchored exec line in codex's own
    transcript — it just happens to be a search for the string rather than a
    merge. It is real execution, so neither the quoted-text filter nor the
    exec-line anchor rejects it. This exact line at
    codex-20260903-201737.log:2132 would credit codex with merging both #697 and
    #532 while it was REVIEWING the census that measures merges.

    Sabotage: drop the SEARCH_TOOL guard and this arm reds with two merges.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260903-201737.log").write_text(
            "/bin/bash -lc \"rg -n --glob '*.log' 'gh pr merge 697' "
            "/home/dp/.local/state/hestia-mesh/logs | head -80\" in /tmp/review\n"
            "/bin/bash -lc \"grep -n 'gh pr merge 532' logs/\" in /tmp/review\n"
        )
        check("searching for a merge is not a merge", seat_merges(logs) == {},
              f"got {seat_merges(logs)}")


def arm_grep_output_never_starts_its_line() -> None:
    """A quoted exec survives into another log behind a `<path>.log-<n>-` prefix.

    Two guards reject it and they are REDUNDANT, which I verified rather than
    assumed: the `^` anchor on EXEC_LINE, and GREP_PREFIX. Removing either one
    alone leaves this arm green, because `^` without re.MULTILINE anchors to the
    string start whether you call `match` or `search`. The arm reds only when
    BOTH are removed at once — so it is evidence for the pair, not for either.

    Saying that precisely is the point. The arm this one replaces claimed to
    prove a guard it could not have failed on, and that false credit is what let
    the contamination ship.
    """
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d)
        (logs / "codex-20260831-175622.log").write_text(
            "/home/dp/.local/state/hestia-mesh/logs/codex-20260807-015109.log-794-"
            "/bin/bash -lc \"gh pr merge 236 --merge\" in /mnt/c\n"
        )
        check("quoted exec line is not a merge", seat_merges(logs) == {},
              f"got {seat_merges(logs)}")


def main() -> int:
    for arm in (
        arm_bot_advert_is_not_review,
        arm_short_human_comment_is_not_review,
        arm_class_split,
        arm_headline_rates,
        arm_mergedby_cannot_separate_seats,
        arm_seat_is_read_from_the_record_not_the_filename,
        arm_quoting_a_record_does_not_double_count,
        arm_prose_and_diffs_are_not_merges,
        arm_disagreeing_records_are_a_conflict_not_a_coin_flip,
        arm_failed_merge_command_is_not_a_merge,
        arm_codex_exec_lines_are_execution_too,
        arm_searching_for_a_merge_is_not_performing_one,
        arm_grep_output_never_starts_its_line,
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
