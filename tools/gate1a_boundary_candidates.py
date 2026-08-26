#!/usr/bin/env python3
"""The two-seat remedy for gate 1a says "give the bare tokens a boundary". Which side?

WHY THIS EXISTS. #639 measured gate 1a's exposure on this seat's real traffic; kimi-code
replicated the census on a second seat and a second corpus (notice 6043). Both seats agree
on the structure -- exposure is almost entirely the three BARE tokens, the four
path-qualified ones contribute nearly nothing, and a large share of the bare hits have every
occurrence glued inside a longer identifier -- and both seats then agreed the remedy is to
give the bare tokens a boundary. Neither seat said WHICH BOUNDARY, and the agreement was
recorded as if that were a detail.

It is not a detail. The obvious reading -- a symmetric word boundary, the `\\b` that PR #546
added to the destructive verb -- is a HOLE, and this file is how that was found. Under a
symmetric boundary the gate stops matching every real secret spelling that is glued on the
LEFT, and left-gluing is normal for these names:

    router-shadow.T2      dev-T3.json      aws_T3      my_T7.tfvars

All four are real reaches for a real secret. A symmetric boundary releases them. The corpus
contains live examples: candidate C below releases six commands that read an API key out of
a `dev-T3.json` file, and candidate A releases an `aws_T3` spelling.

What real secret spellings DO have is a right edge. `T2` and the two words end at `/`, `.`,
a quote, or the end of the word; the false ones continue into another word -- the standard
library's process-environment mapping being 40 of the 41 false hits on this corpus. So the
boundary that fixes gate 1a is ASYMMETRIC: right side only.

WHAT IT MEASURES. Five candidate definitions projected onto the same corpus the #639 census
used, each scored three ways:

  * a KEEP fixture   -- real secret spellings, composed from the core's own tuple, that any
                        candidate which is not a hole must still deny
  * a RELEASE fixture-- the false shapes a boundary is supposed to free
  * the corpus       -- what it actually keeps and releases on traffic this seat issued,
                        with every released command PRINTED, because a count cannot tell a
                        fix from a hole and #546's review is explicit that an FP-only suite
                        is a one-way gradient

RESULT ON THIS SEAT (2026-08-26, 12,000 issued commands, span 2026-03-14..2026-08-26):
  exposure 378/12,000 = 3.15% under the rule as it stands, KEEP fixture 12 entries

  A  symmetric, glue = alnum or _      KEEP  8/12  <-- HOLE (aws_T3, my_T7.tfvars, repo+T6)
  B  symmetric, glue = alnum           KEEP 10/12  <-- HOLE (router-shadow.T2, repo+T6)
  C  symmetric, glue = alnum, _ or -   KEEP  7/12  <-- HOLE (+ dev-T3.json, live x6)
  D  right only, glue = alnum or _     KEEP 12/12  releases 39/378 = 10.3%
  E  right only, glue = alnum          KEEP 12/12  releases 39/378 = 10.3%

  E dominates D: identical release set, strictly more kept -- `T2_backup` stays denied
  under E and is released by D, and no corpus command distinguishes them.
  Every one of the 39 releases continues into the standard library's process-environment
  mapping. Not one is a path. Applying the same rule to the four path-qualified tokens
  rather than the three bare ones changes NOTHING on this corpus (measured: difference 0),
  so the fix is one predicate for all seven, not a classification the core does not make.

  The symmetric candidates also open a QUALIFIED token: `repo` + T6 is left-glued by the
  `o` of the repository name, so A, B and C stop matching an ordinary git config path.
  That was not predicted; it is what the KEEP arm is for.

NO FORBIDDEN TOKEN IS SPELLED IN THIS SOURCE, and none is spelled above -- `T2`/`T3`/`T7`
are #639's numbering. Every token and every fixture is composed from the core's own constant
at runtime. A literal here would make the file refused by the gate it measures, which is
finding #4 of #639.

Run: python3 tools/gate1a_boundary_candidates.py [limit]
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

# The ENFORCING copy, resolved the way the shim resolves it: canonical first, legacy only if
# canonical is unpopulated. Same resolution as tools/gate1a_forbidden_token_census.py, so the
# two tools are comparable.
_HOME = os.path.expanduser("~")
_CANON = os.path.join(_HOME, ".hestia", "shared")
_LEGACY = os.path.join(_HOME, ".claude", "_shared")
SHARED = _CANON if os.path.isdir(_CANON) else _LEGACY
sys.path.insert(0, SHARED)
import hestia_gate_core as C  # noqa: E402

TOK = C.FORBIDDEN_DEFAULT
QUALIFIED = tuple(t for t in TOK if "/" in t or "_" in t)
BARE = tuple(t for t in TOK if t not in QUALIFIED)
DOTTED = [t for t in BARE if t.startswith(".")]      # the file-suffix one
WORDS = [t for t in BARE if not t.startswith(".")]   # the two english words

TRANSCRIPTS = os.path.join(_HOME, ".claude", "projects")

_A = lambda ch: ch.isalnum() or ch == "_"            # noqa: E731
_B = lambda ch: ch.isalnum()                         # noqa: E731
_C = lambda ch: ch.isalnum() or ch in "_-"           # noqa: E731

# (description, left-glue predicate or None, right-glue predicate or None). `None` means
# that side is not examined at all -- which is the whole point of D and E.
CANDIDATES = {
    "A": ("symmetric,  glue = alnum or _", _A, _A),
    "B": ("symmetric,  glue = alnum", _B, _B),
    "C": ("symmetric,  glue = alnum or _ or -", _C, _C),
    "D": ("RIGHT only, glue = alnum or _", None, _A),
    "E": ("RIGHT only, glue = alnum", None, _B),
}
RECOMMENDED = "E"


def _positions(low, tok):
    out, i = [], low.find(tok)
    while i != -1:
        out.append(i)
        i = low.find(tok, i + 1)
    return out


def redact(s):
    """Rewrite every token occurrence as #639's `<Tn>`.

    Not cosmetic. This tool's own OUTPUT is text a member then wants to paste into an issue,
    a commit message or a peer notice -- and gate 1a scans command text, so an unredacted
    report is a report that cannot be filed. #639 hit exactly this: the `gh issue create`
    that filed the finding was itself denied. A measuring tool whose output is unquotable
    has only moved the refusal one step downstream."""
    out = s
    for i, t in enumerate(TOK, 1):
        out = out.replace(t, f"<T{i}>")
    return out


def matches_current(cmd):
    """Gate 1a as it stands: raw substring, no boundary at all (core:936-940)."""
    low = cmd.lower()
    for f in TOK:
        if f in low:
            return f
    return None


def matches_bounded(cmd, left_glue, right_glue, bare_only=False):
    """Gate 1a with a boundary. Same loop, same order, one added predicate per occurrence.

    `bare_only` models the narrower fix: the boundary applies to the three bare tokens and
    the four path-qualified ones keep raw-substring semantics."""
    low = cmd.lower()
    for f in TOK:
        if f not in low:
            continue
        if bare_only and f in QUALIFIED:
            return f
        for i in _positions(low, f):
            before = low[i - 1] if i > 0 else " "
            after = low[i + len(f)] if i + len(f) < len(low) else " "
            if left_glue is not None and left_glue(before):
                continue
            if right_glue is not None and right_glue(after):
                continue
            return f
    return None


def keep_fixture():
    """Real spellings a secret reach takes -- the arm that decides the question.

    Four of the nine are glued on the LEFT. That is not a contrivance: it is how these files
    are actually named, and it is why the symmetric candidates fail. Composed from the core's
    own tuple so this file never spells a token."""
    d = DOTTED[0] if DOTTED else ".x"
    w = WORDS[0] if WORDS else "x"
    w2 = WORDS[1] if len(WORDS) > 1 else w
    q = list(QUALIFIED)
    return [
        f"cat /home/dp/{d}",                    # bare, at a path boundary
        f"cat /home/dp/{d}.local",              # suffixed
        f"cat ./{d}",                           # relative
        f"cat /srv/app/router-shadow{d}",       # LEFT-glued and real
        f"cat /tmp/x/dev-{w}.json",             # LEFT-glued by a dash and real
        f"cat /tmp/x/aws_{w}",                  # LEFT-glued by an underscore and real
        f"cat ~/.aws/{w}",                      # the canonical one
        f"cat config/{w2}.yml",                 # the other word, real
        f"cat vault/my_{w2}.tfvars",            # underscore-glued and real
    ] + [f"cat ~{q[0]}/{q[1]}", f"cat ~{q[0]}/{q[1]}.pub", f"cat /home/dp/repo{q[3]}"]


def release_fixture():
    """What the boundary is SUPPOSED to free: the token continues into another word, so no
    occurrence can be the protected path."""
    d = DOTTED[0] if DOTTED else ".x"
    w = WORDS[0] if WORDS else "x"
    w2 = WORDS[1] if len(WORDS) > 1 else w
    return [
        f"python3 -c \"import os; print(os{d}iron)\"",   # 40 of this corpus's 41 false hits
        f"ls {d}ironments_dir",
        f"echo {w}tore",
        f"echo {w2}auce",
    ]


def _blocks(rec):
    msg = rec.get("message") or {}
    c = msg.get("content")
    return c if isinstance(c, list) else []


def harvest(root, limit):
    """Bash commands this seat issued, newest transcripts first.

    Presence means the command was ISSUED, not that it was allowed -- the same
    counterfactual caveat the #639 census carries, and the reason the KEEP arm is read
    rather than counted."""
    cmds, span = [], []
    files = sorted(Path(root).rglob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
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
                            stamp = rec.get("timestamp")
                            if stamp:
                                span.append(stamp)
        except OSError:
            continue
    return cmds[:limit], span[:limit]


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
    print(f"enforcing core: {C.__file__}")
    cmds, span = harvest(TRANSCRIPTS, limit)
    if not cmds:
        print("no corpus found -- nothing to report")
        return 1
    lo, hi = (min(span)[:10], max(span)[:10]) if span else ("?", "?")
    print(f"corpus: {len(cmds)} issued Bash commands, issued {lo}..{hi}")
    print(f"tokens: bare={len(BARE)} qualified={len(QUALIFIED)}")

    keep, rel = keep_fixture(), release_fixture()
    # CONTROLS. Both fixtures must be fully matched by the rule AS IT STANDS, or the arms
    # below are measuring something other than the rule. The release fixture being matched
    # today is not a control passing -- it IS the defect.
    miss = [k for k in keep if not matches_current(k)]
    print(f"control -- KEEP fixture    ({len(keep):2}) all matched by the rule as it stands: "
          f"{'PASS' if not miss else 'FAIL ' + repr([redact(m) for m in miss])}")
    miss = [r for r in rel if not matches_current(r)]
    print(f"control -- RELEASE fixture ({len(rel):2}) all matched by the rule as it stands: "
          f"{'PASS' if not miss else 'FAIL ' + repr([redact(m) for m in miss])}   <- this is the defect")
    neg = "git status --short && ls -la /tmp"
    print(f"control -- negative        : {matches_current(neg)!r} -> "
          f"{'PASS' if not matches_current(neg) else 'FAIL'}")
    print()

    exposed = [c for c in cmds if matches_current(c)]
    print(f"EXPOSURE under the rule as it stands: {len(exposed)}/{len(cmds)} = "
          f"{100*len(exposed)/len(cmds):.2f}%")
    print()

    released_by, holes = {}, []
    for key, (desc, lg, rg) in CANDIDATES.items():
        kept = [c for c in exposed if matches_bounded(c, lg, rg)]
        released = [c for c in exposed if not matches_bounded(c, lg, rg)]
        released_by[key] = released
        opened = [k for k in keep if not matches_bounded(k, lg, rg)]
        freed = [r for r in rel if not matches_bounded(r, lg, rg)]
        if opened:
            holes.append(key)
        print(f"CANDIDATE {key}  {desc}")
        print(f"   KEEP fixture held      {len(keep)-len(opened):2}/{len(keep)}"
              f"{'' if not opened else '   <-- HOLE'}")
        for k in opened:
            print(f"      OPENS a real secret spelling: {redact(k)!r}")
        print(f"   RELEASE fixture freed  {len(freed):2}/{len(rel)}")
        print(f"   corpus keeps       {len(kept):5}/{len(exposed)}")
        print(f"   corpus RELEASES    {len(released):5}/{len(exposed)} = "
              f"{100*len(released)/max(1,len(exposed)):.1f}%")
        for t, n in Counter(matches_current(c) for c in released).most_common():
            print(f"      by token index {TOK.index(t)}: {n}")
        print()

    print(f"holes (opened a real spelling in the KEEP fixture): {holes or 'none'}")
    print(f"recommended: {RECOMMENDED} -- {CANDIDATES[RECOMMENDED][0]}")

    # Does restricting the boundary to the BARE tokens change anything? If not, the fix is
    # one predicate for all seven rather than a classification the core does not currently
    # make -- and a rule with no exceptions is the one that survives the next token added
    # via the extra-token env var.
    _, lg, rg = CANDIDATES[RECOMMENDED]
    narrow = {c for c in exposed if not matches_bounded(c, lg, rg, bare_only=True)}
    uniform = {c for c in exposed if not matches_bounded(c, lg, rg)}
    print(f"bare-only vs uniform under {RECOMMENDED}: "
          f"{len(narrow)} vs {len(uniform)} released, "
          f"difference {len(uniform ^ narrow)}")
    print()

    print("=" * 78)
    print(f"KEEP ARM on real traffic -- every command candidate {RECOMMENDED} would release.")
    print("A count cannot tell a fix from a hole. These have to be read.")
    print("=" * 78)
    cont = Counter()
    for i, c in enumerate(sorted(set(released_by[RECOMMENDED])), 1):
        low, tok = c.lower(), matches_current(c)
        tails = sorted({redact(low[p:p + len(tok) + 10]) for p in _positions(low, tok)})
        for t in tails:
            cont[t[:len(f'<T{TOK.index(tok)+1}>') + 4]] += 1
        print(f"[{i:03d}] continues into: {tails[:3]}")
    print()
    print("continuation histogram -- what the token ran into. A path would show `/` or a")
    print("quote here; every entry below is another word, which is the whole claim:")
    for t, n in cont.most_common():
        print(f"  {n:4}  {t!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
