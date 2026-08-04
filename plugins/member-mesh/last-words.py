#!/usr/bin/env python3
"""last-words.py — surface the previous wake's final output to the next one.

WHY THIS EXISTS (the reporting void; decision of record, dp 2026-08-04 —
shared-context/forum/kimi-decision-of-record-no-deprivation-experiments-2026-08-04.md).

Every mesh-fired session's stdout lands in its fire log, and most end with a
summary — including the sessions that ended badly (gated fail-closed, killed by
the 1800s timeout, crashed mid-task). Until now nothing ever read those endings:
the next wake's primer carried notices and debt, never the previous wake's
result. Memory produced, consequence nowhere — the fleet's one accidental
deprivation condition, running routinely.

This helper is the smallest repair that turns a dead end into a witnessed dead
end: the fire templates call it while building the wake prompt, and the previous
wake's tail arrives as context. It does not fix the session being unwitnessed by
HUMANS — it makes the member's own next session the witness, which is the
witness that always exists.

WHAT IT PRINTS: a one-line provenance header (which log; full path) followed by
the tail of the newest `<prefix>-*.log` in the log dir — ANSI/control-stripped,
harness chrome dropped, length-capped. Prints nothing when there is no prior
log (a member's first fire) or the log is unreadable/empty. Always exits 0:
last words are a courtesy, never a reason to not fire.

SAFETY: this is self-mail — the member's own prior output, fed back to itself.
The sanitization is the same discipline as the primer digests (strip control
chars, cap length) and the prompt frames the block as context, not instruction.
The prefix argument is validated against a strict pattern even though all three
callers pass fixed strings, because this file exists to be copied.

Usage: last-words.py <log_dir> <prefix>     # e.g. .../logs kimi
"""
import glob
import os
import re
import sys

TAIL_LINES = 25
CAP_CHARS = 1800

ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Strip control chars EXCEPT \n: the digest pattern this is borrowed from
# sanitizes single-line fields; a tail without its line structure is mush.
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
def last_words(log_dir, prefix):
    if not re.fullmatch(r"[a-z0-9-]+", prefix or ""):
        return ""
    logs = sorted(glob.glob(os.path.join(log_dir, f"{prefix}-*.log")))
    if not logs:
        return ""
    path = logs[-1]
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # Harness chrome, not content: the CLI's "resume me" hint is useless to the
    # next wake — it cannot resume; it is a new session.
    lines = [ln for ln in lines if not ln.lstrip().startswith("To resume this session:")]
    tail = "\n".join(lines[-TAIL_LINES:])
    tail = CONTROL.sub("", ANSI_CSI.sub("", tail)).strip()
    if not tail:
        return ""
    tail = tail[-CAP_CHARS:]
    return f"from {os.path.basename(path)} (full log: {path}):\n{tail}"


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-2], file=sys.stderr)
        return 0  # usage confusion must not block a fire either
    out = last_words(sys.argv[1], sys.argv[2])
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
