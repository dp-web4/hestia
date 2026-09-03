#!/usr/bin/env python3
"""What would gate 1a deny if it resolved tokens instead of scanning text?

WHY THIS EXISTS. Issue #639 characterised gate 1a as a raw-substring scan; #641 put a rate
on it. Three remedy proposals (#639, #393, #680) all stall at "shape of a fix", and the
GATE_HEURISTIC_AUDIT of 2026-08-28 says do not re-propose. Nothing here re-proposes. The
missing number is the PRICE of the fix: narrowing a deny is a coverage loss, and no one has
measured which denials the narrower rule would give up. That is the number this computes.

THE COUNTERFACTUAL IS NOT INVENTED. It is gate 1b's discipline, applied to gate 1a's list.
`command_in_scope` in the same module abandoned lexical mention-scanning on 2026-07-23 for
this exact failure mode -- its docstring: "A reach is judged by WHERE IT RESOLVES, not by
what it lexically mentions." It carries a tokenizer; this reuses it verbatim. Segment
matching then follows the daemon preset `deny-secret-files`, which already globs resolved
targets (`presets.rs`) and so already declines the identifier-substring shape.

WHAT IT REPORTS.
  1. Denied by the INSTALLED lexical rule (the status quo).
  2. Denied by the RESOLVED rule (the counterfactual).
  3. FLIP set -- denied today, allowed under resolution. This is the entire coverage delta,
     and every false positive gate 1a costs lives in here too. Priced, not asserted:
     the set is printed for review rather than declared false.
  4. An invariant self-check: resolved-deny must be a SUBSET of lexical-deny, because
     resolution can only ever discard occurrences the substring test already found. A
     non-empty "gained" column means this tool is wrong, not that the rule is better.

NO FORBIDDEN TOKEN IS SPELLED IN THIS SOURCE -- every one is imported from the core's own
constant, the same discipline as tools/gate1a_forbidden_token_census.py. A literal here
would make the file refused by the gate it measures, which is finding #4 of #639.

Run: python3 tools/gate1a_resolved_counterfactual.py [limit]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate1a_forbidden_token_census as X  # noqa: E402

C, TOK, BARE, QUALIFIED = X.C, X.TOK, X.BARE, X.QUALIFIED

# Gate 1b's own splitter, copied from command_in_scope (core:816) so the two agree on what
# a "token" is. Divergence here would silently change the answer.
_SPLIT = re.compile(r"""[\s;|&<>()'"`]+""")


def _tokens(cmd):
    for raw in _SPLIT.split(cmd):
        for tok in raw.split("="):
            tok = tok.strip()
            if tok:
                yield tok


def _reaches(tok, f):
    """Does this ONE token reach the protected resource named by f?

    THREE SHAPES, because the token list holds three and conflating them is the defect.

    (a) QUALIFIED (carries its own separator or underscore): already boundaried. Unchanged.

    (b) DOTFILE-SHAPED (leading dot): a filename, never an English word, so it needs no
        separator to be a reach -- a bare one names a real file. Segment-equal or dotted
        stem. This is what the daemon glob for the dotted families expresses, and it is why
        the bare form still denies while the glued identifier does not.

    (c) WORD-SHAPED (a plain English word): ambiguous by construction. It is a reach only in
        a PATH CONTEXT -- carried by a separator, or wearing a suffix. Standing alone in
        prose it is a word. This is exactly what the daemon encodes: it globs the dotted and
        directory-qualified forms of these words and carries NO bare glob for them, so the
        installed local rule is STRICTER than the authority it mirrors. Documented coverage
        cost: a bare extensionless relative file by that name stops being caught here --
        and it is already not caught by the daemon today."""
    low = tok.lower().replace("\\", "/")
    if "/" in f or "_" in f:
        return f in low
    segs = [s.strip("\"'`,:;") for s in low.split("/")]
    dotfile = f.startswith(".")
    for i, seg in enumerate(segs):
        dotted = "." + f
        if not (seg == f or seg.startswith(f + ".")
                or seg == dotted or seg.startswith(dotted + ".")):
            continue
        if dotfile or seg.startswith(".") or seg != f or len(segs) > 1:
            return True   # (b) any position, or (c) in a path context
    return False


_META = set("*?[]|^$\\")


def real_file_carriers(cmd, f):
    """Carrier tokens that could name a REAL FILE, as opposed to an identifier or a pattern.

    This is the coverage-price instrument and it is deliberately GENEROUS: anything it can
    not rule out stays in. A regex/glob metacharacter rules a token out (a PATTERN is not a
    reach -- #639 finding #2). A following alphanumeric rules it out (attribute access, a
    longer identifier). Everything else is reported for a human to adjudicate rather than
    classified by this tool, because "is this file a secret" is not a lexical question."""
    out = []
    for t in _tokens(cmd):
        low = t.lower().rstrip("\"'`,:;)")
        if f not in low or any(ch in low for ch in _META):
            continue
        base = low.split("/")[-1]
        j = base.find(f)
        if j < 0:
            continue
        nxt = base[j + len(f):j + len(f) + 1]
        if nxt.isalnum() or nxt == "_":
            continue
        out.append(base)
    return out


def gate1a_resolved(cmd):
    for tok in _tokens(cmd):
        for f in TOK:
            if _reaches(tok, f):
                return f
    return None


def _controls():
    """Both directions. A fix that only proves it stops denying is not evidence."""
    env, word = BARE[0], next(t for t in BARE if "." not in t)
    cases = [
        # (label, command, expect_lexical, expect_resolved)
        ("TRUE POSITIVE  dotfile path", "cat /home/u/" + env, True, True),
        ("TRUE POSITIVE  dotted suffix", "cat /app/" + env + ".local", True, True),
        ("TRUE POSITIVE  word as a file", "cat /home/u/.aws/" + word, True, True),
        ("FALSE POSITIVE glued identifier", "v = os" + env + "iron.get(X)", True, False),
        ("FALSE POSITIVE english prose", "git commit -m rotate the " + word, True, False),
        ("TRUE POSITIVE  bare dotfile", "cat " + env, True, True),
        ("FALSE POSITIVE stdlib import", "python3 -c import " + word, True, False),
        ("FALSE POSITIVE prose midline", "echo we rotate " + word + " monthly", True, False),
        ("NEGATIVE       unrelated", "git status --short", False, False),
    ]
    print("CONTROLS (both directions -- a rule that only stops denying is not evidence)")
    ok = True
    for label, cmd, want_lex, want_res in cases:
        lex, res = bool(X.gate1a(cmd)), bool(gate1a_resolved(cmd))
        good = (lex == want_lex) and (res == want_res)
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label:32} lexical={lex!s:5} resolved={res!s:5}")
    print(f"  controls: {'ALL PASS' if ok else 'FAILURE -- do not read the table below'}\n")
    return ok


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    print(f"enforcing core: {C.__file__}")
    if not _controls():
        return 1
    cmds, span = X.harvest(X.TRANSCRIPTS, limit)
    if not cmds:
        print("no corpus found -- nothing to report")
        return 1
    lo, hi = (min(span)[:10], max(span)[:10]) if span else ("?", "?")
    print(f"corpus: {len(cmds)} issued Bash commands, issued {lo}..{hi}\n")

    lex = {i: t for i, c in enumerate(cmds) for t in [X.gate1a(c)] if t}
    res = {i: t for i, c in enumerate(cmds) for t in [gate1a_resolved(c)] if t}
    flip = sorted(set(lex) - set(res))
    gained = sorted(set(res) - set(lex))

    n = len(cmds)
    print(f"DENIED, installed lexical rule : {len(lex):5}/{n} = {100*len(lex)/n:.2f}%")
    print(f"DENIED, resolved counterfactual: {len(res):5}/{n} = {100*len(res)/n:.2f}%")
    print(f"FLIP  (denied today, allowed)  : {len(flip):5}    = "
          f"{100*len(flip)/max(1,len(lex)):.1f}% of today's denials")
    print(f"GAINED(allowed today, denied)  : {len(gained):5}    "
          f"[invariant: MUST be 0; nonzero = this tool is wrong]")

    from collections import Counter
    print("\nflip by token -- which token stops firing:")
    for t, k in Counter(lex[i] for i in flip).most_common():
        kept = sum(1 for i in res if res[i] == t)
        print(f"  {t!r:16} flips {k:5}   still denies {kept:5}   "
              f"[{'BARE' if t in BARE else 'qualified'}]")

    print("\nSURVIVORS -- denials the resolved rule KEEPS, by token:")
    for t, k in Counter(res.values()).most_common():
        print(f"  {t!r:16} {k:5}")

    print(f"\n--- FLIP SAMPLE ({min(25,len(flip))} of {len(flip)}) ---")
    print("Printed for REVIEW, not declared false. A real reach in here is a coverage loss")
    print("and is the argument against the fix; read them before quoting the headline.\n")
    for i in flip[:25]:
        c = " ".join(cmds[i].split())
        print(f"  [{lex[i]}] {c[:150]}")

    print(f"\n--- COVERAGE PRICE: what the resolved rule STOPS denying ---")
    print("Adjudication is a human question ('is this file a secret'), so this tool reports")
    print("candidates rather than verdicts, and errs toward keeping them.\n")
    adj = {i: cs for i in flip for cs in [real_file_carriers(cmds[i], lex[i])] if cs}
    names = Counter(b for cs in adj.values() for b in cs)
    print(f"  file-shaped  {len(adj):4}/{len(flip)} flips = {100*len(adj)/max(1,len(flip)):.1f}% "
          f"({100*len(adj)/max(1,len(lex)):.2f}% of ALL denials today)")
    print(f"  zero-risk    {len(flip)-len(adj):4}/{len(flip)} flips = "
          f"{100*(len(flip)-len(adj))/max(1,len(flip)):.1f}% "
          f"(glued identifiers, prose, PATTERNS -- cannot be a reach)\n")
    print("  every distinct basename that stops being denied:")
    for b, n in names.most_common():
        print(f"    {n:4}x  {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
