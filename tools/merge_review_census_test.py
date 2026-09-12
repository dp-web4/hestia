#!/usr/bin/env python3
"""Arms for merge_review_census. Each arm asserts one claim from the findings doc.

Run: python3 tools/merge_review_census_test.py

Sabotage-verified — the mutation that would make each arm vacuous is named in
the arm's docstring, and each arm fails on its own assert rather than on a
shared fixture, so a red arm names the defect.

The performer arms are all NEGATIVE-heavy on purpose. Every defect codex found
in v1 and v2 of this tool was a FALSE POSITIVE: text that looked like a merge
and was counted as one. An arm that only proves a real merge is detected would
have passed against every broken version. So each arm below pairs the positive
with the near-miss that used to beat it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_review_census import (  # noqa: E402
    census, is_findings, merge_calls, seat_merges, substantive_comments,
    substantive_reviews,
)

FAILURES: list[str] = []
REPO = "dp-web4/hestia"


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
        "reviews": [{"author": {"login": a}, "body": b, "state": "COMMENTED"}
                    for a, b in reviews],
    }


def arm_a_review_object_is_review() -> None:
    """The defect v1/v2 shipped: `gh pr review --comment` leaves comments EMPTY.

    v1/v2 counted the comment channel only, having ASSERTED the review channel
    was empty fleet-wide. It is not — 134 of 551 merged PRs carry one — and the
    64 PRs reviewed only there were published as unread.

    Sabotage: drop substantive_reviews from the `reviewed` disjunction and this
    goes red, restoring the shipped defect exactly.
    """
    reviewed_only_there = pr(60, "findings: a", "2026-08-01T00:00:00Z",
                             reviews=[("dp-web4", "x" * 300)])
    check("review object with no comment IS review",
          substantive_comments(reviewed_only_there, 200) == []
          and len(substantive_reviews(reviewed_only_there, 200)) == 1
          and census([reviewed_only_there], 200, {})["unreviewed"] == 0)

    bot = pr(61, "findings: b", "2026-08-01T00:00:00Z",
             reviews=[("chatgpt-codex-connector", "x" * 300)])
    check("a bot review object is still not review",
          census([bot], 200, {})["unreviewed"] == 1)

    stub = pr(62, "findings: c", "2026-08-01T00:00:00Z", reviews=[("dp-web4", "lgtm")])
    check("a stub review object is not review",
          census([stub], 200, {})["unreviewed"] == 1)


def arm_channel_split_is_reported_not_pooled() -> None:
    """Pooling the two channels is what hid the defect, so the split is output.

    Sabotage: report only the union and this goes red on reviewed_review_only,
    which is the number that names the correction.
    """
    prs = [
        pr(70, "a", "2026-08-01T00:00:00Z", comments=[("dp-web4", "x" * 300)]),
        pr(71, "b", "2026-08-02T00:00:00Z", reviews=[("dp-web4", "x" * 300)]),
        pr(72, "c", "2026-08-03T00:00:00Z", comments=[("dp-web4", "x" * 300)],
           reviews=[("dp-web4", "y" * 300)]),
        pr(73, "d", "2026-08-04T00:00:00Z"),
    ]
    out = census(prs, 200, {})
    check("channel split reported",
          out["reviewed_comment_only"] == 1 and out["reviewed_review_only"] == 1
          and out["reviewed_both"] == 1 and out["unreviewed"] == 1, str(out)[:200])


def hit(plugin, target, ts, action_id="a1", pos=1):
    """One chain outcome entry, in the shape `scan_chain` yields."""
    return {"action_id": action_id, "plugin_id": plugin, "ts": ts,
            "chain_position": pos, "calls": merge_calls(target)}


# --------------------------------------------------------------------------
# REVIEW half
# --------------------------------------------------------------------------

def arm_bot_advert_is_not_review() -> None:
    """The codex connector's 90-char advert must not count as review.

    Sabotage: drop the BOT_LOGINS filter, or set min_body to 0, and this goes
    red because the advert alone would mark the PR reviewed.
    """
    advert = ("To use Codex here, [create an environment for this repo]"
              "(https://chatgpt.com/codex/cloud/settings/environments).")
    p = pr(1, "findings: x", "2026-08-01T00:00:00Z",
           comments=[("chatgpt-codex-connector", advert)])
    check("bot advert is not review", substantive_comments(p, 200) == [])


def arm_short_human_comment_is_not_review() -> None:
    """A human one-liner under the threshold is not review either.

    Sabotage: change the comparison to `>= 0` and this goes red.
    """
    p = pr(2, "fix: y", "2026-08-01T00:00:00Z", comments=[("dp-web4", "lgtm")])
    check("short human comment is not review", substantive_comments(p, 200) == [])
    long = pr(3, "fix: y", "2026-08-01T00:00:00Z", comments=[("dp-web4", "x" * 300)])
    check("long human comment IS review", len(substantive_comments(long, 200)) == 1)


def arm_class_split() -> None:
    """findings-class is a title prefix, and 'fix'/'feat' are not in it.

    Sabotage: add "fix" to FINDINGS_PREFIXES and this goes red.
    """
    check("findings-class split", is_findings("findings: a") and is_findings("census of b")
          and not is_findings("fix(census): c"))


def arm_headline_rates() -> None:
    """The published percentages come from the row set, not a hand count.

    Sabotage: swap the unreviewed numerator for the reviewed one and this goes
    red on the 66.7 figure.
    """
    prs = [
        pr(10, "findings: a", "2026-08-01T00:00:00Z"),
        pr(11, "findings: b", "2026-08-02T00:00:00Z", comments=[("dp-web4", "x" * 300)]),
        pr(12, "fix: c", "2026-08-03T00:00:00Z"),
    ]
    out = census(prs, 200, {})
    check("headline rates", out["n"] == 3 and out["unreviewed"] == 2
          and out["unreviewed_pct"] == 66.7 and out["findings_class"] == 2
          and out["code_class"] == 1, str(out["unreviewed_pct"]))


def arm_mergedby_cannot_separate_seats() -> None:
    """The whole reason the performer census exists: one credential, many actors.

    Sabotage: give the fixture two logins and this goes red — which is the
    point, because on the real repo it never has two.
    """
    prs = [pr(20, "a", "2026-08-01T00:00:00Z"), pr(21, "b", "2026-08-02T00:00:00Z")]
    check("mergedBy collapses every seat to one identity",
          census(prs, 200, {})["distinct_mergedBy"] == ["dp-web4"])


# --------------------------------------------------------------------------
# PERFORMER half — command position
# --------------------------------------------------------------------------

def arm_real_merge_is_at_a_command_position() -> None:
    """The positive case, in the shapes the chain actually holds.

    Sabotage: require `seg[0] == 'gh'` to be the token at index 1 and this goes
    red on every form.
    """
    forms = {
        "gh pr merge 532 --squash --delete-branch": [(532, None)],
        "cd /repo && gh pr merge 353 --merge": [(353, None)],
        "set -euo pipefail\ngh pr merge 729 --merge --delete-branch=false\ngit fetch":
            [(729, None)],
        "gh pr merge 796 --repo dp-web4/hestia --squash": [(796, "dp-web4/hestia")],
        "gh pr ready 490 && gh pr merge 490 --merge": [(490, None)],
    }
    for target, want in forms.items():
        check(f"command position: {target[:34]!r}", merge_calls(target) == want,
              str(merge_calls(target)))


def arm_searching_for_a_merge_is_not_performing_one() -> None:
    """codex #2: a witness record whose target SEARCHES for a merge string.

    v2 applied its search guard only to the codex-exec branch, so these passed
    on the record branch — the basis the finding treats as authoritative. These
    are the exact targets codex exercised, taken verbatim from the chain.

    Sabotage: accept a merge token anywhere in the token list rather than at a
    segment head, and all four go red. Note no arm here names `rg` or `grep`:
    the defence is position, not a tool blacklist, so `printf` is caught by the
    same rule that catches `rg` without ever being enumerated.
    """
    for target in [
        "rg -n --glob '*.log' 'gh pr merge 532' /home/dp/.local/state/hestia-mesh/logs",
        "rg -n --glob '*.log' 'gh pr merge 697' /home/dp/.local/state/hestia-mesh/logs",
        "printf 'gh pr merge 532'",
        'grep -rhE "gh pr merge 236" /logs/ 2>/dev/null | head',
    ]:
        check(f"search is not a merge: {target[:38]!r}", merge_calls(target) == [])


def arm_the_census_reading_itself_is_not_a_merge() -> None:
    """The self-contamination case, as it appears in the chain TODAY.

    This is the target codex ran while reviewing #891 — a heredoc that imports
    this very module. Under v2's log grep it produced a #353 attribution and
    flipped the published census to AMBIGUOUS with no merge occurring.

    Sabotage: lex the whole target as one string instead of per line, or match
    the pattern against raw text, and this goes red.
    """
    target = ("python3 - <<'PY'\nfrom pathlib import Path\nimport sys\n"
              "sys.path.insert(0, 'tools')\nimport merge_review_census as m\n"
              "# gh pr merge 353 appears in the docstring\nPY")
    check("reading the census is not merging", merge_calls(target) == [],
          str(merge_calls(target)))


def arm_unlexable_target_is_dropped_not_guessed() -> None:
    """An unbalanced quote must under-count, never fall back to text matching.

    Sabotage: replace the ValueError guard with a regex fallback and this goes
    red — which is the whole v1 failure mode returning.
    """
    check("unlexable line is skipped", merge_calls("gh pr merge 5 \"unclosed") == [])


# --------------------------------------------------------------------------
# PERFORMER half — corroboration
# --------------------------------------------------------------------------

def arm_wrapper_success_needs_a_merge_instant() -> None:
    """codex #3: `success: true` is the SHELL's exit code, not the merge's.

    The target is #532's real one: `2>&1 | tail -5; echo "rc=$?"` exits zero
    whether or not `gh` did. The two hits below are byte-identical in every
    field the parser reads EXCEPT the timestamp. Only the one that lands beside
    the merge instant counts; the other is reported as uncorroborated.

    Sabotage: drop the window test in seat_merges and this goes red, because
    both hits would be accepted and the masked failure would be a merge.
    """
    target = 'gh pr merge 532 --squash --delete-branch 2>&1 | tail -5; echo "rc=$?"'
    prs = [pr(532, "x", "2026-08-19T05:00:51Z")]

    real = seat_merges([hit("claude-code", target, "2026-08-19T05:00:56Z")],
                       prs, REPO, window=300.0)
    check("outcome beside the merge instant is a merge",
          set(real["corroborated"]) == {532}
          and real["corroborated"][532]["seat"] == "claude-code")

    masked = seat_merges([hit("claude-code", target, "2026-08-19T09:00:56Z")],
                         prs, REPO, window=300.0)
    check("identical success far from the instant is NOT a merge",
          masked["corroborated"] == {} and len(masked["uncorroborated"]) == 1,
          str(masked))


def arm_merge_before_the_instant_is_rejected() -> None:
    """An outcome recorded BEFORE the merge cannot have caused it.

    The outcome row is written when the command returns, so it follows the
    merge; only a small skew slack is allowed backwards.

    Sabotage: widen back_slack to the full window and this goes red.
    """
    prs = [pr(700, "x", "2026-08-28T06:00:00Z")]
    early = seat_merges([hit("kimi-code", "gh pr merge 700 --squash",
                             "2026-08-28T05:50:00Z")], prs, REPO, window=3600.0)
    check("outcome 10 min BEFORE the instant is rejected",
          early["corroborated"] == {}, str(early))


def arm_foreign_repo_is_not_this_repos_pr() -> None:
    """A merge in another repo must not match this repo's same-numbered PR.

    Without the --repo test, `gh pr merge 31 --repo dp-web4/private-context`
    matches hestia's #31 with a 26-DAY gap and reads as a clock fault.

    Sabotage: ignore explicit_repo and this goes red on foreign_repo == 0.
    """
    prs = [pr(31, "x", "2026-07-23T00:00:00Z")]
    out = seat_merges([hit("codex", "gh pr merge 31 --repo dp-web4/private-context "
                                    "--merge --delete-branch",
                           "2026-08-17T22:42:22Z")], prs, REPO, window=300.0)
    check("foreign-repo merge is excluded, not mis-dated",
          out["corroborated"] == {} and out["foreign_repo"] == 1
          and out["uncorroborated"] == [], str(out))


def arm_nearest_outcome_wins_over_a_retry() -> None:
    """Two seats both ran a merge command; the one at the instant performed it.

    A retry after a failed attempt is a real pattern in the chain. The census
    must attribute to the outcome that coincides with the merge, not to
    whichever it scanned first.

    Sabotage: keep the first hit instead of the nearest and this goes red,
    because the walk yields newest-first.
    """
    prs = [pr(800, "x", "2026-09-01T00:00:00Z")]
    out = seat_merges(
        [hit("codex", "gh pr merge 800 --merge", "2026-09-01T00:04:00Z", "far", 2),
         hit("claude-code", "gh pr merge 800 --merge", "2026-09-01T00:00:03Z", "near", 1)],
        prs, REPO, window=300.0)
    check("nearest outcome wins", set(out["corroborated"]) == {800}
          and out["corroborated"][800]["seat"] == "claude-code"
          and out["corroborated"][800]["action_id"] == "near", str(out))


def arm_a_seat_merge_is_reported_against_the_credential() -> None:
    """End to end: mergedBy says dp-web4, the census says a seat did it.

    This is the finding in one row. Sabotage: return an empty dict from
    seat_merges and this goes red on seat_performed.
    """
    prs = [pr(532, "fix: x", "2026-08-19T05:00:51Z"),
           pr(533, "fix: y", "2026-08-19T06:00:00Z")]
    merges = seat_merges([hit("claude-code", "gh pr merge 532 --squash",
                              "2026-08-19T05:00:56Z")], prs, REPO, window=300.0)
    out = census(prs, 200, merges)
    check("seat merge reported behind one credential",
          out["distinct_mergedBy"] == ["dp-web4"] and out["seat_performed"] == 1
          and out["seat_performed_by"] == {"claude-code": 1}
          and out["seat_performed_numbers"] == [532]
          and out["rows"][0]["performed_by_seat"] == "claude-code"
          and out["rows"][1]["performed_by_seat"] is None, str(out["seat_performed_by"]))


def arm_chain_unreadable_leaves_the_review_census_intact() -> None:
    """The review half must not depend on the daemon being up.

    Sabotage: read merges before computing `reviewed` and this goes red when
    the chain is empty.
    """
    prs = [pr(40, "findings: a", "2026-08-01T00:00:00Z"),
           pr(41, "fix: b", "2026-08-02T00:00:00Z", comments=[("dp-web4", "x" * 300)])]
    out = census(prs, 200, seat_merges([], prs, REPO, window=300.0))
    check("review census survives an unreadable chain",
          out["unreviewed"] == 1 and out["seat_performed"] == 0)


def main() -> int:
    print("merge_review_census arms")
    for name, fn in sorted(globals().items()):
        if name.startswith("arm_"):
            print(f"\n{name}")
            fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all arms pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
