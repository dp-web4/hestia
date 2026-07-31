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
that always dies, and asserts the harness SAYS SO. It fails against the unhardened
harness on checks 2 and 3.

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

    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)} recorded): {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nAll cases passed.")
