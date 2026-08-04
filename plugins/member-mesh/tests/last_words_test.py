#!/usr/bin/env python3
"""A wake's last words must reach the next wake — and must never block it.

WHY (decision of record, dp 2026-08-04 —
shared-context/forum/kimi-decision-of-record-no-deprivation-experiments-2026-08-04.md).
Every mesh-fired session's stdout lands in its fire log, most sessions ending
with a summary — including sessions stopped fail-closed or killed by the 1800s
timeout. Until last-words.py, nothing ever read those endings: the next primer
carried notices and debt, never the previous wake's result. Memory produced,
consequence nowhere — the reporting void, the fleet's one accidental
deprivation condition, and (measured in the continuity study,
shared-context/explorations/continuity-study-kimi-2026-08-04) the concentration
point of the 8% of sessions that evaporate.

The repair is a courtesy with one hard property: last words must NEVER block a
fire. They are context, not infrastructure. So:

  A. EXTRACTION (behavioural, against the real helper). Newest log wins; the
     tail keeps its line structure (a first-pass bug stripped \\n with the
     other control chars and rendered summaries as mush — the digest
     sanitizer's pattern, wrong for multi-line content); ANSI/control chars
     gone; harness chrome ("To resume this session:") dropped; length capped;
     no prior log / unreadable log / garbage log all yield empty output, rc 0.
  B. ADOPTION (static, derived from the scripts — the property-A discipline of
     fire_sender_allowlist_test.py). Every fire-*.sh template must call
     last-words.py with the prefix its own STAMP line writes, and must splice
     $LAST_WORDS_BLOCK into its PROMPT. A fourth template inherits the demand,
     not the gap.

Usage: ./last_words_test.py     (runtime ~1s)
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
HELPER = os.path.join(MESH, "last-words.py")

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def run(log_dir, prefix):
    return subprocess.run(
        [sys.executable, HELPER, log_dir, prefix],
        capture_output=True, text=True, timeout=30,
    )


def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


# --- A. extraction ---------------------------------------------------------

with tempfile.TemporaryDirectory() as d:
    # A1: no logs at all -> empty, rc 0 (a member's first fire must fire)
    r = run(d, "kimi")
    check("A1 first fire: no logs -> empty output, rc 0", r.returncode == 0 and r.stdout == "", repr(r))

    # A2: newest log wins (lexical sort = chronological for the STAMP format)
    write(os.path.join(d, "kimi-20260101-000000.log"), "old session\nlast line of OLD\n")
    write(os.path.join(d, "kimi-20260202-000000.log"), "new session\nlast line of NEW\n")
    r = run(d, "kimi")
    check("A2 newest log wins", "last line of NEW" in r.stdout and "last line of OLD" not in r.stdout, repr(r.stdout))

    # A3: provenance header names the source log
    check("A3 provenance header", r.stdout.startswith("from kimi-20260202-000000.log"), repr(r.stdout[:80]))

    # A4: line structure survives sanitization (the \\n-eating bug)
    write(os.path.join(d, "kimi-20260303-000000.log"), "first line\nsecond line\nthird line\n")
    r = run(d, "kimi")
    check("A4 multi-line tail keeps its lines", "first line\nsecond line\nthird line" in r.stdout, repr(r.stdout))

    # A5: ANSI CSI and control chars stripped, \\n preserved
    write(os.path.join(d, "kimi-20260404-000000.log"), "\x1b[31mred text\x1b[0m\x07\nplain\x01line\n")
    r = run(d, "kimi")
    check("A5 ANSI + control stripped, newline kept",
          "red text" in r.stdout and "\x1b" not in r.stdout and "\x07" not in r.stdout
          and "\x01" not in r.stdout and "plainline" in r.stdout.replace("\n", "") or "plain" in r.stdout,
          repr(r.stdout))

    # A6: harness chrome dropped
    write(os.path.join(d, "kimi-20260505-000000.log"), "real summary\nTo resume this session: kimi -r session_xyz\n")
    r = run(d, "kimi")
    check("A6 resume-chrome dropped", "real summary" in r.stdout and "To resume this session" not in r.stdout, repr(r.stdout))

    # A7: length capped (CAP_CHARS=1800 + header line)
    write(os.path.join(d, "kimi-20260606-000000.log"), "x" * 5000 + "\n")
    r = run(d, "kimi")
    check("A7 output capped", 0 < len(r.stdout) < 1900, f"len={len(r.stdout)}")

    # A8: empty log -> empty output
    write(os.path.join(d, "kimi-20260707-000000.log"), "   \n\n")
    r = run(d, "kimi")
    check("A8 whitespace-only log -> empty", r.returncode == 0 and r.stdout == "", repr(r))

    # A9: garbage/binary log -> rc 0, no traceback
    with open(os.path.join(d, "kimi-20260808-000000.log"), "wb") as fh:
        fh.write(b"\xff\xfe\x00\x01binary\xff" * 100)
    r = run(d, "kimi")
    check("A9 binary log: rc 0, no traceback", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[:200])

    # A10: other members' logs are not read
    r = run(d, "claude")
    check("A10 prefix isolation (no claude logs in a kimi dir)", r.stdout == "", repr(r.stdout))

    # A11: hostile prefix rejected, rc 0
    r = run(d, "../../etc")
    check("A11 path-ish prefix refused quietly", r.returncode == 0 and r.stdout == "", repr(r))


# --- B. adoption (static, derived from the fire templates) ------------------

templates = [f for f in os.listdir(MESH) if re.fullmatch(r"fire-[a-z]+\.sh", f)]
check("B0 at least the three known templates exist",
      {"fire-kimi.sh", "fire-claude.sh", "fire-codex.sh"} <= set(templates), str(templates))

for tpl in sorted(templates):
    src = open(os.path.join(MESH, tpl)).read()
    member = tpl[len("fire-"):-len(".sh")]
    # The prefix the STAMP line writes, derived — not assumed to equal the name.
    m = re.search(rf'\$LOG_DIR/({re.escape(member)}[a-z-]*)-\$STAMP\.log', src)
    prefix = m.group(1) if m else None
    check(f"B1 {tpl}: log prefix derivable", prefix is not None, tpl)
    if prefix is None:
        continue
    check(f"B2 {tpl}: calls last-words.py with its own prefix",
          re.search(rf'last-words\.py"\s+"\$LOG_DIR"\s+{re.escape(prefix)}\b', src) is not None, tpl)
    check(f"B3 {tpl}: splices $LAST_WORDS_BLOCK into PROMPT",
          re.search(r'PROMPT="[^"]*\$LAST_WORDS_BLOCK', src, re.S) is not None
          or "$DIGEST$DEBT_BLOCK$LAST_WORDS_BLOCK" in src, tpl)
    check(f"B4 {tpl}: helper failure cannot abort the fire (|| true)",
          "last-words.py\" \"$LOG_DIR\" " + prefix + " 2>/dev/null || true" in src, tpl)
    check(f"B5 {tpl}: HERE_DIR derived exactly once",
          src.count('HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"') == 1, tpl)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
