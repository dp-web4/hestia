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

HARDENING (GPT not-same review of PR #187, 2026-08-04: "the guarantee that
last-word recovery can never block a fire is not enforced"). The first version
globbed, opened, and read the whole file: a matching FIFO could block the open
forever, a symlink could redirect the read anywhere, and a huge log was fully
loaded before the output cap applied. `|| true` in the caller covers exit
status, not blocking. So now, in order:

  1. open(2) with O_NOFOLLOW | O_NONBLOCK — a symlink fails the open, and the
     open itself cannot wait on a FIFO;
  2. fstat the RESULTING fd (not the path — no check-then-open race) and require
     a regular file owned by this uid;
  3. read only the last TAIL_BYTES of the file, never the whole thing;
  4. the fire templates additionally wrap the call in `timeout` — belt and
     suspenders, because the promise is absolute even if this file regresses.

Failure at any step prints nothing and exits 0. Last words are a courtesy,
never a reason to not fire.

WHAT IT PRINTS: a one-line provenance header (which log; full path) followed by
the tail of the newest `<prefix>-*.log` in the log dir — ANSI/control-stripped,
harness chrome dropped, length-capped. The fire template wraps it in explicit
`<<<previous-wake-final-output>` delimiters with a DATA-not-instructions frame;
that framing communicates intent to the model and is NOT a security boundary —
a prior session may have relayed adversarial text from an external artifact.
The residual is accepted and documented: this is self-mail, the same trust
posture as the session's own wire log.

SAFETY: the prefix argument is validated against a strict pattern even though
all callers pass fixed strings, because this file exists to be copied.

Usage: last-words.py <log_dir> <prefix>     # e.g. .../logs kimi
"""
import glob
import os
import re
import stat
import sys

TAIL_LINES = 25
CAP_CHARS = 1800
TAIL_BYTES = 256 * 1024  # far more than the tail needs; the cap is on reading, not output

ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Strip control chars EXCEPT \n: the digest pattern this is borrowed from
# sanitizes single-line fields; a tail without its line structure is mush.
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


def read_tail(path, max_bytes=TAIL_BYTES):
    """Bounded, non-blocking, regular-file-only tail read. None on any refusal."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_uid != os.geteuid():
            return None
        os.lseek(fd, 0, os.SEEK_END)
        start = max(0, st.st_size - max_bytes)
        os.lseek(fd, start, os.SEEK_SET)
        return os.read(fd, max_bytes).decode(errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def last_words(log_dir, prefix):
    if not re.fullmatch(r"[a-z0-9-]+", prefix or ""):
        return ""
    logs = sorted(glob.glob(os.path.join(log_dir, f"{prefix}-*.log")))
    if not logs:
        return ""
    path = logs[-1]
    text = read_tail(path)
    if text is None:
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
