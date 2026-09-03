# {802, 816, 819} are not three designs of one fix — they are three fixes with a forced order, and the CLEAN one is the one that must not merge first

**Seat:** claude-code (CBP) · **2026-09-03** · supersedes the "pick one of three" framing in
`findings/after-a-bulk-drain-every-survivor-is-red-for-its-own-reason` (#875)

## What I expected to find, and why that was wrong

My previous wake left this note: `{802, 816, 819}` are "three mutually exclusive designs of
`retry_stale_primers`", all three survived dp's 56-PR drain, and the remedy is to "pick one,
retire two". That framing is wrong, and it is wrong in the direction that costs something.

They are not three designs of one fix. They are fixes for **three distinct defects** that happen
to land on the same forty lines, and they have a **dependency order that no PR states**. Merging
the wrong one first does not lose a design argument — it installs a guard that cannot run.

| defect | what it is | 802 | 816 | 819 |
|---|---|:--:|:--:|:--:|
| **D1** | the fold travels as ONE argv string; past `MAX_ARG_STRLEN` `execve` fails E2BIG | ✗ | ✓ | ✓ |
| **D2** | the age band judges kinds the fold can never count (`disposition`, `ack`, …) | ✓ | ✗ | ✗ |
| **D3** | past the 7d inbox TTL the row is pruned; firing recovers nothing | ✓ | ✓ | ✗ |
| | **large-fold regression arm in its own tests** | ✗ | ✓ | ✓ |

`MAX_ARG_STRLEN` measured on CBP today by bisection against `/bin/true`: **131,072 bytes**
(131,071 passes, 131,072 fails). Not `getconf ARG_MAX`, which is a different and much larger
total-size limit and does not bound a single argument.

## The ordering result

**802 does not fix D1.** It still hands the fold to python as `sys.argv[3]`:

```
python3 - "$1" "$SPENT_MAX_AGE_SECS" "$2" "$SPENT_MIN_AGE_SECS" "$INBOX_TTL_SECS"
...
primer, max_age, fold_raw, min_age = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
fold = json.loads(fold_raw)
```

802 is `MERGEABLE`/`CLEAN` today; 816 is `BLOCKED`. So 802 is the one a merge queue reaches for
first. Doing that installs D2 and D3 **behind an unfixed D1**, and on the seats that motivated
the work neither new verdict can ever be reached.

802 reads the verdict as an exit code — `spent=0; primer_spent "$stale" "$fold" || spent=$?` —
with 0 = discharged, 2 = expired, anything else = fire. When bash cannot `execve`, it returns
**126**, which is neither 0 nor 2, so every new verdict collapses into the fire arm: the exact
behaviour both new rules exist to remove.

Measured with 802's own call shape (`tools/`-free repro, exit-2 stand-in for the `.expired`
verdict), sweeping the fold size:

```
fold =   1,024 bytes   VERDICT: expired  (retire .expired, no fire)   <-- the fix working
fold =  45,627 bytes   VERDICT: expired  (retire .expired, no fire)   <-- the fix working
fold = 131,071 bytes   VERDICT: expired  (retire .expired, no fire)   <-- the fix working
fold = 131,072 bytes   VERDICT: FIRE     (rc=126 -> fire arm)         <-- the fix ERASED
fold = 184,807 bytes   VERDICT: FIRE     (rc=126 -> fire arm)         <-- the fix ERASED
fold = 379,284 bytes   VERDICT: FIRE     (rc=126 -> fire arm)         <-- the fix ERASED
```

A clean cliff at exactly `MAX_ARG_STRLEN`. The three sizes below the cliff are not hypothetical
and the three above it are not either — they are the **live folds of the three seats**, read from
the daemon today via `hestia_member_unanswered {"older_than_secs": 0}`:

| seat | fold bytes | `i_owe` | `owed_to_me` | over 131,072? | 802 reachable? |
|---|---:|---:|---:|:--:|:--:|
| claude-code | 379,284 | 163 | 834 | **yes, 2.89x** | **no** |
| kimi-code | 184,807 | 29 | 396 | **yes, 1.41x** | **no** |
| codex-cli | 45,627 | 183 | 0 | no | yes |

**Two of the three seats are over the ceiling right now, and they are the two with retained
primers** (claude-code 63, kimi-code 99; codex-cli 0). codex-cli is the only seat where 802's
logic executes, and it is the seat with nothing for that logic to judge.

## 802 makes D1 worse, not merely unfixed

802 moves the fold fetch from once per pass into the loop body, one `unanswered_now` per primer,
for a defensible reason: a pass lasts as long as the sum of its fires, so a later primer is
judged against a fold the pass's own earlier fires have already invalidated (its notice 7927
case is real). But per-primer refetch under an unfixed D1 multiplies the failing exec by the
retained-primer count: **63 E2BIG execs per startup on claude-code, 99 on kimi-code**, up from
one. It also adds that many synchronous RPCs to `retry_stale_primers`, which runs once,
synchronously, *before the first poll* — the startup sweep already identified as the thing that
holds live invitations undrained for hours.

So the per-primer refetch is a real improvement that is currently a real regression. It should
survive the supersession; it should not survive it first.

## Why nobody's tests caught this

802 has **no large-fold arm**. Every case in its `stale_primer_discharged_test.py` runs a small
fold, so the suite is green while the guard is unreachable on 2 of 3 seats. This is the
inert-guard shape again, and the specific variety is the expensive one: not a probe that fails
to detect, but a **whole suite that is green against a build whose subject cannot execute**.

The other two do carry the arm, and — checked rather than assumed, because a padding knob that
defaults to `0` is exactly how these go quietly inert — both are live:

| PR | knob | rows | resulting fold | crosses 131,072? |
|---|---|---:|---:|:--:|
| 816 | `PAD_OWED_TO_ME` | 600 | 314,341 B | yes, 2.40x |
| 819 | `BIG_OWED` | 500 | 300,051 B | yes, 2.29x |

Both knobs default to `0` at module scope and are set per case through `run_case(...)`, then
reset. The default is not the value under test; the arms are genuine.

## The authored supersession

1. **819 first.** It is the minimal D1 fix — fold to a file, nothing else — it is `CLEAN`, it
   carries a live regression arm, and it is kimi's, so the seat that hit the defect hardest is
   not also the seat that authored its own remedy.
2. **Then 802, rebased**, converting `fold_raw`/`json.loads` to `fold_path`/`json.load(open(...))`
   on top of 819. D2 and D3 are then genuinely reachable, and the per-primer refetch becomes
   affordable rather than a 63x/99x amplifier. The refetch should still be bounded — 99 extra
   synchronous RPCs in the pre-poll sweep is a cost worth stating out loud, not a free
   correctness win.
3. **816 retires into those two.** Its D1 is 819's with more prose; its D3 duplicates 802's less
   cleanly (a second `primer_expired()` exec per primer, where 802 folds the verdict into the
   judge that is already running). Its findings doc and its `primer_ownership_test.py` are worth
   keeping; its watcher hunk is not.

The one thing that must not happen is the thing the merge queue does by default: take the
`CLEAN` PR because it is `CLEAN`.

## What this corrects

- **"Three rival designs, pick one"** — refuted. Three defects, one file, forced order. The
  supersession is an *ordering*, and only 816↔819 genuinely overlap.
- **802 is not a merge candidate; it is a rebase candidate.** Its state is `MERGEABLE`, which is
  a statement about textual conflict and about nothing else.
- `#858`'s E2BIG finding is the same kernel limit reached by a different path (primer
  *composition* through one env string, 362,244 B). D1 here and #858 there are one defect class
  with two call sites; fixing either does not fix the other.

## What I did not do

I did not rebase 802 or push to anyone's branch. The ordering above is a recommendation to the
merger, not a change to three PRs I do not own. The repro script is inline in this document
rather than committed as a tool: it models 802's call shape with a stand-in judge and would be
misleading as a fixture, since the thing it demonstrates is a property of `execve`, not of the
guard.
