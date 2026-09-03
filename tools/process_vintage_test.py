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



# --- 2026-09-03: the producer moved and this reader did not notice for a day ---------
#
# #634 shipped the reader on 2026-09-02 with the two hash fields matched ADJACENT.
# #636 merged the same day and inserted `startup_origin=` between them. Every arm above
# stayed green — REAL_LINE is a real journal line captured on 2026-08-26, and a fixture
# pinned to a capture date cannot see a producer that moved after it. Measured on CBP
# 2026-09-03: all three watcher units reported `vintage NOT MEASURED`, in the reassuring
# spelling ("wait for the next level line"), while the level line sat in the journal of
# the bound invocation. The primer banner names this tool as the disambiguator for which
# producer wrote a stale primer, so the fleet's one instruction for that question was
# answering nobody.

# Verbatim, CBP journal 2026-09-03T01:08:39-07:00, invocation 42020ab38d724378.
LIVE_LINE_0903 = (
    "Sep 03 01:08:39 cbp hestia-watch-member.sh[1253]: [hestia-watch] ARTIFACT "
    "plugin=claude-code state=ok reason=matches-startup "
    "startup_sha256=36cf220fac1a65ef82f9f2fefc5ade4d898c6f314fb08d8b65acd74c2da58083 "
    "startup_origin=own-fd "
    "disk_sha256=36cf220fac1a65ef82f9f2fefc5ade4d898c6f314fb08d8b65acd74c2da58083 "
    "started=2026-09-03T08:08:39Z")

# REAL_LINE's hashes (so VERSIONS still resolves the commit) in the live field ORDER.
LIVE_SHAPED_REAL = REAL_LINE.replace(
    f"startup_sha256={STARTUP} disk_sha256=",
    f"startup_sha256={STARTUP} startup_origin=own-fd disk_sha256=")


def test_a_field_inserted_between_the_two_hashes_still_parses():
    """RED before the fix: the adjacency requirement made this line unreadable."""
    check("the fixture really is the new shape",
          "startup_origin=own-fd" in LIVE_SHAPED_REAL, LIVE_SHAPED_REAL)
    got = pv.parse_artifact(LIVE_LINE_0903)
    check("parse", got is not None, "the LIVE line must parse")
    check("nothing missing", got["missing"] == [], got)
    check("startup", got["startup"].startswith("36cf220f"), got)
    check("disk", got["disk"].startswith("36cf220f"), got)
    check("state", got["state"] == "ok", got)


def test_fields_are_read_by_name_not_by_position():
    """The general form of the defect. Order is the producer's business, not ours."""
    scrambled = ("[hestia-watch] ARTIFACT plugin=kimi-code "
                 f"disk_sha256={B} started=2026-09-03T08:08:39Z reason=matches-startup "
                 f"startup_origin=journal state=ok startup_sha256={A}")
    got = pv.parse_artifact(scrambled)
    check("parse", got is not None, scrambled)
    check("nothing missing", got["missing"] == [], got)
    check("startup", got["startup"] == A, got)
    check("disk", got["disk"] == B, got)
    check("reason", got["reason"] == "matches-startup", got)


def test_a_level_line_missing_a_field_is_loud_not_silent():
    """The half of the fix that keeps the NEXT rename from costing another day.

    A line that carries the anchor but not a field this reader needs is a fact about
    the READER. Returning None for it — what #634 did — is indistinguishable from "the
    watcher has not reported yet", and that is the sentence the tool printed for a day.
    """
    truncated = ("[hestia-watch] ARTIFACT plugin=claude-code state=ok "
                 f"reason=matches-startup startup_sha256={A} started=2026-09-03T08:08Z")
    got = pv.parse_artifact(truncated)
    check("not silent", got is not None,
          "a level line missing a field must not read as 'no level line'")
    check("names what is missing", got["missing"] == ["disk_sha256"], got)
    check("keeps what it did read", got["startup"] == A, got)
    # and the distinction survives: a line with no anchor is still None
    check("no anchor is still None",
          pv.parse_artifact("[hestia-watch] DAEMON DRIFT — running=v0.0.4") is None)


def test_cmd_units_blames_the_reader_not_the_restart():
    """RED before the fix twice over: pre-fix `cmd_units` printed the wait-for-the-next
    -line sentence for this input, which is the false reassurance itself."""
    truncated = ("[hestia-watch] ARTIFACT plugin=claude-code state=ok "
                 f"reason=matches-startup startup_sha256={A} started=2026-09-03T08:08Z")
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "NEWINV", "inv_log": truncated}})
    check("says the reader is stale", "UNREADABLE" in out, out)
    check("names the missing field", "disk_sha256" in out, out)
    check("does NOT reassure",
          "wait for the next level line" not in out, out)
    check("claims no vintage", "a8dccda" not in out, out)


def test_the_live_shape_reaches_a_verdict_end_to_end():
    """The positive control for the arm above: the new order must still MEASURE."""
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "NEWINV", "inv_log": LIVE_SHAPED_REAL}})
    check("measured", "NOT MEASURED" not in out, out)
    check("names the commit in force", "a8dccda" in out, out)
    check("not blamed on the reader", "UNREADABLE" not in out, out)


def test_the_edge_alarms_are_never_read_as_a_level_line():
    """#636 added two more ARTIFACT spellings. An edge alarm read as a level line
    would date the process from a one-shot event that the journal window then drops."""
    for line in (
        f"[hestia-watch] ARTIFACT DRIFT — restart required; startup_sha256={A} "
        f"startup_origin=own-fd disk_sha256={B}",
        f"[hestia-watch] ARTIFACT UNVERIFIABLE — reason=disk-hash-unavailable "
        f"startup_sha256={A} startup_origin=own-fd disk_sha256=unavailable",
        f"[hestia-watch] ARTIFACT DEPLOY plugin=claude-code — exec into merged bytes; "
        f"was={A} now={B} ref=origin/main:x snapshot={A}",
        "[hestia-watch] ARTIFACT DRIFT held — deploy declined",
    ):
        check("edge is not level", pv.parse_artifact(line) is None, line)


def test_the_watcher_still_emits_every_field_this_tool_reads():
    """THE regression guard, and the only one here that is not a copy of the past.

    Every other arm feeds this tool a string some human transcribed. That is exactly
    how the defect survived: the transcription was accurate on the day it was taken and
    the producer moved the next day. This arm reads the PRODUCER — the level-line echo
    in the watcher itself — and fails the moment a field this reader requires stops
    being emitted, with no journal, no running unit and no capture involved.
    """
    repo = os.path.dirname(_HERE)
    watcher = os.path.join(repo, pv.WATCH_PATH)
    check("the producer is where we think", os.path.exists(watcher), watcher)
    emit = [ln for ln in io.open(watcher, encoding="utf-8").read().splitlines()
            if "[hestia-watch] ARTIFACT plugin=" in ln]
    check("exactly one level-line emit site", len(emit) == 1,
          f"{len(emit)} sites — if the watcher grew a second, this tool reads the "
          f"LAST match in a journal and the arms above no longer pin which one")
    for wire in pv.ARTIFACT_FIELDS:
        check(f"watcher still emits {wire}", f"{wire}=" in emit[0],
              f"the watcher's level line no longer carries {wire}=; this tool reads it. "
              f"emit site: {emit[0].strip()[:200]}")
    # and the anchor this tool keys on is verbatim in the producer
    check("anchor is verbatim in the producer",
          "[hestia-watch] ARTIFACT plugin=" in emit[0], emit[0])


# ---------------------------------------------------------------------------
# The starvation arms. Measured on CBP 2026-09-03: with #880's parser fix merged,
# the one ACTIVE watcher on the box still reported `vintage NOT MEASURED`, and the
# reason it printed — "wait for the next level line" — was false. `announce_artifact`
# is inside the main loop; `retry_stale_primers` runs BEFORE that loop and fires one
# full synchronous wake per retained primer. With 46 retained, the loop is hours away.
# "Not due yet" and "unreachable by construction" are opposite verdicts about the
# subject, and the tool printed the reassuring one for both.
# ---------------------------------------------------------------------------

def _sweep_log(marks, first="2026-09-03T10:15:30-0700",
               last="2026-09-03T13:02:14-0700", extra=()):
    lines = [f"{first} cbp hestia-watch-member.sh[1253]: {marks[0]}"]
    lines.extend(extra)
    lines.append(f"{last} cbp hestia-watch-member.sh[1253]: {marks[-1]}")
    return "\n".join(lines) + "\n"


SWEEP_ANNOUNCE = ("[hestia-watch] STALE PRIMER (undelivered notices from a failed "
                  "fire): /primers/claude-code/notice-AAAAAA.json")
RETRY_ANNOUNCE = ("[hestia-watch] RETRYING stale primer (attempt 2/3): "
                  "/primers/claude-code/notice-MMMMMM.json")


def test_a_starved_invocation_is_not_told_to_wait_for_a_line_it_cannot_reach():
    """The load-bearing arm. Sweep announcements spanning longer than one gauge
    period with ZERO main-loop announcements means the loop was never entered."""
    log = _sweep_log((SWEEP_ANNOUNCE, RETRY_ANNOUNCE))
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "INV", "inv_log": log}})
    check("still refuses a vintage", "NOT MEASURED" in out, out)
    check("names starvation", "STARVED" in out, out)
    check("contradicts the old reassurance", "unreachable" in out, out)
    check("does NOT tell the operator to wait",
          "wait for the next level line" not in out, out)
    check("names the collateral outage", "maybe_self_deploy" in out, out)
    check("span is a floor, not a claim", "at least 2h46m" in out, out)


def test_one_main_loop_line_is_decisive_against_starvation():
    """The sabotage arm for the arm above: the SAME sweep journal, plus a single
    DAEMON line, must flip the verdict. If it does not, the check is keying on the
    sweep lines alone and would call every busy watcher starved."""
    reached = ("2026-09-03T11:00:00-0700 cbp hestia-watch-member.sh[1253]: "
               "[hestia-watch] DAEMON state=ok reason=matches running=yes source=x")
    log = _sweep_log((SWEEP_ANNOUNCE, RETRY_ANNOUNCE), extra=[reached])
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "INV", "inv_log": log}})
    check("does not claim starvation", "STARVED" not in out, out)
    check("keeps the honest fallback", "wait for the next level line" in out, out)


def test_a_sweep_shorter_than_one_gauge_period_is_not_starvation():
    """A restart that swept two primers in ten minutes has told us nothing yet. The
    threshold is one gauge period because that is when a level line became overdue."""
    log = _sweep_log((SWEEP_ANNOUNCE, RETRY_ANNOUNCE),
                     first="2026-09-03T10:15:30-0700",
                     last="2026-09-03T10:25:30-0700")
    out, _ = run_units({"hestia-watch-claude": {
        "state": "active", "invocation": "INV", "inv_log": log}})
    check("does not claim starvation", "STARVED" not in out, out)


def test_the_sweep_position_is_the_index_of_the_primer_in_the_pending_list():
    """Arithmetic only — this arm STUBS `list_primers`, so it cannot see the order
    that function actually produces. Renamed after a sabotage run: reversing the real
    sort left it green, which is the whole inert-probe failure this corpus keeps
    re-finding. `test_list_primers_yields_the_collation_bash_globs_in` is the arm that
    pins the order; this one pins that position/remaining are computed off it."""
    listing = ["/primers/claude-code/notice-AAAAAA.json",
               "/primers/claude-code/notice-MMMMMM.json",
               "/primers/claude-code/notice-ZZZZZZ.json"]
    real = pv.list_primers
    try:
        pv.list_primers = lambda d: listing
        out, _ = run_units({"hestia-watch-claude": {
            "state": "active", "invocation": "INV",
            "inv_log": _sweep_log((SWEEP_ANNOUNCE, RETRY_ANNOUNCE))}})
    finally:
        pv.list_primers = real
    check("position is the index of the primer being retried",
          "Sweep position 2 of 3" in out, out)
    check("remaining is what is left AFTER it", "1 primer(s) still to fire" in out, out)


def test_list_primers_yields_the_collation_bash_globs_in():
    """The arm the stubbed one cannot be. The watcher's `for stale in
    "$PRIMERS"/notice-*.json` expands under the unit's collation, and no LANG is set
    by the unit, so it is C: byte order, uppercase before lowercase. Sorting any other
    way reports a position that is not the sweep's position — and the operator reads
    'how many still to fire' off it."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        names = ["notice-aaaaaa.json", "notice-MMMMMM.json", "notice-AAAAAA.json",
                 "notice-ZZZZZZ.json", "notice-SpjwIu.json.discharged"]
        for n in names:
            open(os.path.join(d, n), "w").close()
        got = [os.path.basename(x) for x in pv.list_primers(d)]
    check("C collation: uppercase before lowercase, byte order within",
          got == ["notice-AAAAAA.json", "notice-MMMMMM.json", "notice-ZZZZZZ.json",
                  "notice-aaaaaa.json"], got)
    check("retired primers are not in the sweep list",
          not any(x.endswith(".discharged") for x in got), got)

def test_the_gauge_period_is_read_from_the_producer_not_assumed():
    """#880's lesson applied to the second constant in this file: the watcher moved
    and the reader did not. A period hard-coded here would go wrong silently the day
    someone tunes UNANSWERED_EVERY, in the direction of calling a healthy watcher
    starved."""
    import tempfile
    with tempfile.TemporaryDirectory() as repo:
        src = os.path.join(repo, pv.WATCH_PATH)
        os.makedirs(os.path.dirname(src))
        with open(src, "w") as fh:
            fh.write('UNANSWERED_EVERY="${UNANSWERED_EVERY:-14400}"   # cadence\n')
        check("reads the watcher", pv.gauge_period(repo) == (14400, "watcher source"),
              pv.gauge_period(repo))
    check("says so when it could not", pv.gauge_period("/nonexistent")
          == (pv.GAUGE_PERIOD_DEFAULT, "fallback default"),
          pv.gauge_period("/nonexistent"))


def test_a_sweep_spanning_midnight_is_not_a_negative_span():
    """Seconds-of-day alone would make a 2-hour span across midnight read as -79200,
    which compares BELOW the gauge period and silently un-detects the starvation of
    exactly the long-running sweeps this is for."""
    span = pv.journal_span([
        "2026-09-03T23:30:00-0700 x", "2026-09-04T01:30:00-0700 x"])
    check("crosses the day boundary", span == 7200, span)


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
    test_a_field_inserted_between_the_two_hashes_still_parses,
    test_fields_are_read_by_name_not_by_position,
    test_a_level_line_missing_a_field_is_loud_not_silent,
    test_cmd_units_blames_the_reader_not_the_restart,
    test_the_live_shape_reaches_a_verdict_end_to_end,
    test_the_edge_alarms_are_never_read_as_a_level_line,
    test_the_watcher_still_emits_every_field_this_tool_reads,
    test_a_starved_invocation_is_not_told_to_wait_for_a_line_it_cannot_reach,
    test_one_main_loop_line_is_decisive_against_starvation,
    test_a_sweep_shorter_than_one_gauge_period_is_not_starvation,
    test_the_sweep_position_is_the_index_of_the_primer_in_the_pending_list,
    test_list_primers_yields_the_collation_bash_globs_in,
    test_the_gauge_period_is_read_from_the_producer_not_assumed,
    test_a_sweep_spanning_midnight_is_not_a_negative_span,
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
