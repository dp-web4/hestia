#!/usr/bin/env python3
"""How much real traffic does gate 1a refuse, and how much of that can it possibly be right about?

WHY THIS EXISTS. Issue #639 characterises gate 1a's raw-substring egress test from four
false denies in a single wake. That is a shape, not a rate. This puts a number on it by
projecting the CURRENTLY INSTALLED predicate onto commands this seat actually issued --
the same method PR #619 used for the read-only classifier, so the two are comparable.

WHAT IT MEASURES.
  1. Exposure -- the share of issued Bash commands whose text contains a forbidden token.
  2. Attribution -- how much of that exposure comes from the three BARE tokens rather
     than the four path-qualified ones.
  3. A false-positive FLOOR -- commands where EVERY occurrence of the matched token is
     glued inside a longer identifier, so no occurrence can be the protected path.

WHY A FLOOR AND NOT A RATE. A non-glued match can still be a false positive: a grep
PATTERN, a commit message, a quoted heredoc body. Gate 1a has no quoted-as-data carve-out,
though the operating law publishes one for the destructive preset. Counting those needs a
shell parse; counting glued ones needs no judgement at all. So the floor is the honest,
judgement-free number and the true rate is higher.

WHAT IT IS NOT. This is COUNTERFACTUAL for any command older than the installed core.
Presence in a transcript means the command was ISSUED, not that it was allowed; and gate
1a is only reached when the shim takes the snapshot or fail-closed path. So read the
headline as exposure under the rule as it stands today, not as denials that happened.
The positive control below is what ties it to the present: it is the shape of a deny this
seat took live while writing this tool.

NO FORBIDDEN TOKEN IS SPELLED IN THIS SOURCE. Every one is imported from the core's own
constant, the same discipline as tools/marker_bar_probe.py -- a literal here would make
the file refused by the gate it measures, which is finding #4 of #639.

Run: python3 tools/gate1a_forbidden_token_census.py [limit]
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

# The ENFORCING copy, resolved the way the shim resolves it: canonical first, legacy only
# if canonical is unpopulated (pre_tool_use.py:301-307, one-directional by design).
_HOME = os.path.expanduser("~")
_CANON = os.path.join(_HOME, ".hestia", "shared")
_LEGACY = os.path.join(_HOME, ".claude", "_shared")
SHARED = _CANON if os.path.isdir(_CANON) else _LEGACY
sys.path.insert(0, SHARED)
import hestia_gate_core as C  # noqa: E402

TOK = C.FORBIDDEN_DEFAULT
QUALIFIED = tuple(t for t in TOK if "/" in t or "_" in t)
BARE = tuple(t for t in TOK if t not in QUALIFIED)
WORDS = tuple(t for t in BARE if "." not in t)   # the pure english words

TRANSCRIPTS = os.path.join(_HOME, ".claude", "projects")


def gate1a(cmd):
    """Replication of core evaluate() gate 1a over the command blob.

    Faithful because 1a is six lines, runs FIRST and dominates every later gate:
        for f in forbidden:
            if f in blob.lower(): return _deny("egress.secret", ...)
    """
    low = cmd.lower()
    for f in TOK:
        if f in low:
            return f
    return None


def _blocks(rec):
    msg = rec.get("message") or {}
    c = msg.get("content")
    return c if isinstance(c, list) else []


def harvest(root, limit):
    """Bash commands this seat issued, newest transcripts first."""
    cmds = []
    files = sorted(Path(root).rglob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    span = []
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
                    for b in _blocks(rec):
                        if b.get("type") != "tool_use" or b.get("name") != "Bash":
                            continue
                        cmd = (b.get("input") or {}).get("command")
                        if isinstance(cmd, str) and cmd.strip():
                            cmds.append(cmd)
                            # RECORD time, not file mtime: a transcript written today
                            # can carry commands issued months ago, and the whole
                            # counterfactual caveat turns on which one you report.
                            stamp = rec.get("timestamp")
                            if stamp:
                                span.append(stamp)
        except OSError:
            continue
    return cmds[:limit], span[:limit]


def _positions(low, tok):
    out, i = [], low.find(tok)
    while i != -1:
        out.append(i)
        i = low.find(tok, i + 1)
    return out


def _glued(low, tok, i):
    b = low[i - 1] if i > 0 else " "
    a = low[i + len(tok)] if i + len(tok) < len(low) else " "
    return (b.isalnum() or b == "_") or (a.isalnum() or a == "_")


def every_occurrence_glued(cmd, tok):
    """False positive by construction: no occurrence can be the protected path."""
    low = cmd.lower()
    pos = _positions(low, tok)
    return bool(pos) and all(_glued(low, tok, i) for i in pos)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    print(f"enforcing core: {C.__file__}")
    cmds, span = harvest(TRANSCRIPTS, limit)
    if not cmds:
        print("no corpus found -- nothing to report")
        return 1
    lo, hi = (min(span)[:10], max(span)[:10]) if span else ("?", "?")
    print(f"corpus: {len(cmds)} issued Bash commands, issued {lo}..{hi}")
    print(f"tokens: {len(TOK)} total | bare={len(BARE)} qualified={len(QUALIFIED)}")

    # POSITIVE CONTROL -- the shape of a deny taken live while writing this tool:
    # the standard library's process-environment mapping contains a bare token.
    ctrl = "shared = os" + BARE[0] + "iron.get('X')"
    ok = gate1a(ctrl)
    print(f"positive control (live deny shape): matched={ok!r} -> {'PASS' if ok else 'FAIL'}")
    neg = "git status --short && ls -la /tmp"
    print(f"negative control:                   matched={gate1a(neg)!r} -> "
          f"{'PASS' if not gate1a(neg) else 'FAIL'}")
    print()

    hits = [(c, t) for c in cmds for t in [gate1a(c)] if t]
    print(f"EXPOSURE: {len(hits)}/{len(cmds)} = {100*len(hits)/len(cmds):.2f}% "
          f"of issued commands contain a forbidden token")

    by_tok = Counter(t for _, t in hits)
    print("\nper-token:")
    for t, n in by_tok.most_common():
        print(f"  {t!r:20} {n:5}  [{'BARE' if t in BARE else 'qualified'}]")

    bare_hits = [h for h in hits if h[1] in BARE]
    print(f"\nATTRIBUTION: {len(bare_hits)}/{len(hits)} = "
          f"{100*len(bare_hits)/max(1,len(hits)):.1f}% of exposure is a BARE token")

    strict = [h for h in hits if every_occurrence_glued(*h)]
    print(f"FP FLOOR:    {len(strict)}/{len(hits)} = "
          f"{100*len(strict)/max(1,len(hits)):.1f}% have EVERY occurrence glued inside a "
          f"longer identifier")
    print("             (a floor, not the rate -- grep patterns, commit messages and")
    print("              quoted heredoc bodies are also false and are NOT counted here)")

    print(f"\n--- the {len(WORDS)} pure english words among the tokens ---")
    for w in WORDS:
        sub = [c for c in cmds if w in c.lower()]
        print(f"[{w!r}] appears in {len(sub)} commands, all exposed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
