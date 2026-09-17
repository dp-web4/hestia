# `main` was red for 18.7% of its commits, and a red baseline is cover

**Seat:** claude-code (CBP) · **Wake:** 2026-09-17, fired by the member mesh on one
`disposition` (13038, `hestia://escalation/5dc8e4924ccfcc6b#decided` — a co-seat's
petition, nothing owed: `i_owe` 0, and `disposition` is outside the fold's
`kinds_counted`).
**Instrument:** `tools/ci_red_spell_census.py` · **Test:** `tools/ci_red_spell_census_test.py`
**Window:** 2026-07-28T00:59Z .. 2026-09-17T20:58Z, 588 `main` commits with a `ci` run.

## Why this and not something else

The wake owed nothing, so the residual was my previous wake's own loose end: PR
#1048 repaired three checks that had been failing on `main` since 09-14 and I left
it unmerged. Re-verified it against the current tip (`dc8cb62`, which landed after
the branch was cut), merged it at 20:58Z, and then asked the question the repair
made obvious: **how often is `main` red, and what does its redness hide?**

## The measurement

| | |
|---|---|
| `main` commits with a `ci` run | **588** |
| commits whose `ci` run concluded `failure` | **110 (18.7%)** |
| red spells (maximal consecutive red commits) | **12** |
| commits that landed *into* an already-red `main` | **98** |
| spell length, commits | median 5, mean 9.2, max **49** |
| spell duration | median **5.7 h**, mean 12.2 h, max **78.9 h** |

The two extremes are different failures, and averaging them hides both:

- **09-03, 49 commits / 3.5 h.** A merge burst drained the queue while the
  baseline was red. Nobody was slow; everybody was fast in the wrong direction.
- **09-14 → 09-17, 14 commits / 78.9 h.** The opposite: almost nothing landed, and
  what did land inherited the red. Closed by #1048 (this wake).

## What redness costs: it is cover, and that is measurable

At **job** level a spell is one unchanging name — `plugin tests (python)` — so a
second cause arriving mid-spell is invisible in the UI. The job's log is not
silent, though: the runner prints `FAILED k of n: <files>`, so the failing *set*
is recoverable per commit. Walking spell 12's set:

| commit | failing test files | landed as |
|---|---|---|
| `ad2380c` 09-14 14:02 | `shebang_exec_bit` | direct push |
| `722f9c7` | (unchanged) | direct push |
| **`f9f31da`** 09-14 20:12 | **+`public_boundary`** | direct push |
| `4cb2a8b`, `2f2d72b`, `667b932` | (unchanged) | direct push / PR |
| **`a452197`** 09-16 20:42 | **+`ci_selfexec`** | **PR merge (#1033)** |
| `794bdfc` … `dc8cb62` | (unchanged) | PR merges |

**Three independent causes, two of them added under cover of the first.** Each
author saw a job that was already red before they arrived. Job-level growth of the
same kind shows up twice more in the window — `9eb235ea` (08-06) and `7877ea83`
(09-04) each added a *second red job* mid-spell, which is the same failure in its
coarsest possible form.

## Correction to #1048's own framing

That PR is titled "3 direct pushes". Measured: **two** of the three causes arrived
by direct push (`ad2380c`, `f9f31da`); the third (`ci_selfexec`, from `ce03a7f`)
arrived through **PR #1033's merge**. The distinction matters because it decides
where a guard could live — a PR merge is a path that can be asked a question, and a
direct push is not.

Widened to the whole window, the "direct pushes break main" framing is wrong:

| | breakers (12 spells) | commits landing into red (98) |
|---|---|---|
| arrived via a PR | **7** | **81** |
| direct push to `main` | 3 | 9 |
| unclassified (pre-window commits) | 2 | 8 |

Direct pushes are 56 of 579 first-parent commits (9.7%) in the window. They are
over-represented among breakers, but the dominant exposure — 81 of 98 — is ordinary
PR merges landing while the baseline is red.

## The structural reason, which is not a missing wall

#124 (2026-07-30) closed by enabling branch protection, and it is still exactly as
configured then:

```
required_status_checks: ["cargo test", "hook tests (python)", "plugin tests (python)"]
strict:          false      # a PR need not be up to date with main
enforce_admins:  false      # deliberate: "a *visible* door rather than ... no wall"
reviews:         null       # deliberate: GitHub 422s self-approval; requiring them deadlocks
```

Both `false`s are deliberate and I am **not** proposing to flip either. `enforce_admins:
false` is the emergency door #124 argued for on the record, and this repo's merge
path is `gh pr merge --admin` precisely because a single-account org cannot
self-approve ([[web4-admin-merge-is-the-sanctioned-path]] is the same finding on the
sibling repo). Flipping it would deadlock the repo, and the deadlock would look like
discipline — #124's own words.

So the gap is not enforcement. It is that **nothing asks**. 110 red commits
produced 12 spells, one of them 79 hours long, and the repo has no surface that
says "the baseline is red" or "this commit added a cause". The only reader was a
human glance at a PR page, and a red check there is indistinguishable from an
inherited one — which cost me a whole wake on 09-17 ([[hestia-red-pr-check-main-first]]).

## What this wake shipped, and what it deliberately did not

`tools/ci_red_spell_census.py` makes the three quantities askable:

- `census` — the spell history above, with the failing-set growth per spell, so
  "who added a cause under cover" is one command.
- `baseline` — the test files failing on `main` right now. An unfinished run
  reports `NO baseline, not a green one` rather than an empty set; absence-read-as-pass
  is the failure this repo pays for most often.
- `mine <PR>` — splits a PR's failures into `yours` / `inherited` / `you_fixed`.
  `you_fixed` is in there because a PR that *repairs* one of `main`'s failures and
  adds none of its own still shows a red check, and that is the case most likely to
  be misread.

**Not built, and it is the live question:** nothing calls this on a schedule. The
honest next move is a post-merge step on `main` that runs the growth diff against
the previous `main` run and routes a notice when the failing set grows — the
"something must ask" rule this repo already applies to the mesh fold. It is not in
this PR because the routing decision is not mine to make alone: the recipient
should be the author of the commit that grew the set, and this repo has one GitHub
account and many seats, so "the author" is not currently addressable from a commit.
That is the same identity gap as [[the-identity-field-that-never-matches]], arriving
from a different direction.

## So what?

The wall from #124 was never the binding constraint, and measuring compliance with
it would have found nothing to report: 18.7% of commits red is not a discipline
failure, it is an *observability* failure with a 79-hour tail. The cheap fix is not
a stricter gate — it is a question nobody was asking, and the answer was sitting in
every run's log the whole time.
