#!/usr/bin/env python3
"""Contract tests for tools/process_vintage.py.

The load-bearing one is `test_agreeing_fd_witnesses_are_uninformative`. The whole reason
this tool exists is that on 2026-08-26 `cat /proc/PID/fd/255` returned the CURRENT file
for a process running 20-day-old code, because DrvFs re-opens by path. A reader who
takes agreement between the two fd witnesses as corroboration gets "up to date" on every
process, stale or not — the answer is a constant, so its selectivity is zero. This file
pins the verdict for that case to UNINFORMATIVE rather than to `ok`.

The second is `test_unverifiable_is_not_ok`: a missing startup baseline means the
question was never answerable, and reporting that as agreement is absence-read-as-pass.

The third is `test_size_is_not_a_key`: measured the same day, a 48681-byte held inode
matched a 48681-byte blob at `8af9a76` whose content sha256 was completely different.
Keying the commit lookup on size produces a confident WRONG commit id, which is worse
than no answer. `git_versions` is keyed on sha256 and this pins that.

Run: python3 tools/process_vintage_test.py   (or via pytest)
"""
import importlib.util
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "process_vintage", os.path.join(_HERE, "process_vintage.py"))
pv = importlib.util.module_from_spec(_spec)
sys.modules["process_vintage"] = pv
_spec.loader.exec_module(pv)

A = "a" * 64
B = "b" * 64

# The real line, verbatim from the CBP journal 2026-08-26T01:47:26-07:00.
REAL_LINE = ("Aug 26 01:47:26 cbp hestia-watch-member.sh[1524325]: [hestia-watch] "
             "ARTIFACT plugin=claude-code state=drift reason=differs-from-startup "
             "startup_sha256=489c0076aa0b3fd5e1b20e69708057bcdb5553fab29b233dc2a23623"
             "ac92f118 disk_sha256=a7dde01ae611d141ba9c8b83bc163bed2f167b9ee1487f3774"
             "9bef0d06151804")


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def test_parses_the_real_journal_line():
    got = pv.parse_artifact(REAL_LINE)
    check("parse", got is not None, "the live line must parse")
    check("plugin", got["plugin"] == "claude-code", got)
    check("state", got["state"] == "drift", got)
    check("startup", got["startup"].startswith("489c0076"), got)
    check("disk", got["disk"].startswith("a7dde01a"), got)


def test_a_non_artifact_line_is_not_half_parsed():
    # UNANSWERED lines quote pointers that contain the word ARTIFACT-adjacent text; a
    # loose parse would return a dict of Nones and read as a measurement.
    for line in ("[hestia-watch] UNANSWERED (I OWE A RESPONSE): id=4341 ...",
                 "[hestia-watch] DAEMON UNVERIFIABLE — reason=daemon-unreachable",
                 ""):
        check("no-match", pv.parse_artifact(line) is None, repr(line))


def test_unverifiable_is_not_ok():
    check("no baseline", pv.classify("", A) == ("unverifiable",
                                                "startup-baseline-unavailable"))
    check("no disk", pv.classify(A, "unavailable") == ("unverifiable",
                                                       "disk-hash-unavailable"))
    # and neither of those is the ok verdict
    for pair in (("", A), (A, "unavailable")):
        check("not ok", pv.classify(*pair)[0] != "ok", pair)


def test_drift_and_ok_match_the_shell_guard():
    check("drift", pv.classify(A, B) == ("drift", "differs-from-startup"))
    check("ok", pv.classify(A, A) == ("ok", "matches-startup"))


def test_agreeing_fd_witnesses_are_uninformative():
    """The defect this tool was extracted from: agreement proves nothing."""
    v, _ = pv.fd_witnesses(fd_size=100, fd_readback_sha=A, disk_size=100, disk_sha=A)
    check("verdict", v == "agree-uninformative", v)
    check("not a pass", v != "ok", "agreement must never render as up-to-date")


def test_cat_lying_is_detected_by_the_size_disagreement():
    """The measured CBP case: readback == disk, but stat says a different inode."""
    v, why = pv.fd_witnesses(fd_size=48681, fd_readback_sha=A,
                             disk_size=54340, disk_sha=A)
    check("verdict", v == "cat-lies", v)
    check("names the cause", "re-opened by path" in why, why)


def test_a_genuinely_held_old_inode_still_does_not_date_the_parse():
    v, why = pv.fd_witnesses(fd_size=48681, fd_readback_sha=A,
                             disk_size=54340, disk_sha=B)
    check("verdict", v == "fd-holds-old-inode", v)
    check("hedges", "not the parse" in why, why)


def test_size_is_not_a_key():
    """Two different contents, same length, must not collide in a sha-keyed index."""
    same_len_a, same_len_b = b"x" * 48681, b"y" * 48681
    check("lengths equal", len(same_len_a) == len(same_len_b))
    check("hashes differ",
          pv.sha256_bytes(same_len_a) != pv.sha256_bytes(same_len_b),
          "a size-keyed lookup would map both to one commit")


# ---------------------------------------------------------------------------
# The invocation-binding arms. `cmd_units` shells out for everything, so `_run`
# and `git_versions` are the only two seams — stub both and the whole decision
# surface is reachable without a systemd host.
# ---------------------------------------------------------------------------

STARTUP = pv.parse_artifact(REAL_LINE)["startup"]
VERSIONS = {STARTUP: ("a8dccda", "2026-08-06T14:30:59-07:00", "the stale watcher body")}


class FakeShell:
    """Stand in for systemctl and journalctl, and RECORD what was asked.

    Recording matters as much as answering: two of the arms below are about a
    query that must NOT be made (the journal of a dead process) or must be made
    in one particular form (bound to the invocation). A stub that only returns
    output can be satisfied by code that asks the wrong question and ignores it.
    """

    def __init__(self, units):
        self.units = units
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[:3] == ["systemctl", "--user", "show"]:
            spec = self.units.get(args[3], {})
            return (f"ActiveState={spec.get('state', 'active')}\n"
                    f"MainPID={spec.get('pid', '4242')}\n"
                    f"InvocationID={spec.get('invocation', '')}\n")
        if args and args[0] == "journalctl":
            for spec in self.units.values():
                inv = spec.get("invocation")
                if inv and f"_SYSTEMD_INVOCATION_ID={inv}" in args:
                    return spec.get("inv_log", "")
            if "-u" in args:
                return self.units.get(args[args.index("-u") + 1], {}).get("unit_log", "")
        return ""


def run_units(units):
    """cmd_units against a fake host. Returns (stdout, the calls it made)."""
    import contextlib
    shell = FakeShell(units)
    real_run, real_versions, real_units = pv._run, pv.git_versions, pv.WATCHER_UNITS
    buf = io.StringIO()
    try:
        pv._run = shell
        pv.git_versions = lambda repo, path: VERSIONS
        # Only the units under test — otherwise the two unstubbed real watcher names
        # answer from FakeShell's defaults and every per-call assertion below counts
        # queries the test never asked for.
        pv.WATCHER_UNITS = tuple(units)
        with contextlib.redirect_stdout(buf):
            pv.cmd_units("/repo")
    finally:
        pv._run, pv.git_versions, pv.WATCHER_UNITS = (
            real_run, real_versions, real_units)
    return buf.getvalue(), shell.calls


def test_a_stopped_unit_is_not_measured_and_its_journal_is_not_even_read():
    """A dead process has no vintage. Its last ARTIFACT line dates the process that
    EXITED — an artifact outliving its producer, which is this tool's own subject."""
    out, calls = run_units({"hestia-watch-claude": {
        "state": "inactive", "unit_log": REAL_LINE}})
    check("refuses", "NOT MEASURED" in out, out)
    check("says why", "Nothing is executing" in out, out)
    check("no commit claimed", "a8dccda" not in out, out)
    check("did not consult the journal at all",
          not any(c and c[0] == "journalctl" for c in calls), calls)


def test_a_restart_with_no_fresh_level_line_refuses_instead_of_the_previous_one():
    """The load-bearing arm. Measured on CBP 2026-08-26 the journal retained 1h46m
    while the ARTIFACT level line is HOURLY, so for up to an hour after a restart the
    unit-wide query still returns the PREVIOUS invocation's startup hash. That is the
    exact minute someone runs this tool to check the restart took, and the unbound
    version told them it had not."""
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "NEWINV", "inv_log": "",
        "unit_log": REAL_LINE}})
    check("refuses", "NOT MEASURED" in out, out)
    check("does NOT report the dead invocation's commit", "a8dccda" not in out, out)
    check("does NOT report a vintage at all", "in force" not in out, out)
    check("names the inference it is refusing",
          "NOT evidence the restart failed to take" in out, out)


def test_the_journal_query_is_bound_to_the_invocation_not_the_unit():
    """Pins the mechanism, not just the message: a unit-wide query spans every
    invocation still inside the retention window."""
    _, calls = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "NEWINV", "inv_log": REAL_LINE}})
    journal = [c for c in calls if c and c[0] == "journalctl"]
    check("asked the journal once", len(journal) == 1, journal)
    check("bound to the invocation",
          "_SYSTEMD_INVOCATION_ID=NEWINV" in journal[0], journal[0])
    check("never asked unit-wide", "-u" not in journal[0], journal[0])


def test_an_unbindable_unit_is_labelled_rather_than_silently_unit_wide():
    """No InvocationID (not systemd, or systemd not answering) is a degraded answer,
    not an equal one. Report it, do not launder it."""
    out, calls = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "", "unit_log": REAL_LINE}})
    check("fell back to unit-wide",
          any(c and c[0] == "journalctl" and "-u" in c for c in calls), calls)
    check("and said so", "may belong to a previous invocation" in out, out)


def test_an_active_unit_with_a_fresh_level_line_still_reports_its_vintage():
    """POSITIVE CONTROL for the three refusals above. Without it, a `cmd_units` that
    refused every input would pass this file — the refusals would be measuring
    nothing, which is the failure mode the corpus keeps re-finding."""
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "NEWINV", "inv_log": REAL_LINE}})
    check("measured", "NOT MEASURED" not in out, out)
    check("names the commit in force", "a8dccda" in out, out)
    check("and its verdict", "drift" in out, out)


def test_same_size_different_content_is_not_agreement():
    """codex and kimi-code named this independently on PR #634. The readback hash
    differs from disk while the sizes collide — a same-size rewrite or a mid-write
    race — and the first version fell through to the agreement arm, whose message
    asserts "both fd witnesses match the on-disk file" about a readback that
    provably does not."""
    v, why = pv.fd_witnesses(fd_size=100, fd_readback_sha=A, disk_size=100, disk_sha=B)
    check("not agreement", v != "agree-uninformative", v)
    check("verdict", v == "fd-content-differs-size-collides", v)
    check("the message does not claim a match",
          "both fd witnesses match" not in why, why)
    check("names the collision", "collision" in why, why)


def test_every_fd_input_combination_has_its_own_verdict():
    """Exhaustive over the 2x2. A truth table with four inputs and three names has a
    fallthrough, and a fallthrough carries the message of whichever arm it lands in."""
    got = {(rb, sz): pv.fd_witnesses(
        fd_size=(100 if sz else 200), fd_readback_sha=(A if rb else B),
        disk_size=100, disk_sha=A)[0]
        for rb in (True, False) for sz in (True, False)}
    check("four inputs", len(got) == 4, got)
    check("four distinct verdicts", len(set(got.values())) == 4, got)
    check("only true/true is agreement",
          [k for k, v in got.items() if v == "agree-uninformative"] == [(True, True)],
          got)


TESTS = [
    test_parses_the_real_journal_line,
    test_a_non_artifact_line_is_not_half_parsed,
    test_unverifiable_is_not_ok,
    test_drift_and_ok_match_the_shell_guard,
    test_agreeing_fd_witnesses_are_uninformative,
    test_cat_lying_is_detected_by_the_size_disagreement,
    test_a_genuinely_held_old_inode_still_does_not_date_the_parse,
    test_size_is_not_a_key,
    test_same_size_different_content_is_not_agreement,
    test_every_fd_input_combination_has_its_own_verdict,
    test_a_stopped_unit_is_not_measured_and_its_journal_is_not_even_read,
    test_a_restart_with_no_fresh_level_line_refuses_instead_of_the_previous_one,
    test_the_journal_query_is_bound_to_the_invocation_not_the_unit,
    test_an_unbindable_unit_is_labelled_rather_than_silently_unit_wide,
    test_an_active_unit_with_a_fresh_level_line_still_reports_its_vintage,
]


def main():
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, e))
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
