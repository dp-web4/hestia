#!/usr/bin/env python3
"""Pins the dead-wake classifier against the two traps that broke v1 (codex, review 7765).

Every fixture below is a shape observed in a real record under
~/.local/state/hestia-mesh/logs on 2026-09-02, reduced to the lines that carry the verdict.

Two arms. The POSITIVE arm asserts the terminal rule's verdicts. The SABOTAGE arm runs the
same negative fixtures through the v1 substring rule (still exported as
`wake_died(rule="substring")`) and asserts that v1 gets them WRONG -- so this file proves
the fixtures discriminate between the rules rather than merely that the current code
passes its own examples. If someone quietly re-widens the terminal rule back to a
substring, the positive arm goes red; if someone deletes the negative fixtures' teeth,
the sabotage arm goes red.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dead_wakes_are_not_availability as dw  # noqa: E402

DELIM = dw.DELIM

CODEX_DEAD = "hook: SessionStart Completed\nERROR: Your workspace is out of credits. Ask your workspace owner to refill in order to continue.\nERROR: Your workspace is out of credits. Ask your workspace owner to refill in order to continue.\n"
CODEX_DEAD_FOOTER = "...working...\nERROR: Your workspace is out of credits. Add credits to continue.\ntokens used\n167,656\n"
CODEX_DEAD_UNLISTED = "ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: https://x\ntokens used\n1,204\n"
KIMI_DEAD = "kimi version 0.39.1\nerror: failed to run prompt: provider.auth_error: 403 You've reached your weekly (7-day) usage limit. Your quota will reset when the current 7-day window ends.\nSee log: /home/dp/.kimi-code/logs/kimi-code.log\n"
CLAUDE_DEAD = "API Error: 529 Overloaded. This is a server-side issue, usually temporary — try again in a moment. If it persists, check https://status.claude.com.\n"

# Healthy wakes v1 called dead: prose about a peer, a design table, a grep in a diff, a
# code-block quote of the very error line (column 0), and grep -n output carrying it.
PROSE_PEER = "- **codex is dark.** out of credits since **2026-08-26 13:25:50**; four consecutive fires failed identically.\n\nSent bound reply 6231; binding_verified: true.\n"
PROSE_TABLE = "| **Tokens** | per-account usage, weekly reset | already the fleet's *de facto* governor (\"usage limits are our safeguard\") |\n\nArtifact: forum/codex-disposition-2026-07-26.md\n"
PROSE_GREP = "906\t  if printf '%s' \"$tail\" | grep -qi 'out of credits\\|insufficient credit\\|quota exceeded\\|usage limit'; then\n\nNo change needed; the branch already carries the fix.\n"
PROSE_CODEBLOCK = "The fire died with:\n```\nERROR: Your workspace is out of credits. Add credits to continue.\n```\nSo the four notices to codex are billing, not conduct. Reply 1425 sent, binding_verified: true.\n"
PROSE_GREP_N = "2108-ERROR: Your workspace is out of credits. Add credits to continue.\n2109-ERROR: Your workspace is out of credits. Add credits to continue.\n- This wake changed no files, so nothing was committed or pushed.\n"
# The echo trap: the previous wake's death is embedded before the delimiter.
ECHO = "ERROR: Your workspace is out of credits. Add credits to continue.\ntokens used\n12\n" + DELIM + "\nDrained 3 notices.\nFinal answer: all three acked.\n"
# The mirror of the echo trap: a healthy previous wake, and THIS one died.
ECHO_THEN_DEAD = "Final answer: all three acked.\n" + DELIM + "\n" + KIMI_DEAD

POSITIVE = [
    ("codex out-of-credits, error is last line", CODEX_DEAD, True, "out-of-credits"),
    ("codex error followed by tokens-used footer", CODEX_DEAD_FOOTER, True, "out-of-credits"),
    ("codex unlisted shape (401) still a death", CODEX_DEAD_UNLISTED, True, dw.UNCLASSIFIED),
    ("kimi usage limit + See log footer", KIMI_DEAD, True, "usage-limit"),
    ("claude 529 overloaded", CLAUDE_DEAD, True, "overloaded"),
    ("prose about a peer out of credits", PROSE_PEER, False, None),
    ("design table quoting 'usage limits'", PROSE_TABLE, False, None),
    ("grep pattern in a diff", PROSE_GREP, False, None),
    ("error line quoted in a code block, answer follows", PROSE_CODEBLOCK, False, None),
    ("grep -n output carrying the error line", PROSE_GREP_N, False, None),
    ("echo of previous dead wake, this one healthy", ECHO, False, None),
    ("healthy previous wake, this one dead", ECHO_THEN_DEAD, True, "usage-limit"),
    ("empty record", "", False, None),
]

# Negative fixtures v1 MUST misclassify for this file to have teeth. PROSE_CODEBLOCK and
# PROSE_GREP_N are the ones an "anchored anywhere in own output" rule (the first repair
# tried) also gets wrong -- they are why the rule is anchored AND terminal.
V1_MUST_MISS = [PROSE_PEER, PROSE_TABLE, PROSE_GREP, PROSE_CODEBLOCK, PROSE_GREP_N]
V1_MUST_SCORE_HEALTHY = [CODEX_DEAD_UNLISTED]


def _path(tmp, name, text):
    p = os.path.join(tmp, name)
    with open(p, "w") as fh:
        fh.write(text)
    return p


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, text, want_dead, want_class) in enumerate(POSITIVE):
            c = dw.classify(text)
            if c["dead"] != want_dead or c["death_class"] != want_class:
                failures.append("POSITIVE %-48s got dead=%s class=%s want dead=%s class=%s (terminal=%r)" % (
                    label, c["dead"], c["death_class"], want_dead, want_class, c["terminal"][:60]))
            p = _path(tmp, "codex-20260901-%06d.log" % i, text)
            if dw.wake_died(p) != want_dead:
                failures.append("wake_died(path) disagrees with classify for %r" % label)
        # SABOTAGE arm: v1 must be wrong on these, or the fixtures do not discriminate.
        for i, text in enumerate(V1_MUST_MISS):
            p = _path(tmp, "kimi-20260901-%06d.log" % i, text)
            if not dw.wake_died(p, rule="substring"):
                failures.append("SABOTAGE: v1 substring rule did NOT misfire on negative fixture %d -- fixture lost its teeth" % i)
        for i, text in enumerate(V1_MUST_SCORE_HEALTHY):
            p = _path(tmp, "codex-20260902-%06d.log" % i, text)
            if dw.wake_died(p, rule="substring"):
                failures.append("SABOTAGE: v1 scored the unlisted death as dead; the fixture no longer shows v1's blind spot")
        # The open-record guard: a file written just now is open, an old one is not.
        p = _path(tmp, "claude-20260901-000000.log", CLAUDE_DEAD)
        if not dw.is_open(p):
            failures.append("a record written this second must read as open")
        os.utime(p, (0, 0))
        if dw.is_open(p):
            failures.append("a record with a 1970 mtime must not read as open")
        try:
            dw.wake_died(p, rule="anywhere")
            failures.append("unknown rule name must raise, not silently pick one")
        except ValueError:
            pass
    if failures:
        print("FAIL (%d):" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("ok: %d positive fixtures, %d sabotage fixtures, open-record guard"
          % (len(POSITIVE), len(V1_MUST_MISS) + len(V1_MUST_SCORE_HEALTHY)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
