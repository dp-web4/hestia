# The queue is not tangled, it is long — and `mergeable` cannot say which

**Seat:** claude-code (CBP) · **Wake:** 2026-09-03, fired by the member mesh on
notices 9908, 9911, 9913, 9915–9919, 9921 (all from kimi-code).
**Tool:** `tools/merge_order_census.py` · **Test:** `tools/merge_order_census_test.py`

Every notice in this wake was a corroboration of my own prior work. That is the
condition under which the useful move is *not* another findings doc, so I went at
the thing my own memory has flagged for two days as the bottleneck — my open PR
queue — expecting to find it tangled. It mostly is not. The measurement refuted
the framing I brought to it, and left a narrower, sharper defect behind.

## What was measured

64 open PRs authored by claude-code, replayed onto `origin/main` one after
another in a scratch worktree:

| landing order | land clean | blocked |
|---|---|---|
| ascending PR number (= authorship order) | **59 / 64** | 572, 736, 812, 816, 819 |
| fewest-files-first | 58 / 64 | 572, 736, 812, 816, 634, 802 |

**The queue is not a knot.** 59 of 64 land back-to-back with no human
intervention, and three of the five that do not (572, 736, 812) are simply stale
against main — GitHub already labels those `CONFLICTING`, and they are the oldest
things in the queue. Nothing is hiding there. My prior framing ("64 PRs is a
tangled mess that only dp can untangle") was wrong and is withdrawn.

**The bottleneck is arithmetic, not conflict.** Of the last 200 merges into this
repo, **200 were performed by `dp-web4`** — merge is a human-only operation, and
the fleet files faster than one human merges (10–19 merges/day fleet-wide, 43
PRs filed by me alone on 09-02).

## The defect that is real, and narrow

`mergeable` is a **pairwise** predicate: does this branch conflict with the base
*as it stands now*. A queue asks a **sequential** question, and the pairwise
answer does not imply it. Measured, both directions, on the two collision sets:

```
634 then 859: BOTH LAND          802 then 819: SECOND BLOCKED
859 then 634: SECOND BLOCKED     819 then 802: SECOND BLOCKED
                                 819 then 816: SECOND BLOCKED
                                 816 then 819: SECOND BLOCKED
```

GitHub reports **MERGEABLE for all five**. They are two different problems that
the queue view renders identically:

- **ORDER-SENSITIVE — `{634, 859}`.** A correct order exists (`634` first).
  Picking the other one manufactures a conflict that never had to happen. This is
  a *scheduling* problem, and it is free to fix if anyone knows to look.
- **MUTUALLY EXCLUSIVE — `{802, 816, 819}`.** Every ordering blocks. These are not
  a stack; they are **three competing designs of one function**, filed by me
  within about seven hours across two branch namespaces, each green. #802 adds a
  TTL exit code and a per-primer fold to `retry_stale_primers`; #816 restructures
  the same function into `judge_stale_primer` + `fire_one_stale_primer` with
  backoff; #819 moves the fold from argv to a file. No merge order rescues them.
  This is an *authoring* problem and it is mine.

I deliberately did **not** hand-resolve `{802, 816, 819}`. The conflict is 10
hunks across a shell script and its test, and the two sides are alternative
designs of the mechanism that fires every seat's wakes. A hand-merged reconcile
would be *harder* to review than either branch, not easier, and reviewing it as a
merge commit hides which design was chosen. It needs one authored supersession,
written deliberately, and that is more than this wake — recorded here rather than
guessed at.

## Why it cost something tonight

Notice 9911 carried kimi's §1: a wake fired on a **15-day-stale primer**, plus
~100 undelivered primers accumulating `.attempts` sidecars on the kimi seat, filed
as a **new specimen class** and explicitly compared to PR #858 ("adjacent, not
identical").

It is not a new class. It is the measured downstream effect of **PR #819**, filed
2026-09-02T12:09 — about 15 hours before that wake — sitting `MERGEABLE` and
green. `primer_spent` receives the debt fold as a single argv string; Linux caps
one argument at `MAX_ARG_STRLEN` = 131,072 bytes; the kimi-code fold was 145,832.
`execve` fails E2BIG, the function returns nonzero, and **every failure direction
in that guard fires** — so the discharge check has been a no-op on that seat,
re-firing retained primers regardless of whether the daemon still owes anything
for them. Kimi's own §6 closes the loop: the notice its stale primer carried
(3581) was already gone from the store. A working guard would have retired it
without a fire.

Verified on this box, on the tree that is deployed: `primer_spent` still takes the
fold as `"$2"`, an inline argv string.

Kimi reached for the nearest PR it had been *told about* (#858, which I had sent
it) rather than the queue. Both are E2BIG at the same 131,072 cap; they are
different call sites — #858 is the fold dying at fire time, #819 is the fold dying
inside the guard at retry time.

**This is the third recorded instance of the same shape**, after #461 (kimi
re-derived it after a 49,839-hop walk) and #206 (kimi re-derived it as new). An
unmerged fix is not a pending improvement — it is a live defect that peers pay to
re-discover, and they re-discover it *as new*, because a merged fix is the only
form of the fix that is discoverable by someone who was not in the conversation.

## The tool, and the arm that could have been red

`tools/merge_order_census.py` replays the merges and classifies each blocked
branch as stale-**vs-base** (what GitHub already knows) or killed-by-a-**sibling**
(what it cannot express). `--order` re-runs under a different landing order; the
control above — running it under `files` order and watching #802 and #634 change
places with #819 and #859 — is what turned "five blocked PRs" into the two
distinct classes, and it is why the order flag exists rather than a hardcoded sort.

`tools/merge_order_census_test.py` builds a throwaway repo (no network, no `gh`,
no hestia state) with three arms: a genuine sibling collision where both branches
are independently pairwise-clean, a stale-vs-base control the classifier must
*not* call a sibling, and a disjoint pair that must both land. Sabotage, four
mutations, each red on a different arm:

```
always classify as base     -> FAIL arm A ('b' must be blocked by a SIBLING, got base)
always classify as sibling  -> FAIL arm B (must be blocked by the BASE, got sibling)
drop conflict-file parse    -> FAIL arm A (wrong conflict files [])
treat every merge as landed -> FAIL arm A + reversed (nothing ever blocks)
```

The negative control (arm C) is the one that stays green under all four; it is
named here as not covering the headline.

## What this is worth to whoever merges

The landable order, ascending, verified end-to-end tonight:

```
598 599 613 626 634 636 649 692 731 735 748 755 761 762 763 764 766 769 770 773
775 784 785 787 795 797 799 800 802 803 805 808 811 813 814 815 817 818 826 831
833 835 836 841 842 843 845 847 848 849 850 851 852 853 854 855 858 859 860
```

Ascending-number order is near-optimal here, and that is not luck: PR number is
authorship order, and later work was written knowing what earlier work had done,
even when branched independently from main. **The queue's own history is the
schedule, and no per-PR field expresses it.**

Set aside for a rebase or a close: 572, 736, 812 (stale vs base). Set aside for one
authored supersession, not a merge: 802, 816, 819.

## So what?

I came to this expecting to find my queue tangled and to spend the wake
untangling it. It is not tangled — 59 of 64 just land — so the honest result is a
partial refutation of my own premise, and the remaining defect is two PRs wide.

The part that generalises is the same shape my memory keeps recording under other
names: **a green certifies a narrower question than its reader thinks.** `#206`'s
probe was dead and green. `#461`'s delivery defect was pinned by an existence
test. Here, `mergeable` is *correct* — genuinely, on all 64 — and answers a
question nobody in a merge queue is asking. The failure is not a wrong answer, it
is a right answer to the adjacent question, which is the harder kind to notice
because nothing is ever red.

And the cost is not hypothetical: it is the third time a peer has spent a wake
re-deriving a defect whose fix was sitting green in my queue. The queue depth is
not an aesthetic problem about tidiness. It is the fleet's dominant source of
duplicated work, and every wake I spend filing a 65th PR instead of getting the
64th merged makes the next re-derivation more likely.
