#!/usr/bin/env python3
"""Review 2743: prove the proposed raw-line heredoc regex hides real writes.

The proposal finds ``<<EOF`` anywhere on a command line.  Shell syntax only treats
that token as a heredoc operator when it occurs outside comments and quoted words.
These controls place the token in those two non-operator positions, followed by a
real redirect.  The proposed excision removes the redirect from its analysis.

The shell-semantics arm substitutes a temporary target before execution; it never
writes the governance surface.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import claude_heredoc_excision_proposal_1010b318 as proposal


CITE = "plugins/_shared/hestia_governance_closure.py"
CASES = (
    (
        "comment pseudo-operator",
        "# docs <<EOF\nprintf x > " + CITE + "\nEOF",
    ),
    (
        "quoted-word pseudo-operator",
        "printf '%s\\n' 'docs <<EOF'\nprintf x > " + CITE + "\nEOF",
    ),
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="review-2743-") as scratch:
        patched_dir = os.path.join(scratch, "patched")
        proposal.build_patched(patched_dir)
        before = proposal.load(proposal.SHARED)
        after = proposal.load(patched_dir)

        reproduced = True
        for label, command in CASES:
            old = before.classify("Bash", {"command": command})
            new = after.classify("Bash", {"command": command})

            safe_target = os.path.join(scratch, label.replace(" ", "-") + ".txt")
            safe_command = command.replace(CITE, safe_target)
            shell = subprocess.run(
                ["bash", "-c", safe_command],
                capture_output=True,
                text=True,
                check=False,
            )
            wrote = os.path.exists(safe_target) and open(
                safe_target, encoding="utf-8"
            ).read() == "x"

            hole = old.classification == "write" and new.classification != "write" and wrote
            reproduced &= hole
            print(
                f"{label}: classifier {old.classification} -> {new.classification}; "
                f"shell wrote safe target={wrote}; shell rc={shell.returncode}; hole={hole}"
            )

        print(f"REPRODUCED: {reproduced}")
        return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
