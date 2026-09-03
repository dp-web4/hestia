# After a bulk drain, every survivor is red for its own reason — and one matched the known cause by name while having a different one

claude-code · CBP · 2026-09-03

## The frame I arrived with was refuted by events

My previous wake closed on this:

> The bottleneck isn't instrumentation, it's that merge is human-only and I'm the
> largest producer into a queue only dp can drain. Worth asking whether the next
> wake should file nothing and instead work the queue — order the 65, identify
> which are mutually exclusive, and hand dp a merge sequence.

Between 04:46:34 and 08:37:16 today dp merged **56 PRs**, about 50 of them inside a
13-minute window (04:46:34–04:59:07). Open PRs went from ~65 to **19**.

So the queue was never ordering-limited, and a merge sequence would have been wasted
work. dp does not merge one PR at a time after deliberating on each; dp **bulk-drains**.
"Merge is human-only, 200/200 by dp" is true and was still misleading about cost —
I had silently converted *who* merges into *how expensive each merge is*, and those
are different quantities. The correction is recorded in
[[prj_my_merge_queue_not_ci_is_the_bottleneck]].

## What a bulk drain leaves behind

A drain is not uniform: it takes what can go. What survives is selected for being
blocked, so the residue is **all** signal. Of the 19 survivors, 5 had red CI, and the
tempting hypothesis was one cause for all of them:
`plugin tests (python)` had been red on main since `2dca549`, and **#864** ("unred
main", merged 08:17:49Z today) fixed two hygiene defects that were "failing every PR".
A PR last built before 08:17 is therefore *plausibly* red through no fault of its own.

That hypothesis was wrong for every single one. Five red PRs, five distinct causes:

| PR | failing test | actual cause | stale? |
|---|---|---|---|
| #873 | `shebang_exec_bit_test.py` | 1 file committed 100644 | no — ran 10:40, after #864 |
| #858 | `shebang_exec_bit_test.py` | 4 files committed 100644 | no — ran 10:59, after #864 |
| #816 | `primer_ownership_test.py` | fixture date fuse (below) | no |
| #731 | `public_boundary_test.py` | lands a file under `forum/`, a root #493 forbade | **looked** stale, was not |
| #787 | `rc124_is_not_unreachable_test.py` | flake (1 failure in 7 runs) | no |

## The one worth generalizing: a name match is not a cause match

#731's failing test was `tools/public_boundary_test.py` — **literally one of the two
tests #864 repaired**. Last built 08-31, well before the fix. Every visible signal said
"stale red, just re-run it."

It is not. Merging current `main` into the branch locally and re-running gives:

    public tree violates boundary:
      forum/codex/review-...-2026-08-26.md: installation-local root is tracked

The branch predates **#493**, which retired `forum/` as a public surface;
`tools/public_boundary.py` now lists it in `FORBIDDEN_ROOTS` and the check is on the
**path**, not the content. The PR exists to preserve a codex review record that is the
only copy of itself, and it was landing it on a path main refuses. Remedy is relocation
(`findings/`, where the same PR's other record already goes), not elision.

**The transferable rule: when a branch is red on the same test as a known main-side
breakage, that is a coincidence until you merge main in and re-run.** The failing test
name is the *symptom*, and #864's fix and #493's rule produce the same symptom from
unrelated causes. Cost of checking: one local merge. Cost of not checking: a re-run
that comes back red and a PR that looks intermittently broken.

## A test with a fuse: fixed fixture dates judged by a wall-clock rule

`plugins/member-mesh/tests/primer_ownership_test.py` dated every fixture notice
`2026-07-31T00:00:00Z`, hardcoded. #816 adds a startup judge that sets aside
`.expired` any retained primer whose notices are **all** past the daemon's 7d inbox
TTL. From 2026-08-07 onward, every fixture in that file ages out before case 2 asserts
anything.

The failure mode is worse than a plain red. Case 2 collects candidates by globbing
`notice-*.json` and `notice-*.exhausted`; an `.expired` file is neither, so it collects
nothing and reports

    exhausted=[]  live=[]

under the message *"codex's work list was parked after 2 of its own attempts"* — a
cause that did not occur. The subject was **gone**, not parked. A reader debugging this
starts on the retry-budget path and finds nothing wrong there, because nothing is.

What makes this more than a one-file bug: **the file's own comment already named the
hazard.**

> *"case 2 would then pass or fail on the age of a hardcoded 2026-07-31 date relative
> to whenever the suite runs, which is a flake, not a test"*

The author saw the class and defended against the **one** age rule that existed then
(discharge) by keeping the fixture ids in `i_owe`. That defence was per-rule. #816
added a second age rule and walked straight around it. A defence written against an
instance does not hold the class.

Fix is the general one: dates relative to now (`RECENT` = 1h, `OLDER` = 2h), which no
present or future age rule can silently retire. Case 2 is not vacuously green after it
— the arm requires `live` to be non-empty, which is precisely why it failed loudly
instead of passing on an empty directory. That is the guard working; only its *message*
was wrong.

## Guard-newer-than-branch is a real class, and it is benign

#873 and #858 are the same shape: `tools/shebang_exec_bit_test.py` landed on main at
08:17Z today, and both branches predate it, so files went in 100644. The guard names
the file and prints the remedy (`git update-index --chmod=+x`, because a plain
`chmod +x` is dropped under `core.filemode=false`). Cost per PR: one mode-only commit,
same blob.

This is the *opposite* of the inert-by-relocation class ([[ref_guards_index]]): a new
guard retroactively reds every open branch that violates it. That is not a defect and
should not be filed as one — but it does mean **the merge of a new guard silently adds
work to every branch already open**, and nobody is notified. Five of today's 19
survivors, two of them by this mechanism.

## #787 is a flake, and it is not #787's

`plugins/member-mesh/tests/rc124_is_not_unreachable_test.py`, arm *"1c. and the primer
is RETAINED, so the retry path still owns the wake"*. Measured: 1 failure in 7 runs
(0/3 on `main`, 1/4 on #787 merged with main — including 3 subsequent passes in the
*same* tree that produced the failure).

#787's diff is `core/src/server/{dashboard/index.html,http.rs,hub_tab.rs}` — Rust and
HTML only. It **cannot** causally reach a Python mesh-watcher test. The attribution is
therefore not "probably not #787's fault" but "not #787's fault", and the remedy is a
re-run. I did not push to that branch: it is dp's own working branch, so it is
diagnosed here rather than modified.

One failure is thin evidence for a *rate* and I am not claiming one. What is solid is
the causal exclusion, which needs no rate.

## What was done

- **#873** — exec bit on 1 file, mode only, same blob. Green locally.
- **#858** — exec bit on 4 files, mode only, same blobs. Green locally.
- **#816** — fixture dates made relative; 9 arms pass, `stale_primer_discharged_test.py`
  still green.
- **#731** — record relocated `forum/codex/` → `findings/`; boundary test passes.
- **#787** — diagnosed only, not touched.

## So what

The instinct I acted on ("work the queue instead of filing another document") was right
about *where* to spend the wake and wrong about *what the work was*. Ordering was never
the blocker. The blocker is that a drained queue leaves a residue that is 100% blocked,
and each blockage needs its own diagnosis — five PRs, five causes, one of which
impersonated the cause everyone already knew about.

The reusable output is the discipline, not the fixes: **merge main in and re-run before
believing a branch is stale-red.** I nearly re-ran #731 on the strength of a matching
test name and would have gotten a red back with no more information than I started with.
