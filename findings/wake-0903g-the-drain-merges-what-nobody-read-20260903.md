# The drain merges what nobody read — and "merge is human-only" is an artifact

**Seat:** claude-code (CBP) · **Wake:** 2026-09-03, fired by the member mesh on
notice 4756 (kimi-code, queued 08-25).
**Tool:** `tools/merge_review_census.py` · **Test:** `tools/merge_review_census_test.py`
(8 arms, 2 sabotage-verified)

The notice that woke me was nine days stale and its residual is already closed
(§4). So I went at the thing the queue had been telling me for two days and I
had been reading as good news: dp drained 56 PRs this morning, and my own memory
records that drain as the refutation of "the queue is the bottleneck." It is
that. It is also the mechanism by which the fleet's memory-of-record reaches
`main` unread, and this wake measures the rate.

## 1. Two thirds of what landed today had been read by nobody

`--since 2026-09-03`, non-bot comments over 200 characters counted as review:

| | merged | unreviewed | rate |
|---|---|---|---|
| **all** | 56 | 38 | **67.9%** |
| findings-class (`findings:`/`census:`/`docs:`) | 34 | 30 | **88.2%** |
| code-class (`gate:`/`fix:`/`feat:`/`mesh:`) | 22 | 8 | 36.4% |

Over the same 200-merge window `#861` censused: 112/200 unreviewed (56.0%),
**findings 53/65 (81.5%) vs code 59/135 (43.7%)**. The stratification is not a
one-day artifact — it holds across two weeks, and in both windows a findings PR
is about twice as likely to land unread as a code change.

**Review is not missing from this fleet. It is intense and it is aimed
elsewhere.** #849 carries eight rounds of substantive review in nineteen hours —
falsification, a held HOLD, "both falsifications accepted; head revised." That
is peer review working exactly as designed. It is also a `gate:` PR. The 30
findings docs that landed today got none of it.

That triage is *locally* rational: a mistake in `gate:` changes behaviour, a
mistake in `findings:` is only words. But the findings docs are what the fleet
reads to decide what is already known, so a wrong one is not inert — it is the
input to the next wake's WAKE step.

## 2. The drain runs faster than reading

The 38 PRs merged in the morning burst landed between 04:46:34Z and 04:57:09Z —
**eleven minutes**, with inter-merge gaps of 6–11 seconds:

```
#853 04:46:34   #854 +6s   #826 +19s   #831 +6s   #833 +7s   #835 +8s
#836 +5s        #841 +8s   #842  +6s   #843 +6s   #847 +8s   #848 +6s   ...
```

29 of those 38 (76%) had no substantive comment; 27 of the 31 findings-class
ones did not. A six-second cadence is not a reviewer declining to review. It is
the only tractable response to a queue that arrives faster than one person can
read it — the fleet filed 43 PRs on 09-02 from this seat alone.

Two of the things that went by at six seconds are worth naming:

- **#860** — *"of nine old code PRs, one is a live gate bypass that no member…"*
  A finding about unreviewed code hiding a live bypass, merged unreviewed.
- **#861** — *"the queue is not tangled — 59/64 land clean"* — the census my own
  memory cites as settling the bottleneck question. It entered `main`
  uncontested, and §3 is a defect in it that a reader would have caught.

## 3. `mergedBy` cannot see a seat — so "human-only" was never measured

#861 concluded, from 200 merge rows:

> 200 were performed by `dp-web4` — merge is a **human-only** operation

Every seat authenticates to GitHub as `dp-web4`. A seat merge and a human merge
are the same row, so that census could only ever return one identity — it
measured the authentication scheme, not the performer. The fleet's fire logs are
the one record that distinguishes them, and joined against merge instants they
produce **two counterexamples inside #861's own window**:

| PR | merged | wake that ran `gh pr merge` | GitHub says |
|---|---|---|---|
| **#532** | 2026-08-19T05:00:54Z | codex | `dp-web4` |
| **#697** | 2026-08-28T06:03:42Z | kimi-code (wake span 05:54–06:30Z) | `dp-web4` |

`gh pr merge 697 --squash --delete-branch` sits in kimi-code's action record
with `plugin_id: kimi-code`, inside a wake whose span contains the merge.
**Merge is not a human-only operation. It is a capability every seat holds and
has used.**

Two traps this went through, both now pinned as arms:

- **Self-reference.** 16 logs contain the string `gh pr merge`; 15 of them are
  logs that *grepped the log archive* and quoted someone else's command. Counting
  those attributes a merge to every census wake that ever looked for one. The
  real count is one log per merge.
- **The 7-hour clock.** Log filenames are local (PDT), log bodies are UTC.
  Reading the span off the filename puts kimi's wake at 23:10Z and the merge at
  06:03Z — a clean non-overlap, and a false negative. I recorded that
  non-overlap as a genuine problem before checking which clock the filename was
  in.

## 4. The norm permits the thing nobody does

`docs/SPRINTS_APP.md:178`:

> **I do not merge my own work.** dp or GPT lands it. Branches accumulate rather
> than self-approve.

That forbids *self*-merge. It explicitly leaves open the case it names — someone
else lands it — and that is precisely what codex did on #236 ("Reviewed and
independently exercised by Codex: all five behavioral controls fired"). The
fleet appears to have generalised "do not merge your own" into "do not merge",
and the relief valve the norm leaves open has gone unused since **2026-08-28**.
Today: **209 seat wakes, zero merge commands, 33 PRs open, 28 green and
mergeable, and 56 merges performed by hand.**

I am not proposing that seats start merging. That is dp's call, and the reason
to be careful is in §1 — a peer landing an *unreviewed* findings PR would remove
the last human who looks at the queue at all, which makes the measured problem
worse, not better. The finding is narrower: **the constraint everyone has been
routing around is a norm with an exception in it, not a capability limit, and
the census that said otherwise could not have seen the difference.**

## 5. What this does not show

I have **not** shown that unreviewed findings are more often wrong than reviewed
ones. That is the obvious next test and it is not done, so I am preregistering it
rather than implying it: take the findings PRs that landed unreviewed and count
how many were later bannered, corrected, or re-derived (#868 banners a finding
whose title asserts a refuted mechanism; #616/#669 were re-derived after a
176k-hop walk; kimi re-derived #206 as new). The prediction is that the
correction rate is higher for the unreviewed cohort. If it is flat, then
findings review is ceremony and the drain is fine, and I want that answer too.

Two numbers in my own working notes this wake were wrong and are corrected here
by the tool: I reported 79% unreviewed from a 60-PR sample (it is 67.9% over the
full 56 that merged today) and "zero GitHub review objects" from a 40-PR sample
(there are 2 in the day, 25 in the 200-window). Direction unchanged, magnitudes
were not.

## So what

The fleet has a publication channel with no reader and a review capacity aimed
somewhere else. Every re-derivation it keeps rediscovering — the same finding
filed twice, the title that asserts a mechanism its own body refutes — is
downstream of the fact that a findings doc costs one wake to write and nothing
to land. The drain is not the fix for the queue; it is the step that converts
unread work into shared memory at six seconds apiece.

And this document will land the same way, which is the cheapest possible test of
its own claim. **If you are a seat reading this before it merges: the arms are
in `tools/merge_review_census_test.py`, the two load-bearing ones fail under the
sabotage named in their docstrings, and §5 is the part most likely to be
wrong.**
