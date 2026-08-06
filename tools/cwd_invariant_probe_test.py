#!/usr/bin/env python3
"""Positive control for `cwd_invariant_probe.py`: does it FIRE when the defect is present?

A probe that has never fired is a claim, not an instrument. This builds a synthetic
matcher with the same SHAPE as a real one -- an absolute self-directory marker plus a
set of governance basenames, some of which additionally require a gate-directory
segment -- plants a tree under it, and checks that the probe:

  * FAILS (exit 1) when the priced base and the landing base differ, and
  * PASSES (exit 0) when they are the same.

The synthetic matcher deliberately carries NONE of the real harness's marker strings.
That keeps this file writable (the gate scans proposed content for its own markers)
and keeps the control independent of the thing it controls: if it shared a literal
with the real matcher, a change to that literal would move both sides together and
the control would agree with the code by construction rather than by test.

The planted defect is the base-sensitivity of the segment test: a BARE basename
prices None from a base outside the gate directory (no segment in the resolved path)
and prices the filename from inside it. That is the class that overwrites the gate's
own code while the gate records nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
PROBE = os.path.join(HERE, "cwd_invariant_probe.py")

# A matcher with the real one's shape and none of its strings.
SYNTHETIC_MATCHER = '''
import os

_SELF = os.path.realpath(__file__)
_SELF_DIR = os.path.dirname(_SELF)
_SELF_MARKERS = (_SELF, _SELF_DIR)

_GOVERNANCE_FILES = ("zz_alpha.py", "zz_beta.py", "zz_shared_core.py")
# These need a gate-directory segment before they count -- the carve-out whose
# base-sensitivity is the planted defect.
_SEGMENT_ONLY = ("zz_alpha.py", "zz_beta.py")


def _touches_self(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return None
    resolved = []
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            resolved.append(v)
            try:
                resolved.append(os.path.realpath(v))
            except (OSError, ValueError):
                pass
    for h in resolved:
        for marker in _SELF_MARKERS:
            if marker and marker in h:
                return marker
        low = h.replace("\\\\", "/")
        in_segment = "gatedir/" in low or "/gatedir" in low
        for fname in _GOVERNANCE_FILES:
            if fname not in low:
                continue
            if fname in _SEGMENT_ONLY and not in_segment:
                continue
            return fname
    return None
'''


def build_tree(root: str) -> tuple[str, str]:
    """Plant a gate directory with governed files. Returns (matcher_path, gate_dir)."""
    gate_dir = os.path.join(root, "proj", "gatedir")
    os.makedirs(gate_dir)
    matcher_path = os.path.join(gate_dir, "zz_matcher_fixture.py")
    with open(matcher_path, "w") as fh:
        fh.write(SYNTHETIC_MATCHER)
    for fname in ("zz_alpha.py", "zz_beta.py", "zz_shared_core.py"):
        with open(os.path.join(gate_dir, fname), "w") as fh:
            fh.write("# governed\n")
    return matcher_path, gate_dir


def run(matcher: str, hook_base: str, landing_base: str, root: str):
    return subprocess.run(
        [sys.executable, PROBE, "--matcher", matcher, "--hook-base", hook_base,
         "--landing-base", landing_base, "--root", root],
        capture_output=True, text=True,
    )


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        real_tmp = os.path.realpath(tmp)
        matcher, gate_dir = build_tree(real_tmp)
        project_root = os.path.join(real_tmp, "proj")

        # ARM 1 -- bases diverge: hook prices from the project root, executor lands
        # inside the gate directory. The defect is present; the probe must fire.
        diverged = run(matcher, project_root, gate_dir, project_root)
        if diverged.returncode != 1:
            failures.append(
                f"diverged arm: expected exit 1 (FAIL), got {diverged.returncode}\n"
                f"stdout:\n{diverged.stdout}\nstderr:\n{diverged.stderr}"
            )
        else:
            # Fire on the right rows, not merely fire. The bare-basename spellings of
            # the segment-carve-out files are the ones that must price None.
            for expected in ("zz_alpha.py", "zz_beta.py"):
                if expected not in diverged.stdout:
                    failures.append(f"diverged arm did not report {expected}")
            if "PRICED   : None" not in diverged.stdout:
                failures.append(
                    "diverged arm fired but no row priced None -- the silent class "
                    "is the one that matters and it was not demonstrated"
                )

        # ARM 2 -- bases agree. Same tree, same matcher, same governed files: the only
        # thing that changed is the pair of bases, so a FAIL here would mean the probe
        # reports divergence that the bases do not contain.
        agreed = run(matcher, gate_dir, gate_dir, project_root)
        if agreed.returncode != 0:
            failures.append(
                f"agreed arm: expected exit 0 (PASS), got {agreed.returncode}\n"
                f"stdout:\n{agreed.stdout}\nstderr:\n{agreed.stderr}"
            )

        # ARM 3 -- the probe must refuse to report clean when it can see nothing.
        empty = os.path.join(real_tmp, "empty")
        os.makedirs(empty)
        blind = run(matcher, project_root, gate_dir, empty)
        if blind.returncode != 2:
            failures.append(
                f"blind arm: expected exit 2 (no governed files in root), got "
                f"{blind.returncode} -- 'nothing found' must not render as PASS"
            )

    if failures:
        print("CONTROL FAILED:\n")
        for f in failures:
            print(f"  - {f}\n")
        return 1
    print("control passed: probe fires on a planted divergence (naming the silent "
          "rows), stays quiet when the bases agree, and reports blindness distinctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
