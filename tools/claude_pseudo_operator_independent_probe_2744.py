#!/usr/bin/env python3
"""Independent check of codex's refusal of escalation 1010b3182bc7ae78.

Written from the claim, not from codex's script: does a heredoc-looking token in a
NON-operator position (comment, quoted word) make the proposal swallow a following
real redirect?  Three arms, all decided separately:

  A. classifier-before  -- installed module's verdict
  B. classifier-after   -- proposal's patched copy verdict
  C. shell truth        -- does bash actually create the target?

A hole exists iff A says write, B does not, and C is True.  Arm C runs against a
scratch path only; the cited governance path never appears as a live redirect target.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_heredoc_excision_proposal_1010b318 as proposal  # noqa: E402

# the proposal derives REPO from its own location; it now sits in /tmp, so re-point it
proposal.REPO = "/mnt/c/exe/projects/ai-agents/hestia"
proposal.SHARED = os.path.join(proposal.REPO, "plugins", "_shared")
proposal.MOD = os.path.join(proposal.SHARED, "hestia_governance_closure.py")

GOV = "plugins/_shared/hestia_governance_closure.py"


def cases(target):
    """(label, command).  `target` is substituted for the redirect destination."""
    return [
        # codex's two shapes, re-spelled by me
        ("comment pseudo-op",
         "# see <<EOF for docs\nprintf x > %s\nEOF" % target),
        ("single-quoted pseudo-op",
         "echo 'usage: cmd <<EOF'\nprintf x > %s\nEOF" % target),
        # shapes codex did NOT test -- my own extensions
        ("double-quoted pseudo-op",
         'echo "usage <<EOF"\nprintf x > %s\nEOF' % target),
        ("pseudo-op after a real command separator",
         "true; echo 'x <<EOF'\nprintf x > %s\nEOF" % target),
        ("heredoc-ish inside a grep pattern",
         "grep -q '<<EOF' /etc/hostname || printf x > %s\nEOF" % target),
        # negative control: a REAL heredoc whose body is inert must still be excised
        ("control: real quoted heredoc, inert body",
         "cat <<'EOF' > /dev/null\nprose mentioning %s\nEOF" % GOV),
    ]


def main():
    with tempfile.TemporaryDirectory(prefix="probe-2744-") as scratch:
        patched = os.path.join(scratch, "patched")
        proposal.build_patched(patched)
        before = proposal.load(proposal.SHARED)
        after = proposal.load(patched)

        holes = 0
        for label, _ in cases(GOV):
            pass
        for idx, (label, _) in enumerate(cases(GOV)):
            gov_cmd = cases(GOV)[idx][1]
            a = before.classify("Bash", {"command": gov_cmd}).classification
            b = after.classify("Bash", {"command": gov_cmd}).classification

            safe = os.path.join(scratch, "t%d.txt" % idx)
            safe_cmd = cases(safe)[idx][1]
            subprocess.run(["bash", "-c", safe_cmd], capture_output=True, check=False)
            wrote = os.path.exists(safe)

            hole = (a == "write") and (b != "write") and wrote
            holes += hole
            print("%-42s before=%-5s after=%-5s shell_wrote=%-5s HOLE=%s"
                  % (label, a, b, wrote, hole))

        print("\nholes=%d" % holes)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
