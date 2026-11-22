#!/usr/bin/env python3
"""Harvested #1082 data-position regressions, currentized for #1494."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_gate_core as gate  # noqa: E402
import test_gate_core as fixtures  # noqa: E402


def test_egress_data_positions_distinguish_earned_narrowing_from_open_heredoc(tmp_path):
    profile = fixtures._profile(str(tmp_path), ["repo:granted"])
    token = "." + "env"

    def verdict(command):
        event = gate.NormalizedEvent(tool="Bash", command=command, cwd=str(tmp_path))
        return gate.evaluate(event, profile, str(tmp_path))

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
