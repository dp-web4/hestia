#!/usr/bin/env python3
"""Pins the arithmetic of tools/ci_red_spell_census.py.

The network path is deliberately untested and deliberately thin: everything that
decides anything takes plain data, so the arms below are the whole judgment
surface. One arm replays the real 2026-09-14..17 spell, because that spell is the
reason the tool exists and a synthetic-only corpus would not have caught what it
caught (a second and third cause arriving under an existing red).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_red_spell_census as census
from ci_red_spell_census import (attribute, failing_files_of, growth,
                                 parse_failed_files, red_spells, verdict)


def R(*pairs):
    """(hour, conclusion) -> a run row. Hours keep the fixtures readable."""
    return [{"sha": "sha%02d" % h, "created_at": "2026-09-14T%02d:00:00Z" % h,
             "conclusion": c} for h, c in pairs]


def test_a_spell_is_consecutive_failures_and_success_closes_it():
    s = red_spells(R((1, "success"), (2, "failure"), (3, "failure"), (4, "success"),
                     (5, "failure"), (6, "success")))
    assert [x["breaker"] for x in s] == ["sha02", "sha05"], s
    assert s[0]["commits"] == ["sha02", "sha03"], s
    assert s[0]["landed_into_red"] == 1, s
    assert s[0]["repaired_by"] == "sha04" and s[0]["hours"] == 2.0, s
    assert s[1]["landed_into_red"] == 0, s


def test_an_unrepaired_spell_reports_open_not_zero():
    """A still-red main has no duration. Reporting 0 h would read as "fixed fast"."""
    s = red_spells(R((1, "failure"), (2, "failure")))
    assert len(s) == 1 and s[0]["repaired_by"] is None, s
    assert s[0]["hours"] is None, s
    assert s[0]["landed_into_red"] == 1, s


def test_cancelled_and_in_progress_close_a_spell_rather_than_extend_it():
    """Neither is evidence main is red. Counting them as red invents spells out of
    a cancelled run, which is how infrastructure noise becomes a governance claim."""
    s = red_spells(R((1, "failure"), (2, "cancelled"), (3, "failure")))
    assert [x["commits"] for x in s] == [["sha01"], ["sha03"]], s
    s2 = red_spells(R((1, "failure"), (2, None)))
    assert s2[0]["commits"] == ["sha01"], s2


def test_no_red_is_no_spells():
    assert red_spells(R((1, "success"), (2, "success"))) == []


def test_the_echoed_shell_line_is_not_a_result():
    """The workflow's own `echo "FAILED ${#failed[@]} of ..."` source appears in the
    log above the output. Reading it as data reports `${#failed[@]}` as a filename."""
    log = ('2026-09-14T14:03:04Z \x1b[36;1m  echo "FAILED ${#failed[@]} of '
           '${#tests[@]}: ${failed[*]}"\x1b[0m\n'
           '2026-09-14T14:11:10Z FAILED 2 of 109: tools/b_test.py tools/a_test.py\n')
    assert parse_failed_files(log) == ["tools/a_test.py", "tools/b_test.py"]


def test_a_job_that_failed_without_the_summary_line_yields_nothing():
    """A job can die before the loop (setup, timeout, OOM). The honest answer is an
    empty set -- NOT "no failures", which is why callers print `(job-level only)`."""
    assert parse_failed_files("Process completed with exit code 1.\n") == []
    assert parse_failed_files("") == []


def test_the_last_summary_line_wins():
    """Re-run-in-place and multi-group logs can carry two summaries; the later one
    is the state the run ended in."""
    log = ("FAILED 3 of 9: a b c\nFAILED 1 of 9: a\n")
    assert parse_failed_files(log) == ["a"]


def test_growth_names_the_commit_that_added_a_cause_mid_spell():
    rows = growth([("s1", ["a"]), ("s2", ["a"]), ("s3", ["a", "b"]),
                   ("s4", ["b"])])
    assert [r["sha"] for r in rows] == ["s3", "s4"], rows
    assert rows[0]["added"] == ["b"] and rows[0]["fixed"] == [], rows
    assert rows[1]["added"] == [] and rows[1]["fixed"] == ["a"], rows


def test_growth_is_silent_when_the_set_is_unchanged():
    """The whole point: 14 commits all showing the same red job produce no rows,
    so the two that DID change stand out."""
    assert growth([("s1", ["a"]), ("s2", ["a"]), ("s3", ["a"])]) == []


def test_the_real_september_spell_names_its_three_causes():
    """Replay of the measured run (main, 2026-09-14T14:02Z .. 2026-09-17T17:12Z).
    14 commits, one job name (`plugin tests (python)`) red throughout, THREE
    distinct causes -- and the two later ones are invisible at job level."""
    series = [("ad2380c6", ["tools/shebang_exec_bit_test.py"]),
              ("722f9c7f", ["tools/shebang_exec_bit_test.py"]),
              ("f9f31da7", ["tools/public_boundary_test.py",
                            "tools/shebang_exec_bit_test.py"]),
              ("4cb2a8b0", ["tools/public_boundary_test.py",
                            "tools/shebang_exec_bit_test.py"]),
              ("667b932e", ["tools/public_boundary_test.py",
                            "tools/shebang_exec_bit_test.py"]),
              ("a4521973", ["tools/ci_selfexec_test.py",
                            "tools/public_boundary_test.py",
                            "tools/shebang_exec_bit_test.py"]),
              ("dc8cb62f", ["tools/ci_selfexec_test.py",
                            "tools/public_boundary_test.py",
                            "tools/shebang_exec_bit_test.py"])]
    rows = growth(series)
    assert [r["sha"] for r in rows] == ["f9f31da7", "a4521973"], rows
    assert rows[0]["added"] == ["tools/public_boundary_test.py"], rows
    assert rows[1]["added"] == ["tools/ci_selfexec_test.py"], rows


def test_an_unreported_run_has_no_baseline_and_says_unknown():
    """`conclusion: null` is what a run in flight returns. Mapping it to "no
    failures" is the absence-read-as-pass failure; every caller branches on the
    state, so the state is what is pinned."""
    for c in (None, "in_progress", "queued"):
        assert failing_files_of({"conclusion": c, "run_id": 1}) == ([], "unknown"), c
    assert failing_files_of({"conclusion": "success", "run_id": 1}) == ([], "success")
    assert failing_files_of({"conclusion": "cancelled", "run_id": 1}) == ([], "cancelled")


def test_a_failed_run_reads_its_log_and_nothing_else_does():
    """The only network call in the arithmetic path, and only on `failure`."""
    calls = []
    real = census.gh_failed_files
    census.gh_failed_files = lambda rid: (calls.append(rid) or ["tools/x_test.py"])
    try:
        assert failing_files_of({"conclusion": "failure", "run_id": 77}) == (
            ["tools/x_test.py"], "failure")
        assert failing_files_of({"conclusion": "success", "run_id": 88}) == ([], "success")
    finally:
        census.gh_failed_files = real
    assert calls == [77], calls


def test_attribute_splits_a_red_pr_three_ways():
    att = attribute(["a", "b"], ["b", "c"])
    assert att == {"yours": ["a"], "inherited": ["b"], "you_fixed": ["c"]}, att


def test_a_pr_whose_every_failure_is_mains_says_so():
    att = attribute(["a", "b"], ["a", "b"])
    assert att["yours"] == [], att
    assert verdict(att).startswith("INHERITED"), verdict(att)


def test_a_pr_that_repairs_main_still_shows_red_and_must_read_clean():
    """The case most likely to be misread. The PR is green on nothing of its own;
    its check is red only if it inherited one, and here it inherited none."""
    att = attribute([], ["a"])
    assert att == {"yours": [], "inherited": [], "you_fixed": ["a"]}, att
    assert verdict(att) == "CLEAN against main's baseline", verdict(att)


def test_verdict_leads_with_yours_and_still_names_the_inherited():
    v = verdict(attribute(["a", "b"], ["b"]))
    assert v.startswith("YOURS: a"), v
    assert "inherited: b" in v, v


TESTS = [
    test_a_spell_is_consecutive_failures_and_success_closes_it,
    test_an_unrepaired_spell_reports_open_not_zero,
    test_cancelled_and_in_progress_close_a_spell_rather_than_extend_it,
    test_no_red_is_no_spells,
    test_the_echoed_shell_line_is_not_a_result,
    test_a_job_that_failed_without_the_summary_line_yields_nothing,
    test_the_last_summary_line_wins,
    test_growth_names_the_commit_that_added_a_cause_mid_spell,
    test_growth_is_silent_when_the_set_is_unchanged,
    test_the_real_september_spell_names_its_three_causes,
    test_an_unreported_run_has_no_baseline_and_says_unknown,
    test_a_failed_run_reads_its_log_and_nothing_else_does,
    test_attribute_splits_a_red_pr_three_ways,
    test_a_pr_whose_every_failure_is_mains_says_so,
    test_a_pr_that_repairs_main_still_shows_red_and_must_read_clean,
    test_verdict_leads_with_yours_and_still_names_the_inherited,
]


if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        # An explicit list can go stale. Make that RED, not a silently smaller run.
        print("FAIL TESTS is stale: defined-not-listed=%s listed-not-defined=%s"
              % (sorted(defined - listed), sorted(listed - defined)))
        raise SystemExit(1)
    for f in TESTS:
        f()
        print("ok", f.__name__)
    print("%d passed" % len(TESTS))
