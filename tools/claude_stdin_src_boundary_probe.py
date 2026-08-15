#!/usr/bin/env python3
"""The fused-boundary remedy flushes `cur` but not `stdin_src`.

kimi's reply-2568 sweep adopts a 5-line arm: when a fused punct token's charset meets
{';','&','|',')'}, flush the accumulated simple command. The separator arm it is modelled on
(hestia_governance_closure.py:704-709) resets TWO pieces of loop state -- `cur` AND
`stdin_src`. The new arm as specified resets one.

`stdin_src` is the `< file` source threaded into _flush_simple_command and consumed by
`patch` (line 582) and `git apply|am` (line 635) as the patch preimage. With no source those
heads raise _OpaqueWriter -> unconditional fail-close. Inheriting a PREVIOUS simple command's
`< file` across a restored boundary therefore replaces a fail-close with a write set read out
of a file the second command never opened.

Stdlib only: shlex + set logic over literals transcribed from
plugins/_shared/hestia_governance_closure.py:393-394,444-445,489-492,697-736 at HEAD.
No hestia import, no sys.path manipulation, no governance vocabulary in any constructed
command (targets are /tmp placeholders). _flush_simple_command is stubbed to RECORD
(words, stdin_src) -- this probe measures which preimage each simple command is handed, not
the resolved write set.

Run: python3 tools/claude_stdin_src_boundary_probe.py
"""
import shlex

# -- transcribed literals -------------------------------------------------------------
_PUNCT = "();<>|&"
_SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", ";;"})
_BOUNDARY = frozenset({";", "&", "|", ")"})  # kimi's new arm 4 charset


def _is_punct(tok):
    return bool(tok) and all(ch in _PUNCT for ch in tok)


def _tokenize(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT)
    lex.whitespace_split = True
    return list(lex)


def walk(command, arm):
    """Loop 697-736 with a recording stub for _flush_simple_command.
    arm: 'today' | 'remedy5' (flush cur) | 'remedy6' (flush cur + reset stdin_src).
    Returns [(words, stdin_src), ...] in flush order."""
    toks = _tokenize(command)
    flushes, cur = [], []
    stdin_src = None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _SEPARATORS:
            if cur:
                flushes.append((list(cur), stdin_src))
                cur = []
            stdin_src = None
            i += 1
            continue
        if _is_punct(t):
            if ">" in t:
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and "&" in t and nxt.isdigit():
                    i += 2
                    continue
                if nxt is not None and nxt not in _SEPARATORS and not _is_punct(nxt):
                    i += 2
                    continue
                i += 1
                continue
            if t in ("<", "<<", "<<<", "<<-"):
                if t == "<" and i + 1 < len(toks) and not _is_punct(toks[i + 1]):
                    stdin_src = toks[i + 1]
                i += 2
                continue
            if arm in ("remedy5", "remedy6") and (frozenset(t) & _BOUNDARY):
                if cur:
                    flushes.append((list(cur), stdin_src))
                    cur = []
                if arm == "remedy6":
                    stdin_src = None
                i += 1
                continue
            i += 1
            continue
        cur.append(t)
        i += 1
    if cur:
        flushes.append((list(cur), stdin_src))
    return flushes


def preimage_verdict(words, stdin_src):
    """The two heads whose write set lives in `stdin_src` (582, 635). OPAQUE == fail-close."""
    if not words:
        return "-"
    head = words[0].rsplit("/", 1)[-1]
    if head == "patch":
        return "reads " + stdin_src if stdin_src else "OPAQUE(fail-close)"
    if head == "git" and len(words) > 1 and words[1] in ("apply", "am"):
        if any(not a.startswith("-") for a in words[2:]):
            return "reads named file(s)"
        return "reads " + stdin_src if stdin_src else "OPAQUE(fail-close)"
    return "n/a (stdin_src unused by this head)"


CASES = [
    # fused `);` boundary, second head consumes stdin
    "(patch -p1 < /tmp/benign.patch); git apply",
    "(cat < /tmp/benign.patch); git apply",
    "(cat < /tmp/benign.patch); patch -p1",
    # control: the SAME shape with an unfused separator -- 704-709 resets stdin_src today
    "( cat < /tmp/benign.patch ) ; git apply",
    # control: no prior redirect -- every arm must fail closed
    "(cat /tmp/benign.patch); git apply",
]


def main():
    print("alphabet check: _PUNCT has", len(_PUNCT), "chars ->",
          sum(len(_PUNCT) ** n for n in (1, 2, 3)), "fused tokens of length 1-3")
    print()
    for cmd in CASES:
        print("command:", cmd)
        print("  tokens:", _tokenize(cmd))
        for arm in ("today", "remedy5", "remedy6"):
            rows = walk(cmd, arm)
            rendered = ["%s [stdin=%s] -> %s" % (" ".join(w), s, preimage_verdict(w, s))
                        for w, s in rows]
            print("  %-8s %s" % (arm + ":", " || ".join(rendered)))
        print()

    print("-- independent closed-form census of the sweep (no enumeration needed) --")
    n = len(_PUNCT)
    total = sum(n ** k for k in (1, 2, 3))
    seps = sum(1 for s in _SEPARATORS if _is_punct(s) and len(s) <= 3)
    gt = sum(n ** k - (n - 1) ** k for k in (1, 2, 3))  # contains '>'
    lt = 3                                              # '<','<<','<<<' ('<<-' is not punct)
    rest = total - seps - gt - lt
    skip = sum(1 for k in (1, 2, 3)
               for t in __import__("itertools").product("(<", repeat=k)
               if "".join(t) not in _SEPARATORS and "".join(t) not in ("<", "<<", "<<<"))
    print("total=%d sep=%d redirect(>)=%d redirect(<)=%d survivors=%d flush=%d skip=%d"
          % (total, seps, gt, lt, rest, rest - skip, skip))
    print("redirect-free by construction:", gt == sum(1 for k in (1, 2, 3)
          for t in __import__("itertools").product(_PUNCT, repeat=k)
          if ">" in "".join(t) and "".join(t) not in _SEPARATORS) + 0)


if __name__ == "__main__":
    main()
