#!/usr/bin/env python3
"""Prove `tools/ci_shaped_run.py` can go RED for the reasons it claims.

A pre-push check that has only ever printed green is a claim, not a check --
and this one is especially easy to get wrong in the silent direction, because
every one of its strips is invisible when it fails to apply. If the depth were
ignored, or `HOME` leaked, the sweep would still pass and would still say
"shaped checkout".

So each strip gets a live probe: a file that FAILS under the shaping and PASSES
on the developer host. The contrast is the control -- a probe that reds under
both arms would only prove the probe is broken.

The two probes are not invented. They are the two defects that reached main and
had to be fixed from CI logs (`4be4110`, `ff18fe4`): `HEAD~1` on a depth-1
checkout, and `commit-tree` with no ambient `user.name`.

NOTE ON THIS FILE IN CI. It runs in the `plugin tests (python)` sweep, where the
host arm cannot be demonstrated for the identity probe: `actions/checkout` sets
no identity, so the host and the shaped run agree and the contrast is
unavailable. That is reported, not skipped silently, and the shaped arm is still
asserted -- an unavailable contrast weakens the evidence without excusing the
claim.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

HARNESS = REPO / "tools" / "ci_shaped_run.py"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Probes exit 0 when the ambient thing IS available. Under the shaping it must
# not be, so a correct harness turns each of these red.
PROBE_IDENTITY = f"""#!/usr/bin/env python3
import subprocess, sys
p = subprocess.run(["git", "commit-tree", "{EMPTY_TREE}", "-m", "probe"],
                   capture_output=True, text=True)
print("commit-tree rc=%d %s" % (p.returncode, p.stderr.strip()[-120:]))
sys.exit(p.returncode)
"""

PROBE_DEPTH = """#!/usr/bin/env python3
import subprocess, sys
p = subprocess.run(["git", "rev-parse", "HEAD~1"], capture_output=True, text=True)
print("rev-parse HEAD~1 rc=%d %s" % (p.returncode, p.stderr.strip()[-120:]))
sys.exit(p.returncode)
"""

# The negative control. Nothing here is ambient, so it must stay GREEN -- and it
# asserts the shaping actually applied, so a harness that simply fails every
# probe cannot pass this file by failing the other two.
PROBE_INERT = """#!/usr/bin/env python3
import os, pathlib, subprocess, sys
refs = subprocess.run(["git", "for-each-ref", "refs/remotes"],
                      capture_output=True, text=True).stdout.strip()
home = pathlib.Path(os.environ["HOME"])
leftovers = sorted(p.name for p in home.iterdir()) if home.is_dir() else ["<missing>"]
print("remote refs=%r home=%s contents=%r" % (refs, home, leftovers))
assert refs == "", "shaped checkout carries remote-tracking refs: %r" % refs
assert leftovers == [], "HOME was not empty: %r" % leftovers
sys.exit(0)
"""


def _write_probe(body: str, name: str) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix="shaped-probe-"))
    p = d / name
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)
    return p


def _host_arm(probe: pathlib.Path) -> int:
    """The probe, run the way a developer runs a test: in this checkout, as me."""
    return subprocess.run(
        [sys.executable, str(probe)], cwd=REPO, capture_output=True, text=True,
    ).returncode


def _shaped_arm(probe: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "--probe", str(probe)],
        cwd=REPO, capture_output=True, text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _report_unavailable_contrast(which: str, why: str) -> None:
    """Deliver the weakened arm to whatever is running this file.

    Printing alone reaches the CI log and nothing else; a warning reaches
    pytest too. Same delivery lesson as `gate_false_refusal_test.py` -- the
    fix for a host-shaped skip is to make the skip legible, not to assert an
    environment.
    """
    msg = f"CONTRAST UNAVAILABLE for {which}: {why}"
    print(f"  !! {msg}")
    import warnings
    warnings.warn(msg, RuntimeWarning, stacklevel=2)


def test_the_shaping_strips_ambient_git_identity():
    """`commit-tree` needs an author. `actions/checkout` provides none."""
    probe = _write_probe(PROBE_IDENTITY, "identity_probe.py")
    host = _host_arm(probe)
    shaped, log = _shaped_arm(probe)
    print(f"  identity probe: host rc={host}  shaped rc={shaped}")
    assert shaped != 0, (
        "the shaped run minted a commit, so ambient identity reached it -- the "
        "harness would have been green on ff18fe4's defect.\n" + log)
    if host == 0:
        print("  -> contrast held: green on this host, red under the shaping")
    else:
        _report_unavailable_contrast(
            "the identity probe",
            "this host also has no git identity (CI is such a host), so both arms "
            "are red and the red proves less than it does on a developer machine")


def test_the_shaping_strips_history_beyond_depth_1():
    """`HEAD~1` exists on a developer clone and not under `actions/checkout`."""
    probe = _write_probe(PROBE_DEPTH, "depth_probe.py")
    host = _host_arm(probe)
    shaped, log = _shaped_arm(probe)
    print(f"  depth probe: host rc={host}  shaped rc={shaped}")
    assert shaped != 0, (
        "`HEAD~1` resolved inside the shaped checkout, so the depth was not "
        "honoured -- `git clone --depth` is silently ignored for a local PATH, "
        "which is exactly the way to build this tool wrong.\n" + log)
    if host == 0:
        print("  -> contrast held: green on this host, red under the shaping")
    else:
        _report_unavailable_contrast(
            "the depth probe",
            "this checkout is itself shallow, so both arms are red")


def test_a_probe_needing_nothing_ambient_stays_green():
    """The negative control, and the one that makes the other two mean anything.

    Without it, a harness that failed EVERY probe -- a typo in the runner, a
    missing interpreter -- would pass both red-arm assertions above and read as
    a working control. This probe also asserts the two strips from inside the
    shaped checkout, so it fails loudly if the shaping silently did nothing.
    """
    probe = _write_probe(PROBE_INERT, "inert_probe.py")
    shaped, log = _shaped_arm(probe)
    print(f"  inert probe: shaped rc={shaped}")
    assert shaped == 0, (
        "a probe that touches nothing ambient went red under the shaping, so the "
        "red arms above are not evidence about ambience.\n" + log)


def main() -> int:
    """Called BY NAME -- `tools/ci_selfexec_test.py` reads this statically and a
    `globals()` dispatch is invisible to it (see `citation_refpop_symref_test.py`,
    which learned that the expensive way)."""
    tests = [
        test_the_shaping_strips_ambient_git_identity,
        test_the_shaping_strips_history_beyond_depth_1,
        test_a_probe_needing_nothing_ambient_stays_green,
    ]
    failures = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
        else:
            print(f"ok   {fn.__name__}")
    print(f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
