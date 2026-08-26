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


TESTS = [
    test_parses_the_real_journal_line,
    test_a_non_artifact_line_is_not_half_parsed,
    test_unverifiable_is_not_ok,
    test_drift_and_ok_match_the_shell_guard,
    test_agreeing_fd_witnesses_are_uninformative,
    test_cat_lying_is_detected_by_the_size_disagreement,
    test_a_genuinely_held_old_inode_still_does_not_date_the_parse,
    test_size_is_not_a_key,
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
