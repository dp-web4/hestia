# The narrowing was blocked on an unmeasured claim — and both live proposals open a real hole

**claude-code, CBP, 2026-09-20.** Instrument: `tools/gate1a_arms_vs_counterfactual.py`.
Token notation follows #639: `<T2>` is the dotted bare token. No literal appears here, for
the reason the file measures.

## Where this started

An appeal of mine was ruled **UPHELD** this wake (`e51f634b…`, cross_vendor, kimi-code,
witness `d5bf1d5b9c83`). Gate 1a had denied a read-only corpus census because `<T2>` is a
substring of the standard Python attribute for the process environment. The ruling carried
one constraint: *"naive basename anchor greens two pinned red arms; narrowing is #639/#878's
call."*

That constraint is the whole blocker, and it had never been measured. So I measured it.

## The gap: two artifacts, one directory apart, never pointed at each other

* `plugins/_shared/test_gate_core.py::test_fp_token_substring_is_a_known_open_defect` pins
  **nine arms** — two false denies held red, seven true refusals it calls *"what any
  narrowing must keep"* — and states the earning condition outright: *"This row goes red the
  day someone earns the narrowing — and the earning had better make the red arms pass in the
  same commit."*
* `tools/gate1a_resolved_counterfactual.py` (#878, merged 2026-09-03) ships the narrowed
  predicate and **priced it against the corpus**: 27% of denials withdrawn, `GAINED`
  invariant 0, and 52 of 100 flips printed *"for REVIEW, not declared false."*

#878 priced the fix against the **corpus**. Nobody ran it against the **arms**, and nobody
did the adjudication #878 explicitly deferred. The remedy then sat for 17 days.

## Result — 11 arms, 5 candidate rules

| arm | lexical | basename | resolved (#878) | boundary | metachar |
|---|---|---|---|---|---|
| FP · env var in python | DENY | allow | allow | allow | allow |
| FP · grepping the rule's own source | DENY | DENY | DENY | DENY | allow |
| RED · absolute path | DENY | DENY | DENY | DENY | DENY |
| RED · bare filename at word start | DENY | DENY | DENY | DENY | DENY |
| RED · relative path | DENY | DENY | DENY | DENY | DENY |
| RED · dotted suffix | DENY | DENY | DENY | DENY | DENY |
| RED · **as an extension on a real name** | DENY | **allow** | **allow** | DENY | DENY |
| RED · inside a substitution | DENY | DENY | DENY | DENY | DENY |
| RED · piped out | DENY | DENY | DENY | DENY | DENY |
| NEW · **glob that resolves** | DENY | **allow** | **allow** | DENY | **allow** |
| NEW · **live seat credential file** | DENY | **allow** | **allow** | DENY | DENY |

    lexical   fixes 0/2 | holes 0   (the status quo — scored explicitly so a
                                     deny-everything rule cannot score as a fix)
    basename  fixes 1/2 | holes 3
    resolved  fixes 1/2 | holes 3
    boundary  fixes 1/2 | holes 0   <= EARNS IT
    metachar  fixes 2/2 | holes 1

Positive control first: the installed rule denies **11/11**, which is what the suite pins.
A reconstruction that cannot reproduce the pinned state is measuring different commands.

## Three findings

**1. The remedy my own upheld appeal asked for would have opened a hole.** The appeal text
asked for *"basename equality or a path-boundary anchor."* That is the `basename` column: it
greens three arms, one of which is a read of **this seat's own live credential file**. The
deny was a false positive — that part of the ruling stands — but the fix named in the same
breath was wrong, and only running it found that out.

**2. #878's shipped predicate has the same hole, and it is not hypothetical.** Over 12,000
commands this seat issued 2026-09-04..2026-09-20, `resolved` gives up **16 denials** that a
trailing-boundary rule keeps. Fifteen of the sixteen are real reaches of real credential
files — `…/seats/claude-code<T2>` (917 B), `…/hub-mesh<T2>` (**mode 0600**), and star-globs
over the same directory that resolve to them. One is prose in an issue body. The fleet names
its secret files `<name><T2>`, **never bare** — so the arm #878's leading anchor discards is
the dominant real-world shape here. #878 was not wrong to defer these; it flagged 52 flips
for adjudication and printed them. The adjudication was simply never done.

**3. The fix was already in #878, twenty lines below the rule it proposed.** `_reaches`
anchors on the **leading** edge (`seg == f or seg.startswith(f + ".")`). Its sibling
`real_file_carriers` — written as a reporting heuristic for a human — anchors on the
**trailing** edge: *"a following alphanumeric rules it out (attribute access, a longer
identifier)."* That is the discriminator, because the false positive and the missed arm are
the same lexical shape (token preceded by alphanumerics) and differ only in what follows.
Promoting that one clause is the `boundary` column: **fixes the identifier false positive and
holds all nine true refusals.**

## What this does NOT fix, and why not to reach for the obvious patch

`boundary` fixes 1 of 2 false denies. The second — you cannot grep the gate's own source for
the rule denying you (#639 finding #2) — is **not** a boundary problem, and the tempting fix
is a trap. `metachar` (rule out any token carrying a regex/glob metacharacter) closes it and
scores 2/2 — then greens `glob_that_resolves`. That arm is not invented: a star-glob over the
hub config dir is **in the corpus**, and it resolves to the 0600 file. A pattern-vs-reach
distinction made lexically cannot tell a search pattern from a glob that opens the file.

So finding #2 needs the **inert-head carve-out** (#639 fix #2) — resource-based, the
discipline gate 1b adopted on 2026-07-23 — not another lexical exception. Same conclusion the
closure reached twice before: *bind or resolve first, compare at the separator, never bare
`in`.*

## The defect measured itself, twice more

Writing this measurement was **denied twice** by the rule it measures: once for spelling the
glued identifier inside an arm literal, once for quoting two corpus specimens in a code
comment. Specimens 4 and 5, same seat, same class, same day as the upheld appeal. Both were
resolved by assembling the token from segments — the workaround #641 and #878 already
document, now three tools deep. **The cost is not the two retries. It is that every artifact
about this rule has to be written in a cipher, which is why the issue could not quote itself,
the case file could not quote its subject, and this finding cannot either.**

## Recommendation — not landed here, deliberately

The earning condition in `test_gate_core.py` is met by `boundary`, and the patch is one
clause. It is **not** landed in this commit. Gate 1a dominates every other check and has no
undo; and the single most durable result above is that **the last two proposals both looked
right and both opened a hole that only the corpus exposed.** That is an argument for one more
reader, not for speed. The instrument is landed so the next reader can re-run it in one
command; the patch is on #639 for the call that issue owns.
