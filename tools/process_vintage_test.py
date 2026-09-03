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

ADDED 2026-09-03, and it is the one that matters most, because this file WAS GREEN while
the tool could not read a single line a current watcher emits. `REAL_LINE` below is
captioned "verbatim from the CBP journal 2026-08-26" and it is — the capture discipline
was followed and dated. But #637 inserted `startup_origin=` into the emitted line on
2026-08-29, three days before this suite landed, so the verbatim capture was ALREADY a
snapshot of a wire that no longer existed. Provenance is not freshness: a fixture with a
capture date is a fixture with an expiry date that nothing enforces.

So `test_the_reader_handles_every_key_the_emitter_writes` does not test a capture at all.
It reads the ARTIFACT echo out of `plugins/member-mesh/hestia-watch-member.sh` in THIS
checkout and requires the reader to account for every `k=` in it. That guard is red in
the CI run of the commit that inserts a field, needs no journal, and cannot go stale,
because its fixture IS the emitter. `REAL_LINE_POST_637` keeps a dated capture too — one
fixture per format actually present in a live journal window (measured today: 13 of 19
lines carry the field, 6 do not, because a stale watcher and a current one were both
running).

Run: python3 tools/process_vintage_test.py   (or via pytest)
"""
import importlib.util
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "process_vintage", os.path.join(_HERE, "process_vintage.py"))
pv = importlib.util.module_from_spec(_spec)
sys.modules["process_vintage"] = pv
_spec.loader.exec_module(pv)

A = "a" * 64
B = "b" * 64

# The real line, verbatim from the CBP journal 2026-08-26T01:47:26-07:00 — emitter
# PRE-#637, so it carries no `startup_origin`. Still a live shape: a watcher started
# before 2026-08-29 emits exactly this, and reading a STALE watcher is the whole point of
# the tool, so this fixture must keep parsing forever.
REAL_LINE = ("Aug 26 01:47:26 cbp hestia-watch-member.sh[1524325]: [hestia-watch] "
             "ARTIFACT plugin=claude-code state=drift reason=differs-from-startup "
             "startup_sha256=489c0076aa0b3fd5e1b20e69708057bcdb5553fab29b233dc2a23623"
             "ac92f118 disk_sha256=a7dde01ae611d141ba9c8b83bc163bed2f167b9ee1487f3774"
             "9bef0d06151804")

# The real line, verbatim from the CBP journal 2026-09-03T01:08:39-07:00 — emitter
# POST-#637 (`startup_origin=own-fd` sits BETWEEN the two sha fields, which is exactly
# where the original adjacency regex required them to touch). Every watcher on CBP was
# emitting this shape, hourly, while this suite reported 15/15.
REAL_LINE_POST_637 = (
    "2026-09-03T01:08:39-07:00 cbp hestia-watch-member.sh[1253]: [hestia-watch] "
    "ARTIFACT plugin=claude-code state=ok reason=matches-startup "
    "startup_sha256=36cf220fac1a65ef82f9f2fefc5ade4d898c6f314fb08d8b65acd74c2da58083 "
    "startup_origin=own-fd "
    "disk_sha256=36cf220fac1a65ef82f9f2fefc5ade4d898c6f314fb08d8b65acd74c2da58083 "
    "started=2026-09-03T08:08:39Z")


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


def test_parses_the_post_637_journal_line():
    """THE regression. Red against the adjacency regex this file shipped with."""
    got = pv.parse_artifact(REAL_LINE_POST_637)
    check("parse", got is not None, "a line every current watcher emits must parse")
    check("readable", got["missing"] == (),
          f"required keys absent: {got['missing']}")
    check("startup", got["startup"].startswith("36cf220f"), got)
    check("disk", got["disk"].startswith("36cf220f"), got)
    check("origin", got.get("startup_origin") == "own-fd", got)
    # and the inserted field must not be reported as a surprise
    check("known", got["unknown"] == (), f"unexpected keys: {got['unknown']}")


def test_the_reader_handles_every_key_the_emitter_writes():
    """The fixture IS the emitter, so this guard cannot go stale.

    Reads the ARTIFACT level echo out of the watcher script in THIS checkout. If someone
    inserts, renames or removes a field, this is red in that commit's own CI run — which
    is the round trip that #637 did not have to make.
    """
    emitter = os.path.join(os.path.dirname(_HERE), pv.WATCH_PATH)
    check("emitter present", os.path.exists(emitter), emitter)
    with open(emitter, encoding="utf-8") as fh:
        echoes = [l for l in fh if "ARTIFACT plugin=" in l]
    check("echo found", len(echoes) == 1,
          f"expected exactly one ARTIFACT level echo, found {len(echoes)}")
    emitted = tuple(m.group("k") for m in pv._KV_RE.finditer(echoes[0]))
    for k in pv.REQUIRED_ARTIFACT_KEYS:
        check("required emitted", k in emitted,
              f"the reader requires {k} and the emitter no longer writes it: {emitted}")
    for k in emitted:
        check("emitted known", k in pv.KNOWN_ARTIFACT_KEYS,
              f"the emitter writes {k} and the reader does not account for it — add it "
              f"to KNOWN_ARTIFACT_KEYS (or REQUIRED_ARTIFACT_KEYS) in process_vintage.py")
    # The whole line must round-trip through the reader once its $VARs are filled in.
    filled = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", "x", echoes[0])
    got = pv.parse_artifact(filled)
    check("emitter line parses", got is not None and got["missing"] == (),
          f"the emitter's own line does not parse: {got}")


def test_an_unparseable_artifact_line_is_not_an_absent_one():
    """The defect that hid the defect: both states printed the same reassurance.

    An ARTIFACT line whose required keys the reader cannot find must come back as a
    dict with `missing` set — a READER defect — not as None. None means "no such line",
    whose documented remedy is to wait, and waiting can never fix a shape mismatch.
    """
    mangled = REAL_LINE_POST_637.replace("disk_sha256=", "disk_sha256_v2=")
    got = pv.parse_artifact(mangled)
    check("still recognised", got is not None,
          "an ARTIFACT line with a renamed field is still an ARTIFACT line, not absence")
    check("named", "disk_sha256" in got["missing"], got["missing"])
    check("surprise named", "disk_sha256_v2" in got["unknown"], got["unknown"])
    # and the readable line is not mistaken for the broken one
    check("clean is clean", pv.parse_artifact(REAL_LINE_POST_637)["missing"] == ())


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
    test_parses_the_post_637_journal_line,
    test_the_reader_handles_every_key_the_emitter_writes,
    test_an_unparseable_artifact_line_is_not_an_absent_one,
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
