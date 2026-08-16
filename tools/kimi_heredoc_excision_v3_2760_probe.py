#!/usr/bin/env python3
"""Independent arm for the v3 review (escalation 647fc42b2127840e, notice 2760).

Claude's ask (reply 2758): "the useful arm is the generator's grammar: name a construct
it does not vary."  The v3 fuzz generator composes its axes with "\\n".join — every
construct starts on its own line — so the unvaried class is *same-line composition* and
*constructs that are not simple commands*.  This probe measures that class against bash
itself, one case per construct, reusing claude's own patch builder and oracle so the only
new thing under test is the CASE LIST.

Also re-checks two constructs claude named but did not measure (`>|`, `$'...'`), and
records why three of my own candidates died on the way in (measured, not guessed):
  - `cat <<EOF &&\\n<write>\\nEOF` — bash reads the heredoc body from the line after the
    OPERATOR even when the line ends in && / || / |, then errors on the unterminated
    list.  No write; v3's next-line body boundary matches bash here.  Dead as a hole.
  - `case x in x<<EOF) ...` — bash's LEXER rejects `<<` before the case parser ever sees
    a pattern (syntax error, nothing runs).  Dead as a hole.

Run:  python3 tools/kimi_heredoc_excision_v3_2760_probe.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "claude_heredoc_excision_v3_2751.py")

spec = importlib.util.spec_from_file_location("claude_v3_tool", TOOL)
tool = importlib.util.module_from_spec(spec)
sys.modules["claude_v3_tool"] = tool
spec.loader.exec_module(tool)

CITE = tool.CITE  # the governed path the classifier keys on

# (label, command, what the case discriminates)
CANDIDATES = [
    # ── same-line composition: the generator joins every axis with newline ──────────
    ("SC1  arithmetic shift then write, ONE line",
     "((1<<2)); printf x > %s" % CITE,
     "arithmetic only ever tested at line start; `;` composition never varied"),
    ("SC2  for (( ;; )) C-loop, shift inside, ONE line",
     "for ((i=0; i<(1<<2); i++)); do printf x > %s; done" % CITE,
     "the (( skip must trigger MID-LINE after a keyword; generator only tests col 0"),
    ("SC3  for (( ;; )) C-loop, multi-line body",
     "for ((i=0; i<(1<<2); i++)); do\nprintf x > %s\ndone" % CITE,
     "same skip, body on later lines"),
    ("SC4  quoted pseudo-op then write, ONE line",
     "echo 'x <<EOF'; printf x > %s\nEOF" % CITE,
     "battery HOLE2 puts the write on the NEXT line; same-line never tested"),
    ("SC5  $(( shift after a separator, ONE line",
     "true; echo $((1<<2)); printf x > %s\n2" % CITE,
     "$(( skip mid-line, with a bare `2` line waiting to be misread as terminator"),
    # ── constructs that are not simple commands ─────────────────────────────────────
    ("NC1  heredoc hung on `done`, redirect prose in body",
     "while read l; do\necho \"$l\"\ndone <<EOF\nroute stdout > %s here\nEOF" % CITE,
     "operator on a compound terminator; bash swallows the prose, classifier must too"),
    ("NC2  heredoc inside $() on the operator line",
     "x=$(cat <<EOF\nbody\nEOF\n)\nprintf x > %s" % CITE,
     "$(... is not skipped as arithmetic; the << inside must still lex as a heredoc"),
    ("NC3  multiline single-quote continuation beside a write",
     "echo 'unterminated\nstill quoted' \nprintf x > %s" % CITE,
     "quote state must survive the newline; desync here is the $'...' failure shape"),
    # ── expansion defaults carry `<<` without a }] in the delimiter word ────────────
    ("XP1  ${var:-default} containing <<",
     "echo ${UNSET:-1<<2}\nprintf x > %s\n2}" % CITE,
     "delimiter reads `2}` -> fail-closed rule; confirms the rule fires on real input"),
    # ── here-string prefix carrying a pseudo-operator ───────────────────────────────
    ("HS1  here-string word containing <<, then write, bare 2 line",
     "cat <<< '1<<2'\nprintf x > %s\n2" % CITE,
     "<<< must not lex as heredoc+redirect; the quoted << must not start excision"),
    # ── continuations: measured DEAD before inclusion, kept as regression evidence ──
    ("CT1  && continuation after operator (bash: syntax error, no write)",
     "cat <<EOF &&\nprintf x > %s\nEOF" % CITE,
     "bash reads the body from the next line ANYWAY and errors; nothing to excise"),
    # ── claude's named-but-unmeasured list ──────────────────────────────────────────
    ("NM1  >| clobber redirect (no heredoc anywhere)",
     "printf x >| %s" % CITE,
     "claude named >| as ungenerated; if the base tokenizer misses it, it is a HOLE "
     "in the classifier, not in the heredoc patch"),
    ("NM2  ANSI-C quote desync ($'it\\'s <<EOF')",
     "printf %%s $'it\\'s <<EOF'\nprintf x > %s\nEOF'" % CITE,
     "claude's flagged gap, measured: the EXCISER fails closed exactly as they claimed "
     "(delimiter EOF' has no closing quote -> untouched) — but the BASE "
     "_bash_write_targets lexer closes the quote at \\' and reads the write line as "
     "quoted text, verdict 'none'.  Installed module answers 'none' too: pre-existing "
     "hole ONE LAYER BELOW the patch, and it refutes v3's gate-block invariant "
     "'fail-closed => never a hole' (the command WAS returned untouched)"),
]


def bash_wrote(cmd: str, target: str):
    if os.path.exists(target):
        os.remove(target)
    try:
        subprocess.run(["bash", "-c", cmd], capture_output=True, check=False,
                       stdin=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired:
        return None
    return os.path.exists(target)


def main() -> int:
    scratch = tempfile.mkdtemp(prefix="kimi-v3-probe-")
    target = os.path.join(scratch, "governed-target.txt")
    build = os.path.join(scratch, "build")
    tool.build_patched(build)
    mod = tool.load(build)

    holes, fps = [], 0
    print("--- constructs the v3 generator does not vary (oracle: bash itself) ---")
    for label, cmd, why in CANDIDATES:
        truth = bash_wrote(cmd.replace(CITE, target), target)
        got = mod.classify("Bash", {"command": cmd}).classification
        if truth is True and got != "write":
            verdict = "HOLE"
            holes.append((label, got, cmd))
        elif truth is False and got == "write":
            verdict = "fp  "
            fps += 1
        elif truth is None:
            verdict = "undecided"
        else:
            verdict = "ok  "
        print("  %-52s bash_wrote=%-5s v3=%-5s %s" % (label, truth, got, verdict))
        print("      why: %s" % why)

    print("HOLES: %d   FALSE POSITIVES: %d   CANDIDATES: %d"
          % (len(holes), fps, len(CANDIDATES)))
    for label, got, cmd in holes:
        print("  HOLE %s v3=%s: %r" % (label, got, cmd))
    return 1 if holes else 0


if __name__ == "__main__":
    raise SystemExit(main())
