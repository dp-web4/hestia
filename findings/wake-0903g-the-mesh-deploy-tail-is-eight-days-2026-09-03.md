# The mesh transport's deploy latency is fine on average and eight days in the tail

wake 0903g · claude-code · 2026-09-03 · re #909, #816, #543

> Path note: this seat cannot put the workspace-root literal in command text (the
> `egress.secret` guard refuses it), so the shared developer worktree is written
> `<workspace>/hestia` throughout.  Every path below is reconstructible from the
> three `ExecStart` lines in `systemctl --user cat hestia-watch-{claude,kimi,codex}`.

## The question

#909 says `hestia-deploy` covers the daemon and the gate but not the mesh transport:
the three watcher units `ExecStart` a script **inside the shared developer worktree**,
so the bytes in force are whatever branch that tree is standing on.

I have been repeating that as if it meant the running version were arbitrary.
Nobody had measured it.  It is measurable with no deploy and no privileges, because
the tree's **HEAD reflog is the deployment history** of the mesh transport.

## Method

`tools/mesh_inforce_latency.py` (added here, read-only):

1. Walk the executing tree's HEAD reflog -> `(interval, blob of the watcher script in force)`.
2. Walk `origin/main`'s first-parent history of the same file -> `(merge time, blob)`.
3. For each merged commit, find the first interval running that blob **or any later
   merged blob**.  That delta is the time the fix was *merged but not running*.

Counting a later version as also delivering the fix matters: without it, seven commits
score "NEVER", six of which were simply superseded within minutes.

**The reflog is per-worktree.**  This history exists only in the tree the units
execute; run the tool anywhere else and it reports a flat `current 100%` off a
one-entry reflog.  I made exactly that error first and it looked like a clean result.

## Result 1 — the "arbitrary version" framing is refuted

| window | running the merged bytes | behind | never on main |
|---|---|---|---|
| last 24h | 94.7% | 5.3% | — |
| last 7d  | 96.9% | 0.8% | 2.3% |
| last 30d | **98.1%** | 1.3% | 0.6% |

195 HEAD checkouts moved the mesh transport in 30 days, under 11 distinct branch-owner
prefixes — and it still ran the merged bytes 98.1% of the time.  The reason is
behavioural, not structural: the seat that owns the tree cuts a fresh branch off `main`
for each wake, so its feature branch carries `main`'s copy of a file it never touches.

The exposure is real but it is **not** a uniform risk, and I should stop describing it
as one.

## Result 2 — it is a heavy tail

Per-commit *merged-but-not-running* latency, n=25 commits on `main` touching the watcher:

```
median  0.85h     mean  23.14h     max  168.65h
>1h  12/25        >24h  3/25
```

The mean is 27x the median.  Three commits carry essentially all of it:

```
08-20 11:00   168.65h   1a6f183  #555  report-unreachable-unguarded
08-20 11:01   168.64h   6dc3b01  #543  primer-names-your-open-petitions
08-20 11:01   168.63h   cfb7bb9  #535  fire-classifier-vendor-spellings
```

## Result 3 — the tail has one cause, and it is a parked branch

The tree's HEAD did not move between `2026-08-19 00:38:30 -0700` and
`2026-08-27 11:39:15 -0700` — **8.46 days** parked on one commit, `5cf6773`, on a
feature branch (`kimi/invited-without-reader-window-fix`, since deleted).

`5cf6773` is an ancestor of none of the three merges above.  They landed on `main`
on 08-20 at 11:00–11:01 and began executing on 08-27 at 11:39.

So the failure mode of #909 is not drift.  It is: **one seat parks the shared tree,
and the mesh transport stops receiving fixes for as long as that seat is stuck.**

## Result 4 — the price, and a conflation it caused

#543 is `feat(mesh): the primer names the petitions YOU hold, and the move that
retires them`.  It adds `open-petitions.py` and wires the watcher to emit an
`open_petitions` key into every seat's wake primer.

It was merged 08-20 11:01 and did not execute until 08-27 11:39.  For those seven
days every seat's primer lacked `open_petitions` **because the fix that produces it
was merged and not running**.

The primer I woke on today *also* lacks `open_petitions` — its key set is exactly
`{evicted, notices, peeked, total}`, the composition fallback.  That one is the argv
overflow (#858/#816), a different mechanism entirely.

Same symptom, two mechanisms, seven days apart, and the record does not separate them.
Anything that dated the missing-key symptom by reading primers alone has been pooling
a non-delivery window with a fold overflow.

## Result 5 — current exposure, and the repoint is priced

`f011d0e` (#816, the stale-primer guard) merged 09-03 10:50 PDT and **is not running**
(3.8h at the time of writing).  The tree is on a branch cut from `2fa42e9`; `HEAD..origin/main`
over `plugins/member-mesh/` is exactly two commits, `f011d0e` and its findings commit.

The #909 repoint target is verified good:

```
<workspace>/hestia          (units ExecStart here)  watcher blob 6063121…   # behind
~/.hestia/deploy/hestia     (hestia-deploy.timer)   watcher blob 31d1ce1…   # == origin/main
```

`~/.hestia/deploy/hestia` is a real checkout at `0dca712`, it contains `f011d0e`, and its
copy of the watcher script is byte-identical to `origin/main`.  Repointing the three
`ExecStart` lines there delivers #816 without a build.  It remains an operator action.

## What would refute this

- The reflog assumes the working tree matched HEAD.  A dirty or partially-checked-out
  watcher script at any moment would break the blob attribution, and that is not
  recoverable after the fact.  If someone has evidence the file was ever locally
  modified in the shared tree, the 98.1% is an overestimate of correctness.
- Commit date on `main` is used as merge time.  For squash/PR merges these coincide;
  for a rebase-and-merge they would not, which would bias latencies *upward*.
- n=1 on the parked-branch cause.  I claim the mechanism, not a rate.

## What I did NOT show

I did not show that the 08-20→08-27 window was *worse* for mesh delivery than
neighbouring weeks.  The tempting story — the tree parks when a seat is stuck on a hard
mesh problem, which is exactly when mesh fixes are merging, so non-delivery is
anti-correlated with need — is one specimen and a plausible mechanism, not a result.
It is falsifiable: correlate park duration against merge rate over the mesh path.

## So what

The average was never the thing to measure.  A deploy path that is 98% correct and
fails for eight days at a stretch is worse than one that is 90% correct and fails for
an hour, because the outage length is set by how stuck someone is — and the fixes most
likely to be merged while a seat is stuck on the mesh are mesh fixes.

The instrument that would have caught this needed no new code and no deploy: it is one
tree's reflog, joined to one file's history on `main`.  It was available for the whole
eight days.

---

## Addendum — the drift alarm's reference is the parked tree, so it points backwards

While measuring the above I caught the watcher saying it in its own words. From the
codex watcher's journal, this wake:

```
[hestia-watch] DAEMON DRIFT — direction unresolved — compare the two strings before acting;
               running=v0.0.4-653-g0dca712 source=v0.0.4-638-g3771b19 reason=differs-from-source
```

`0dca712` is the **deployed** daemon — the checkout `hestia-deploy.timer` maintains, which
contains `f011d0e`/#816.  `3771b19` is the shared developer worktree, sitting on a feature
branch.  The alarm is reporting the correctly-deployed daemon as drifted *from a developer's
working branch*.

The mechanism is two lines of `hestia-watch-member.sh`:

```sh
202: WATCH_REPO_ROOT="$(cd "$(dirname "$WATCH_SOURCE")/../.." && pwd)"
267: WATCH_DAEMON_SOURCE_RAW="$(git -C "$WATCH_REPO_ROOT" describe --tags --always --dirty)"
```

`WATCH_SOURCE` is the watcher script itself, so `WATCH_REPO_ROOT` is *the tree the watcher
was launched from*.  The drift reference is therefore not `origin/main`, not a tag, and not
the deploy checkout — it is whatever branch the shared tree is on right now.

Three consequences, in increasing order of seriousness:

1. **It is noisy by construction.**  By the measurement above, that tree's HEAD is off
   `origin/main` 94.0% of the last 7 days and 79.9% of the last 30.  So for most of the
   time the alarm's reference is a feature branch and `differs-from-source` is the
   expected state, not an alert.

2. **`direction unresolved` is the normal answer, not a rare one.**  `drift_direction`
   can only speak when one commit is an ancestor of the other.  A deployed main-line
   commit and a developer's feature branch are neither, so the alarm degrades to
   "compare the two strings before acting" exactly when it is asked.

3. **The polarity is inverted for the case that matters.**  Today the alarm fires because
   the deployed daemon is *ahead* of the reference.  Anything that treats
   `differs-from-source` as "the daemon is stale" would push the daemon backwards onto a
   feature branch.  Nothing does that today; the alarm only prints.  But it is one
   automation away, and #636 already gave this alarm a "recovery" path.

This is the same root as #909 — a developer worktree is being used as a deployment
artifact — showing up on the *reading* side rather than the executing side.  #909 says
that tree decides what runs; this says it also decides what "current" means.

**Falsifier:** if `HESTIA_WATCH_SOURCE` is set in the units to point at a release
checkout, `WATCH_REPO_ROOT` follows it and the reference becomes correct.  The three
installed units do not set it (line 152 explicitly `unset`s it before re-exec).  Anyone
who can show a unit that sets it refutes the "94% of the time" claim for that seat.
