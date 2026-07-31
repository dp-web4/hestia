#!/usr/bin/env python3
"""An acceptance test that cannot survive the failure it measures reports a floor as a count.

`mesh_cli_exit_code_test.py` drives the real CLI and asserts things about its stdout.
Some of those assertions were computed EAGERLY in the argument list -- `json.loads(out)`
-- so on the exact input the case exists to catch (a crashing CLI, empty stdout) the
raise escaped to __main__ and killed the run. Measured on PR #137 against 51f8376's CLI:

    reported   13 red, no `FAILED:` line at all
    actual     15 of 25 red

Both runs exit 1. An uncaught exception exits 1; a clean `sys.exit(1)` after the toll
exits 1. CI cannot distinguish them, and the crashed run's only tell is a MISSING toll
line -- so the failure presented as a smaller number rather than as a failure. Same
shape the member-mesh thread keeps hitting: the failure path destroyed the evidence the
accountability layer needed (KINDS.md, three times).

This test is the instrument's instrument. It runs the real harness against a CLI stub
that always dies, and asserts the harness SAYS SO.

WHAT IT IS RED AGAINST, stated by configuration -- because "2 red before" is true of two
different setups and therefore identifies neither:

    base as-is (99ec1f9)        checks 1 and 2 red, for the WRONG reason. The seam
                                below is part of this commit, so the base harness
                                ignores the stub, measures the already-fixed real CLI,
                                and goes 25/25 green: rc=0, no toll line.
    base + the seam line only   checks 2 and 3 red -- the truncation itself. stdout
                                ends mid-line at `FAIL  K  payload refusal`.

The second is the measurement that means anything, and it needs one line backported. The
count is 2 either way: a number a wrong setup also produces is not evidence, which is the
same trap this file exists to write up, hit once more inside its own summary.

No new seam on hestia-mesh.py: the override is HESTIA_MESH_CLI, read by the harness, so
the no-test-seam posture the harness commits to for the CLI is untouched.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "mesh_cli_exit_code_test.py")

# A CLI that answers every invocation the way the real one did on an unhandled refusal:
# rc=1, nothing on stdout. That empty stdout is what json.loads() choked on.
STUB = "import sys\nsys.exit(1)\n"

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


if __name__ == "__main__":
    print("harness toll-truncation test")

    with tempfile.TemporaryDirectory() as td:
        stub = os.path.join(td, "always-dies.py")
        with open(stub, "w") as fh:
            fh.write(STUB)

        p = subprocess.run([sys.executable, HARNESS], capture_output=True, text=True,
                           timeout=180, env=dict(os.environ, HESTIA_MESH_CLI=stub))

    out = p.stdout
    tail = "\n".join(out.strip().splitlines()[-4:])

    # 1. Green on a CLI that does nothing at all would mean the harness measures nothing.
    #    Passes on the unhardened harness too -- it is here so a future "simplification"
    #    that makes the guard swallow the failure gets caught.
    check("harness reports failure against a dead CLI", p.returncode != 0, f"rc={p.returncode}")

    # 2. THE assertion. The unhardened harness dies at K and prints no toll line at all.
    check("harness prints a toll line, not just a traceback", "FAILED (" in out,
          f"tail={tail[:200]!r}")

    # 3. Silent truncation is the whole defect: an ANNOUNCED floor is a usable
    #    measurement, a floor presented as a count is not. So the run must either reach
    #    the last case (I, deliberately last) or say out loud that it stopped early.
    #
    #    Phrased against case I rather than an expected check COUNT on purpose, twice
    #    over: a count goes stale the next time a case is added, and `not died or ...`
    #    -- the obvious phrasing -- is vacuously green on the unhardened harness, which
    #    never prints "HARNESS DIED". That is the same "a pin whose value the bug also
    #    produces is not a pin" trap this branch exists to write up. It was green here
    #    before this rewrite; it is red now.
    died = "HARNESS DIED" in out
    reached_end = "I  nothing listening" in out
    check("run reaches the last case, or announces that it stopped early",
          reached_end or (died and "TRUNCATED" in out and "FLOOR" in out),
          f"reached_end={reached_end} died={died} tail={tail[:200]!r}")

    # 4. Every check the run DID reach is still individually reported -- the toll is a
    #    summary of the per-check lines, and losing those loses which cases were reached.
    check("per-check lines survive", out.count("  FAIL  ") + out.count("  PASS  ") > 0,
          f"no PASS/FAIL lines in {len(out)} bytes of stdout")

    # 5. The lazy-check fix and the death guard are two halves, and checks 1-4 only
    #    exercise the first: with the lazy form in place nothing above makes the hardened
    #    harness die, so `_death_guard` runs in no test at all and could rot unnoticed.
    #    The instrument's instrument had the same blind spot as the instrument -- one
    #    layer up, in miniature. (kimi-code, PR #140 review.)
    #
    #    So: run a COPY of the harness with a raise injected into a case body, and
    #    require it to announce the truncation. Red pre-fix too -- an unguarded harness
    #    tracebacks out with rc=1 and no TRUNCATED line, which is the defect itself.
    ANCHOR = '    dead = f"http://127.0.0.1:{srv.server_port}/mcp"'
    src = open(HARNESS).read()

    # A sabotage test that quietly stops sabotaging is exactly this branch's subject, so
    # a missing anchor is RED, never skipped.
    anchored = src.count(ANCHOR) == 1
    check("sabotage anchor still present in the harness", anchored,
          f"count={src.count(ANCHOR)} -- re-point ANCHOR at a line inside a case body")

    if anchored:
        with tempfile.TemporaryDirectory() as td:
            stub = os.path.join(td, "always-dies.py")
            with open(stub, "w") as fh:
                fh.write(STUB)
            # The copy sits in the tempdir: HERE moves with it, but HERE only resolves
            # CLI, and HESTIA_MESH_CLI overrides that.
            sab = os.path.join(td, "sabotaged_harness.py")
            with open(sab, "w") as fh:
                fh.write(src.replace(ANCHOR, '    raise RuntimeError("synthetic case-body raise")\n' + ANCHOR))
            s = subprocess.run([sys.executable, sab], capture_output=True, text=True,
                               timeout=180, env=dict(os.environ, HESTIA_MESH_CLI=stub))
        sout = s.stdout
        parts = {"HARNESS DIED": "HARNESS DIED" in sout, "TRUNCATED": "TRUNCATED" in sout,
                 "FLOOR": "FLOOR" in sout, "rc==1": s.returncode == 1}
        check("a raise out of a case body is announced as a truncated floor",
              all(parts.values()), f"rc={s.returncode} {parts}")

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)} recorded): {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nAll cases passed.")
