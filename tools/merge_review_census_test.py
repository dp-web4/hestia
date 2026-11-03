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
    _CACHE_SCHEMA, census, is_findings, merge_calls, scan_chain, seat_merges, substantive_comments,
    substantive_reviews,
)
from merge_review_parser import classify_outcomes  # noqa: E402

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
        "comments": [{"author": {"login": a}, "body": b,
                      "createdAt": "2020-01-01T00:00:00Z"} for a, b in comments],
        "reviews": [{"author": {"login": a}, "body": b, "state": "COMMENTED",
                     "submittedAt": "2020-01-01T00:00:00Z"}
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
    """Direct candidates are recognized; compound shapes are unknown.

    Sabotage: require `seg[0] == 'gh'` to be the token at index 1 and this goes
    red on every form.
    """
    forms = {
        "gh pr merge 532 --squash --delete-branch": [(532, None)],
        "gh pr merge 796 --repo dp-web4/hestia --squash": [(796, "dp-web4/hestia")],
        "gh pr merge 796 -R example/other --merge": [(796, "example/other")],
    }
    for target, want in forms.items():
        check(f"command position: {target[:34]!r}", merge_calls(target) == want,
              str(merge_calls(target)))
    for target in ["cd /repo && gh pr merge 353 --merge",
                   "set -euo pipefail\ngh pr merge 729 --merge\ngit fetch",
                   "gh pr ready 490 && gh pr merge 490 --merge"]:
        check("compound target is unknown", merge_calls(target) is None, repr(target))


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
        check(f"search is not attributed: {target[:38]!r}", merge_calls(target) is None)


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
    check("heredoc stays unknown, not a counted merge", merge_calls(target) is None,
          str(merge_calls(target)))


def arm_unlexable_target_is_dropped_not_guessed() -> None:
    """An unbalanced quote is unknown, never a measured negative or a guessed call.

    Sabotage: replace the ValueError guard with a regex fallback and this goes
    red — which is the whole v1 failure mode returning.
    """
    check("unlexable target is unknown", merge_calls("gh pr merge 5 \"unclosed") is None)


def arm_ambiguous_shell_text_is_not_attributed() -> None:
    """Literal data and shell expansion cannot become a performer observation."""
    for target in [
        "python3 - <<'END'\ngh pr merge 532 --merge\nEND",
        "python3 - <<END\ngh pr merge 532 --merge\nEND",
        "python3 - <<-END\n\tgh pr merge 532 --merge\n\tEND",
        "echo $(gh pr merge 532 --merge)",
        "echo `gh pr merge 532 --merge`",
        "diff <(gh pr merge 532 --merge) /dev/null",
        "gh pr merge 532 --merge\npython3 - <<END\nexample\nEND",
        "printf ';' gh pr merge 532",
        r"echo \; gh pr merge 532",
        "printf '\n' gh pr merge 532",
        "echo ok | gh pr merge 532",
        "gh pr merge 532 --repo example/*",
        "gh pr merge 532 -R",
        "gh pr merge 532 --body --repo example/other",
        "gh pr merge 532 --repo example/one --repo example/two",
    ]:
        check("ambiguous target remains unknown", merge_calls(target) is None, repr(target))
    quoted = "printf 'example:\ngh pr merge 532 --merge\n'"
    check("multiline quoted data is unknown", merge_calls(quoted) is None, str(merge_calls(quoted)))
    check("non-ASCII numeric text stays unknown", merge_calls("gh pr merge ²") is None)
    check("oversized numeric text stays unknown", merge_calls("gh pr merge " + "9" * 5000) is None)
    hits = [{"calls": None, "ambiguous_count": 2}]
    merged = seat_merges(hits, [pr(532, "synthetic", "2026-08-01T00:00:00Z")], REPO, 300)
    report = census([pr(532, "synthetic", "2026-08-01T00:00:00Z")], 200, merged)
    check("ambiguous source is partial, not a measured zero",
          report["performer_status"] == "partial" and report["seat_performed"] is None
          and report["seat_candidate_count"] == 0 and report["ambiguous_outcomes"] == 2,
          str(report))


def arm_supplied_records_are_classified_without_acquiring_a_chain() -> None:
    """The classifier consumes only its iterable; it does not acquire or authenticate it."""
    entries = [
        {"eventType": "outcome", "timestamp": "2026-01-01T00:00:00Z", "chainPosition": 1,
         "eventData": {"success": True, "action_id": "synthetic", "plugin_id": "synthetic",
                       "target": "gh pr merge 42 --repo example/repo --merge"}},
        {"eventType": "outcome", "eventData": {"success": True, "target": "printf ';' gh pr merge 42"}},
        {"eventType": "policy_decision", "eventData": {"success": True, "target": "gh pr merge 43"}},
        {"eventType": "outcome", "eventData": {"success": False, "target": "gh pr merge 44"}},
        {"eventType": "outcome", "eventData": {"success": True, "error": "synthetic",
                                               "target": "gh pr merge 45"}},
        {"eventType": "outcome", "eventData": {"target": "gh pr merge 46"}},
        {"eventType": "outcome", "eventData": {"success": True, "target": 123}},
        {"eventType": "outcome", "eventData": "malformed"},
        {"eventData": {"success": True, "target": "gh pr merge 47"}},
    ]
    hits = classify_outcomes(iter(entries))
    check("one supplied direct candidate", len(hits) == 2 and hits[0]["calls"] == [[42, "example/repo"]], str(hits))
    check("failed, malformed and ambiguous outcomes remain unknown",
          hits[-1] == {"calls": None, "ambiguous_count": 7}, str(hits))
    check("raw target text is not retained", all("target" not in hit for hit in hits), str(hits))


def arm_old_or_invalid_cache_is_not_a_measured_zero() -> None:
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory) / "synthetic.json"
        for content in ([], {"schema": "merge-candidates-unknown-shell-v2", "hits": []},
                        {"schema": "merge-candidates-direct-only-v3", "hits": []},
                        {"schema": _CACHE_SCHEMA, "hits": [{"calls": None, "ambiguous_count": -1}]}):
            cache.write_text(json.dumps(content))
            try:
                scan_chain(10, cache)
            except ValueError:
                refused = True
            else:
                refused = False
            check("old or malformed cache refused", refused)
        cache.write_text(json.dumps({"schema": _CACHE_SCHEMA, "hits": []}))
        check("new empty cache remains observed zero", scan_chain(10, cache) == [])


def arm_missing_performer_or_timezone_is_unknown() -> None:
    prs = [pr(532, "synthetic", "2026-08-01T00:00:00Z")]
    no_actor = hit(None, "gh pr merge 532 --repo dp-web4/hestia --merge", "2026-08-01T00:00:01Z")
    no_zone = hit("seat", "gh pr merge 532 --repo dp-web4/hestia --merge", "2026-08-01T00:00:01")
    merged = seat_merges([no_actor, no_zone], prs, REPO, 300)
    result = census(prs, 200, merged)
    check("missing actor or timezone does not become a measured negative",
          result["performer_status"] == "partial" and result["seat_performed"] is None
          and result["ambiguous_outcomes"] == 2, str(result))
    no_repo = hit("seat", "gh pr merge 532 --merge", "2026-08-01T00:00:01Z")
    no_repo_result = seat_merges([no_repo], prs, REPO, 300)
    check("missing explicit repo is unknown, not attributed to this repo",
          no_repo_result["corroborated"] == {} and no_repo_result["ambiguous_outcomes"] == 1,
          str(no_repo_result))


# --------------------------------------------------------------------------
# PERFORMER half — corroboration
# --------------------------------------------------------------------------

def arm_wrapper_success_needs_a_merge_instant() -> None:
    """codex #3: `success: true` is the SHELL's exit code, not the merge's.

    The measured target includes a shell expansion and is now unknown. The
    synthetic wrapper below still exits zero whether or not `gh` did. The two hits are identical in every
    field the parser reads EXCEPT the timestamp. Only the one that lands beside
    the merge instant counts; the other is reported as uncorroborated.

    Sabotage: drop the window test in seat_merges and this goes red, because
    both hits would be accepted and the masked failure would be a merge.
    """
    actual = 'gh pr merge 532 --squash --delete-branch 2>&1 | tail -5; echo "rc=$?"'
    check("wrapper with expansion is unknown", merge_calls(actual) is None)
    wrapper = 'gh pr merge 532 --squash --delete-branch 2>&1 | tail -5; echo done'
    check("wrapper without expansion is also unknown", merge_calls(wrapper) is None)
    target = 'gh pr merge 532 --repo dp-web4/hestia --squash --delete-branch'
    prs = [pr(532, "x", "2026-08-19T05:00:51Z")]

    real = seat_merges([hit("claude-code", target, "2026-08-19T05:00:56Z")],
                       prs, REPO, window=300.0)
    check("outcome beside the merge instant is a candidate",
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
    early = seat_merges([hit("kimi-code", "gh pr merge 700 --repo dp-web4/hestia --squash",
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
        [hit("codex", "gh pr merge 800 --repo dp-web4/hestia --merge", "2026-09-01T00:04:00Z", "far", 2),
         hit("claude-code", "gh pr merge 800 --repo dp-web4/hestia --merge", "2026-09-01T00:00:03Z", "near", 1)],
        prs, REPO, window=300.0)
    check("nearest outcome wins", set(out["corroborated"]) == {800}
          and out["corroborated"][800]["seat"] == "claude-code"
          and out["corroborated"][800]["action_id"] == "near", str(out))


def arm_a_seat_merge_is_reported_against_the_credential() -> None:
    """End to end: the temporal match remains a candidate, not proven authorship.

    This is the finding in one row. Sabotage: return an empty dict from
    seat_merges and this goes red on seat_candidate_count.
    """
    prs = [pr(532, "fix: x", "2026-08-19T05:00:51Z"),
           pr(533, "fix: y", "2026-08-19T06:00:00Z")]
    merges = seat_merges([hit("claude-code", "gh pr merge 532 --repo dp-web4/hestia --squash",
                              "2026-08-19T05:00:56Z")], prs, REPO, window=300.0)
    out = census(prs, 200, merges)
    check("candidate reported without asserting who merged",
          out["distinct_mergedBy"] == ["dp-web4"] and out["seat_performed"] is None
          and out["seat_candidate_count"] == 1 and out["seat_candidate_by"] == {"claude-code": 1}
          and out["seat_candidate_numbers"] == [532]
          and out["rows"][0]["candidate_seat"] == "claude-code"
          and out["rows"][0]["performed_by_seat"] is None
          and out["rows"][1]["performed_by_seat"] is None, str(out["seat_performed_by"]))


def arm_empty_chain_leaves_the_review_census_intact() -> None:
    """An observed empty chain must not affect the review half.

    Sabotage: read merges before computing `reviewed` and this goes red when
    the chain is empty.
    """
    prs = [pr(40, "findings: a", "2026-08-01T00:00:00Z"),
           pr(41, "fix: b", "2026-08-02T00:00:00Z", comments=[("dp-web4", "x" * 300)])]
    out = census(prs, 200, seat_merges([], prs, REPO, window=300.0))
    check("review census survives an empty observed chain",
          out["unreviewed"] == 1 and out["seat_performed"] is None
          and out["seat_candidate_count"] == 0)


def arm_unavailable_chain_is_not_a_zero_performer_count() -> None:
    """A failed or skipped observation is unknown, not a measured zero."""
    import contextlib
    import io
    import json
    from unittest.mock import patch
    import merge_review_census as tool

    prs = [pr(40, "findings: a", "2026-08-01T00:00:00Z")]
    try:
        out = census(prs, 200, None)
    except Exception as exc:
        check("unavailable chain is represented without an exception", False, type(exc).__name__)
        return
    check("unavailable is not zero", out.get("performer_status") == "unavailable"
          and out.get("seat_performed") is None and out.get("seat_performed_pct") is None
          and out.get("seat_performed_by") is None and out["unreviewed"] == 1, str(out))
    observed = census(prs, 200, seat_merges([], prs, REPO, window=300.0))
    check("successful empty scan has zero candidates, not proven performers",
          observed.get("performer_status") == "observed" and observed.get("seat_performed") is None
          and observed.get("seat_candidate_count") == 0 and observed.get("seat_candidate_pct") == 0.0)
    empty = census([], 200, seat_merges([], [], REPO, window=300.0))
    check("no merged PR denominator is not zero percent", empty.get("seat_performed_pct") is None)
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", ["census", "--json"]), patch.object(tool, "fetch", return_value=prs), \
            patch.object(tool, "scan_chain", side_effect=OSError("synthetic unavailable")), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = tool.main()
    data = json.loads(stdout.getvalue())
    check("CLI retains unknown on scan failure", result == 0 and data.get("performer_status") == "unavailable"
          and data.get("seat_performed") is None and data.get("seat_performed_pct") is None, str(data))
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", ["census"]), patch.object(tool, "fetch", return_value=prs), \
            patch.object(tool, "scan_chain", side_effect=OSError("synthetic unavailable")), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = tool.main()
    check("text output labels unavailable without a zero count", result == 0
          and "performer evidence unavailable" in stdout.getvalue()
          and "temporally associated seat-merge candidates:" not in stdout.getvalue(), stdout.getvalue())


def arm_missing_authors_and_known_bot_accounts_are_not_human_discussion() -> None:
    merged = "2026-08-01T12:00:00Z"
    def item(number, author, body, edited=False):
        row = pr(number, "fix: synthetic", merged)
        row["comments"] = [{"author": author, "body": body, "includesCreatedEdit": edited,
                            "createdAt": "2026-08-01T11:00:00Z"}]
        return row

    post_merge = item(7, None, "x" * 300)
    post_merge["comments"][0]["createdAt"] = "2026-08-01T13:00:00Z"
    unknown_time = item(8, None, "x" * 300)
    unknown_time["comments"][0]["createdAt"] = None
    review = pr(9, "fix: synthetic", merged)
    review["reviews"] = [{"author": None, "body": "x" * 300, "submittedAt": "2026-08-01T11:00:00Z"}]
    examples = [item(1, None, "x" * 300), item(2, {}, "x" * 300),
                item(3, {"login": "automation[bot]"}, "x" * 300),
                item(4, {"login": "automation", "__typename": "Bot"}, "x" * 300),
                item(5, {"login": "reviewer"}, "x" * 300),
                item(6, None, "short", True), post_merge, unknown_time, review]
    result = census(examples, 200, {})
    states = [row["reviewed"] for row in result["rows"]]
    check("missing author is unknown and known bots do not count",
          states == [None, None, False, False, True, None, False, None, None], str(states))


def arm_review_timing_is_evidence_not_an_assumption() -> None:
    """Only demonstrably prior discussion is in the pre-merge proxy.

    Missing, malformed, timezone-free, simultaneous and edited records are
    unknown, not a negative review verdict; a later record is not prior.
    """
    merge = "2026-09-01T12:00:00Z"
    cases = []
    for number, stamp in enumerate(["2026-09-01T11:59:59Z", "2026-09-01T12:00:01Z",
                                    "2026-09-01T12:00:00Z", None, "invalid",
                                    "2026-09-01T11:59:59"], start=900):
        item = pr(number, "findings: timing", merge)
        item["comments"] = [{"author": {"login": "reviewer"}, "body": "x" * 300,
                              "createdAt": stamp}]
        cases.append(item)
    edited = pr(906, "findings: edited", merge)
    edited["reviews"] = [{"author": {"login": "reviewer"}, "body": "x" * 300,
                          "submittedAt": "2026-09-01T11:59:59Z", "includesCreatedEdit": True}]
    cases.append(edited)
    mixed = pr(907, "findings: mixed", merge)
    mixed["reviews"] = [{"author": {"login": "reviewer"}, "body": "x" * 300,
                         "submittedAt": "2026-09-01T11:59:59Z"}]
    mixed["comments"] = [{"author": {"login": "reviewer"}, "body": "x" * 300}]
    cases.append(mixed)
    result = census(cases, 200, {})
    states = [row["reviewed"] for row in result["rows"]]
    check("post-merge comment is not prior discussion", states[0:2] == [True, False], str(states))
    check("uncertain timing stays unknown", states[2:7] == [None] * 5, str(states))
    check("known prior discussion dominates an unknown row", states[7] is True, str(states))
    check("unknown rows excluded from negative count", result["unreviewed"] == 1
          and result["timing_unknown"] == 5, str(result))

    # One known negative plus three unknowns: the known rate is 100%, while
    # the all-row uncertainty interval is 25–100%, never a silent 25% rate.
    denominator = census([cases[1], cases[3], cases[4], cases[5]], 200, {})
    check("unknowns excluded from known denominator", denominator["timing_known"] == 1
          and denominator["unreviewed_pct"] == 100.0, str(denominator))
    check("uncertainty bounds include unknown rows", denominator["unreviewed_pct_lower"] == 25.0
          and denominator["unreviewed_pct_upper"] == 100.0, str(denominator))
    check("class uncertainty is explicit", denominator["findings_timing_unknown"] == 3, str(denominator))
    none_known = census([cases[3]], 200, {})
    check("no known denominator is not zero percent", none_known["unreviewed_pct"] is None, str(none_known))


def arm_shortened_edited_discussion_is_unknown() -> None:
    """A later edit can hide a formerly qualifying pre-merge body."""
    merge = "2026-09-01T12:00:00Z"
    items = []
    for number, field, stamp_key, stamp, edited in [
        (910, "comments", "createdAt", "2026-09-01T11:59:59Z", True),
        (911, "reviews", "submittedAt", "2026-09-01T11:59:59Z", True),
        (912, "comments", "createdAt", "2026-09-01T12:00:01Z", True),
        (913, "comments", "createdAt", "2026-09-01T11:59:59Z", False),
        (914, "comments", "createdAt", None, True),
        (915, "comments", "createdAt", "2026-09-01T12:00:00Z", True),
    ]:
        item = pr(number, "findings: edited short", merge)
        item[field] = [{"author": {"login": "reviewer"}, "body": "short",
                        stamp_key: stamp, "includesCreatedEdit": edited}]
        items.append(item)
    states = [row["reviewed"] for row in census(items, 200, {})["rows"]]
    check("short edited prior bodies are unknown, not absent",
          states == [None, None, False, False, None, None], str(states))

    items[0]["reviews"] = [{"author": {"login": "reviewer"}, "body": "x" * 300,
                            "submittedAt": "2026-09-01T11:59:59Z"}]
    check("known qualifying discussion beats shortened edited body",
          census([items[0]], 200, {})["rows"][0]["reviewed"] is True)


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
