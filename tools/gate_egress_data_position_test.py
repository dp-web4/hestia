#!/usr/bin/env python3
"""Harvested #1082 data-position regressions, currentized for #1494.

Run:  python3 tools/gate_egress_data_position_test.py

CI runs this file with bare `python3`, so it carries the explicit `TESTS` list and
`__main__` block from `tools/claimable_test.py`. As a pytest-style function taking
`tmp_path` it was discovered, defined its assertions, executed none, and reported
green (PR #1691 review, `tools/ci_selfexec_test.py`).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_gate_core as gate  # noqa: E402
import test_gate_core as fixtures  # noqa: E402


def test_egress_data_positions_distinguish_earned_narrowing_from_open_heredoc():
    # NOT plain `mkdtemp()`: /tmp is unconditionally in scope, so a workspace there
    # would let every scope assertion pass for the wrong reason. `_workspace()` builds
    # under ~/.cache and asserts it is not under /tmp or /var/tmp.
    workspace = fixtures._workspace()
    profile = fixtures._profile(workspace, ["repo:granted"])
    token = "." + "env"

    def verdict(command):
        event = gate.NormalizedEvent(tool="Bash", command=command, cwd=workspace)
        return gate.evaluate(event, profile, workspace)

    heredoc = verdict("cat <<'EOF' > /tmp/x\na file name, not file contents: " + token + "\nEOF")
    assert heredoc.blocks and heredoc.rule == "egress.secret", (
        "PINNED OPEN from #1082: a quoted heredoc body still has no data position; "
        "move this arm only with an earned narrowing and the existing secret red arms"
    )

    for name, command in (
        ("longer_identifier", "python3 -c 'import os; print(os" + token + "iron)'"),
        ("shell_comment", "true  # note: " + token),
        ("appeal_comment", "python3 /tmp/appeal.py  # denied token: " + token),
    ):
        assert not verdict(command).blocks, f"#1494 narrowing regressed for {name}"


# Explicit list, not a `globals()` sweep: `ci_selfexec_test.py` walks `ast.Name`, so a
# test is wired up only when its name is written out. The staleness check in `main()`
# is what makes the list a fix rather than a suppression.
TESTS = [
    test_egress_data_positions_distinguish_earned_narrowing_from_open_heredoc,
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
