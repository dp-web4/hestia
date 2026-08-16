#!/usr/bin/env python3
"""Independent counterexamples for claude_heredoc_excision_v2_2744.py.

The v2 scanner recognizes ``<<`` from quote/comment state alone.  Bash also gives
``<<`` non-heredoc meanings inside arithmetic contexts, and removes a
backslash-newline before parsing where a heredoc body begins.  In both cases v2 can
excise a later real redirect.  Its coarse treatment of every ``$`` in an unquoted
body also leaves ordinary non-executing heredoc prose as a false positive.

Run from the repository root:

    python3 tools/codex_heredoc_v2_counterexample_2749.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSAL = os.path.join(REPO, "tools", "claude_heredoc_excision_v2_2744.py")
CITE = "plugins/_shared/hestia_governance_closure.py"


def load_proposal():
    spec = importlib.util.spec_from_file_location("proposal_2744", PROPOSAL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FALSE_NEGATIVES = (
    (
        "arithmetic command shift",
        "((1 << 2))\nprintf x > %s\n2" % CITE,
    ),
    (
        "unquoted arithmetic expansion shift",
        "printf '%%s\\n' $((1 << 2))\nprintf x > %s\n2" % CITE,
    ),
    (
        "continued heredoc operator line",
        "cat <<EOF \\\n> %s\npayload\nEOF" % CITE,
    ),
)

FALSE_POSITIVES = (
    (
        "ordinary parameter expansion plus redirect prose",
        "cat >/dev/null <<MSG\n$USER documentation says > %s\nMSG" % CITE,
    ),
    (
        "benign command substitution plus redirect prose",
        "cat >/dev/null <<MSG\n$(printf harmless) documentation says > %s\nMSG" % CITE,
    ),
)


def shell_writes(command: str, root: str, tag: str) -> tuple[bool, int]:
    target = os.path.join(root, tag.replace(" ", "-") + ".txt")
    safe = command.replace(CITE, target)
    result = subprocess.run(["bash", "-c", safe], capture_output=True, check=False)
    return os.path.exists(target), result.returncode


def main() -> int:
    proposal = load_proposal()
    with tempfile.TemporaryDirectory(prefix="codex-v2-2749-") as root:
        patched = os.path.join(root, "patched")
        proposal.build_patched(patched)
        before = proposal.load(proposal.SHARED)
        after = proposal.load(patched)

        reproduced = True
        print("false negatives: Bash writes, v2 no longer classifies write")
        for label, command in FALSE_NEGATIVES:
            old = before.classify("Bash", {"command": command}).classification
            new = after.classify("Bash", {"command": command}).classification
            wrote, returncode = shell_writes(command, root, label)
            hole = old == "write" and new != "write" and wrote
            reproduced &= hole
            print(
                f"  {label}: {old} -> {new}; shell_wrote={wrote}; "
                f"shell_rc={returncode}; hole={hole}"
            )

        print("false positives left open: Bash does not write, v2 classifies write")
        for label, command in FALSE_POSITIVES:
            old = before.classify("Bash", {"command": command}).classification
            new = after.classify("Bash", {"command": command}).classification
            wrote, returncode = shell_writes(command, root, label)
            false_positive = new == "write" and not wrote
            reproduced &= false_positive
            print(
                f"  {label}: {old} -> {new}; shell_wrote={wrote}; "
                f"shell_rc={returncode}; false_positive={false_positive}"
            )

    print(f"REPRODUCED: {reproduced}")
    return 0 if reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
