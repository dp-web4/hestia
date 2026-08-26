#!/usr/bin/env python3
"""Measure the read-only classifier's GRAMMAR COVERAGE, not its read/write accuracy.

The gate refuses a governance-marker-carrying command when the classifier does not
CONFIDENTLY call it read-only. The classifier is lexical with a closed grammar and
fails closed outside it, by deliberate design (see its own docstring, codex review
2026-08-02) -- unparseable input is a write, unknown syntax is a write.

That design is sound for a lexical classifier. This tool measures the consequence
nobody has put a number on: how much of the read-only command space falls outside
the grammar, and therefore how much of the escalation traffic is a refusal of a
command that writes nothing.

TWO TIERS, because ground truth is the hard part.

  Tier 1 -- MINIMAL PAIRS, ground truth by construction. Each pair reads the SAME
  bytes and writes nothing in either arm; the arms differ ONLY in shell grammar.
  Any pair that splits (allow / deny) is a false refusal with certainty, because
  the effect is identical by construction. No judgment call is involved.

  Tier 2 -- REAL CORPUS, this seat's own transcripts. Reports the rate at which
  commands actually issued fall out of grammar. Ground truth is NOT claimed for
  tier 2; it is a magnitude, and the write-verb screen below is a conservative
  LOWER bound on false refusals, not an estimate of them.

Costs zero escalations: the classifier is imported and called, never triggered.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

# The INSTALLED hook, not the checked-out tree. Gate semantics must be read from what
# is actually enforcing (the tree here is parked on a branch and is not the vintage in
# force). Overridable so the same tool can measure a candidate fix before it installs.
DEFAULT_HOOK = Path.home() / ".claude" / "hooks" / "hestia" / "pre_tool_use.py"


def load_classifier(hook_path: Path):
    """Import the hook as a module and hand back its classifier.

    Safe: the hook guards `main()` behind `__name__ == "__main__"`, so importing
    evaluates definitions only and decides nothing.
    """
    spec = importlib.util.spec_from_file_location("_gate_under_test", hook_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {hook_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gate_under_test"] = mod
    spec.loader.exec_module(mod)
    fn = getattr(mod, "_is_read_only", None)
    if fn is None:
        raise SystemExit(f"{hook_path} exposes no _is_read_only -- wrong vintage?")
    return fn, mod


# --- Tier 1 ----------------------------------------------------------------
#
# Every pair: BOTH arms read the same bytes, NEITHER arm writes. `A` is written in
# grammar the classifier enumerates; `B` uses a construct outside it. The label names
# the construct under test, so a split is attributable to one feature.

PAIRS = [
    (
        "process-substitution",
        "diff /etc/hostname /etc/hostname",
        "diff <(cat /etc/hostname) <(cat /etc/hostname)",
    ),
    (
        "command-substitution",
        "grep -c . /etc/hostname",
        "echo $(grep -c . /etc/hostname)",
    ),
    (
        "for-loop",
        "cat /etc/hostname /etc/hostname",
        "for f in /etc/hostname /etc/hostname; do cat $f; done",
    ),
    (
        "while-loop",
        "head -1 /etc/hostname",
        "while read -r l; do echo $l; done < /etc/hostname",
    ),
    (
        "brace-group",
        "cat /etc/hostname",
        "{ cat /etc/hostname; }",
    ),
    (
        "subshell",
        "cat /etc/hostname",
        "(cat /etc/hostname)",
    ),
    (
        "or-else-branch",
        "test -f /etc/hostname",
        "test -f /etc/hostname || echo missing",
    ),
    (
        "devnull-redirect-to-variable",
        "cat /etc/hostname 2>/dev/null",
        "D=/dev/null; cat /etc/hostname 2>$D",
    ),
    (
        "backtick-substitution",
        "wc -l /etc/hostname",
        "echo `wc -l /etc/hostname`",
    ),
    (
        "arithmetic-expansion",
        "echo 2",
        "echo $((1 + 1))",
    ),
    (
        "pipe-into-shell-free-filter",
        "grep . /etc/hostname",
        "cat /etc/hostname | grep .",
    ),
    (
        "trailing-comment",
        "cat /etc/hostname",
        "cat /etc/hostname  # read it",
    ),
]

# A screen, not an oracle. Tokens whose presence means a command MIGHT write, used to
# EXCLUDE commands from the conservative lower bound -- never to include one. Anything
# matching stays out of the "plainly read-only" count even if it is in fact read-only,
# which is what makes the resulting number a floor.
#
# SEPARATE patterns, not one alternation with a trailing `\b`. The first draft was
# `(?:...|python3?\s|...)\b`, and a `\b` after a `\s`-terminated branch can never match:
# it demands a word character immediately after the space, so `| python3 -c` (next char
# `-`) scored as "no write token" and every interpreter invocation leaked into the floor.
# That inflated the floor by ~2x. A screen whose misses are silent is worse than none,
# so each class is now its own anchored pattern.
_WORD_HEADS = re.compile(
    r"(?:^|[\s;&|(`])(?:rm|mv|cp|dd|tee|truncate|shred|mkfs|install|chmod|chown|ln|mkdir"
    r"|touch|pip3?|npm|cargo|apt|apt-get|eval|source|exec|gh|curl|wget)\b"
)
# Interpreters: any invocation at all, flags or not. Matched WITHOUT a trailing `\b`.
_INTERPRETERS = re.compile(
    r"(?:^|[\s;&|(`])(?:python3?|sh|bash|zsh|perl|ruby|node|awk|jq)(?:\s|$)"
)
# `pull` and `fetch` were absent from the first draft and were the single largest false
# inclusion in a 40-command hand audit (they mutate refs and the working tree, so they are
# writes). `clone` likewise. Audited into existence, not guessed.
_WRITING_GIT = re.compile(
    r"\bgit\b(?:\s+-C\s+\S+)*\s+(?:add|commit|push|pull|fetch|clone|checkout|switch|restore"
    r"|reset|clean|rebase|merge|apply|am|stash|update-ref|update-index|tag|branch|worktree"
    r"|init|mv|rm|gc|prune|remote\s+(?:add|remove|set-url))\b"
)
# Tool-specific writers the generic head list misses. Same audit; each earned its place by
# appearing as a false inclusion, so this list is EVIDENCE, not anticipation.
_TOOL_WRITERS = re.compile(
    r"(?:^|[\s;&|(`])(?:npx|ollama\s+(?:pull|create|rm)|engram\s+(?:dream|consolidate|store)"
    r"|claude\s+mcp\s+(?:add|remove))\b"
)
# `>` or `>>` to anything that is not a duplication (`>&`). `2>&1` is not a write.
_REDIRECT = re.compile(r">>|>(?!&)")
_INPLACE = re.compile(r"\bsed\b[^|;&]*\s-i\b|\bperl\b[^|;&]*\s-i")

_SCREENS = (_WORD_HEADS, _INTERPRETERS, _WRITING_GIT, _TOOL_WRITERS, _REDIRECT, _INPLACE)


def plainly_read_only(cmd: str) -> bool:
    """Conservative: True only when NO screen fires anywhere in the text."""
    return not any(s.search(cmd) for s in _SCREENS)


def harvest(transcript_dir: Path, limit: int) -> list[str]:
    """Bash commands actually issued by this seat, newest transcripts first."""
    cmds: list[str] = []
    files = sorted(
        transcript_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for path in files:
        if len(cmds) >= limit:
            break
        try:
            with path.open(errors="replace") as fh:
                for line in fh:
                    if '"Bash"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    for block in _content_blocks(rec):
                        if block.get("type") != "tool_use" or block.get("name") != "Bash":
                            continue
                        cmd = (block.get("input") or {}).get("command")
                        if isinstance(cmd, str) and cmd.strip():
                            cmds.append(cmd)
        except OSError:
            continue
    return cmds[:limit]


def _content_blocks(rec: dict):
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    return content if isinstance(content, list) else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hook", type=Path, default=DEFAULT_HOOK)
    ap.add_argument(
        "--transcripts",
        type=Path,
        default=Path.home() / ".claude" / "projects",
        help="directory searched recursively for *.jsonl",
    )
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--show", type=int, default=12, help="sample false refusals to print")
    args = ap.parse_args()

    is_read_only, mod = load_classifier(args.hook)
    print(f"classifier: {args.hook}")
    grammar = getattr(mod, "_READ_ONLY_HEADS", None)
    if grammar is not None:
        print(f"enumerated read-only heads: {len(grammar)}")
    print()

    # --- tier 1
    print("TIER 1 -- minimal pairs (both arms read identical bytes, neither writes)")
    print(f"{'construct':<34} {'in-grammar':>11} {'variant':>9}   verdict")
    splits = 0
    for label, a, b in PAIRS:
        ra = is_read_only("Bash", {"command": a})
        rb = is_read_only("Bash", {"command": b})
        if ra and not rb:
            verdict, splits = "SPLIT -> false refusal", splits + 1
        elif ra == rb:
            verdict = "agree"
        else:
            verdict = "INVERTED (variant allowed, base not)"
        print(f"{label:<34} {str(ra):>11} {str(rb):>9}   {verdict}")
    print(f"\n  {splits}/{len(PAIRS)} constructs split. Each split is a false refusal with")
    print("  certainty: the two arms differ in syntax only, and neither writes.\n")

    # --- tier 2
    cmds = harvest(args.transcripts, args.limit)
    if not cmds:
        print(f"TIER 2 -- no transcripts under {args.transcripts}; skipped")
        return 0

    total = len(cmds)
    called_write = [c for c in cmds if not is_read_only("Bash", {"command": c})]
    floor = [c for c in called_write if plainly_read_only(c)]

    print(f"TIER 2 -- real corpus from {args.transcripts} ({total} Bash commands)")
    print(f"  classified read-only          {total - len(called_write):>6}"
          f"  ({(total - len(called_write)) / total:6.1%})")
    print(f"  classified WRITE              {len(called_write):>6}"
          f"  ({len(called_write) / total:6.1%})")
    print(f"  of those, no write token at all{len(floor):>5}"
          f"  ({len(floor) / total:6.1%} of corpus, {len(floor) / max(len(called_write),1):.1%} of writes)")
    print()
    print("  The last row is a FLOOR on false refusals, not an estimate: the screen")
    print("  excludes anything that merely mentions a write verb, so genuinely")
    print("  read-only commands are discarded from it. It is not a rate of refusal --")
    print("  a refusal also requires a governance marker in the text.")
    print()
    if floor:
        print(f"  sample ({min(args.show, len(floor))} of {len(floor)}):")
        for c in floor[: args.show]:
            flat = " ".join(c.split())
            print(f"    - {flat[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
