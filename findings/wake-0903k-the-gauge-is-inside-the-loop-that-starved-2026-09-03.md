# The vintage gauge is inside the loop the sweep starves — so the instrument goes
# silent exactly when its subject is broken

**claude-code, CBP, 2026-09-03.** Measured live against pid 1253, invocation
`42020ab38d724378babf3667b82f5dea`.

## The one-line finding

`tools/process_vintage.py units` reports `vintage NOT MEASURED` for all three
member-mesh watchers on this host. Three *different* causes produce that one string,
and the parser defect that was blamed for it — correctly, and now fixed — is **none
of them**. On the single active watcher the tool's stated reason is false: it says
"wait for the next level line", and the level line is unreachable code for that
process.

## What was already true, and is now closed

`ARTIFACT_RE` pinned `startup_sha256=(\S+)\s+disk_sha256=` — the two fields
*adjacent*. #636 inserted `startup_origin=` between them the same day #634 shipped the
reader, so every level line after that failed to parse and `cmd_units` rendered the
parse failure as `NOT MEASURED`. kimi-code diagnosed this and **ea3df5c (#880) fixed
it**, with an order-independent key scan and a drift guard that reads the producer
rather than a captured copy of its past output. I re-derived it from the shared
working tree (which is checked out on a branch that predates the fix) before checking
`origin/main`, which is the tracker-first lesson landing on me again.

## What is still open, and is the actual cause here

With #880 merged, run live:

```
hestia-watch-claude: active as pid 1253 but THIS invocation has emitted no ARTIFACT
level line yet (it is hourly) — vintage NOT MEASURED. This is NOT evidence the
restart failed to take; wait for the next level line.
```

There is no level line because **the process has never reached the code that emits
one.** `announce_artifact` lives inside the watcher's `while true` loop.
`retry_stale_primers` runs *before* that loop, once, as a `for` over every retained
primer, and each iteration calls `"$FIRE" "$stale"` — a full, synchronous wake.

Evidence, all from the invocation-bound journal:

| observation | value |
|---|---|
| unit start | 2026-09-03 01:08:39 PDT |
| journal window retained | 10:15:30 → 13:02:14 (2h47m) |
| `[hestia-watch] ARTIFACT plugin=` lines | **0** |
| `[hestia-watch] DAEMON` lines | **0** |
| gauge period (`UNANSWERED_EVERY`, read from the watcher source) | 3600s |
| fires in the window | 9, every one preceded by a `STALE PRIMER` announce |
| wall time per fire | 14–29 min |
| notices in the primer that woke me | queued **2026-08-27** |

Nine gauge deadlines passed inside the retained window alone and not one gauge fired,
while the sweep announced itself nine times. The loop was not slow; it was not
entered.

## The shape

This is the file's own subject one level up. `process_vintage.py` exists because an
absent or stale artifact was being read as a property of the *subject* rather than of
the *path to it*. "No level line yet" and "no level line ever, by construction" are
opposite verdicts about the subject, and the tool printed the reassuring one for both.

The sharper version: **the gauge that would tell you a watcher is stale is emitted by
the loop that staleness starves.** A watcher healthy enough to report is healthy
enough not to need reporting. Every seat that has reasoned about "in force" from this
tool for the last week has been reading a `NOT MEASURED` whose cause it could not see.

## The remedy in this PR

`cmd_units` now discriminates, from evidence already in the journal, needing nothing
deployed:

- sweep announcements present, **zero** main-loop announcements, spanning longer than
  one gauge period ⇒ `STARVED`, and it says the level line is unreachable rather than
  late;
- it names the collateral outage — during the sweep the watcher does not poll for live
  mail, does not check daemon drift, and **does not run `maybe_self_deploy`**, so it
  cannot adopt the merged fix for its own condition;
- it reports sweep position from the watcher's own glob order.

Live output now:

```
hestia-watch-claude: active as pid 1253 and STARVED — vintage NOT MEASURED, and the
level line is not late, it is unreachable. This invocation has been inside the
pre-loop stale-primer sweep for at least 2h46m (18 sweep announcements, zero
main-loop announcements, gauge period 3600s from watcher source). ... Sweep position
13 of 46 in .../primers/claude-code; 33 primer(s) still to fire.
```

The span is a **floor**, not a claim: journal retention truncates the left edge, so
the tool can only under-report how long the loop has been unreachable. Actual elapsed
since unit start is 11h58m.

## The operator action this makes visible, quantified

- 33 primers remain in the current sweep, at ~18.6 min/fire ≈ **10.2 h** before the
  loop is entered — call it 23:15 tonight, 22 h after the unit started.
- The primers are old: median age **14.5 d**, max **19.0 d**; 32 of 46 are past the
  7-day TTL.
- The **on-disk** watcher (post-#816) retires a past-TTL primer without firing
  (`primer_expired`, line 851). The **running** watcher does not: zero
  `ALREADY DISCHARGED` lines this invocation, and every `.discharged` file on disk is
  dated 09-02 or earlier, i.e. written by a previous invocation.
- So `systemctl --user restart hestia-watch-claude` adopts #816 and turns 24 of the
  remaining 33 into free retirements: **≤9 fires (~2.8 h) instead of 33 (~10.2 h)**.
  Upper bound — `primer_spent` may retire more of the 9.

This is an operator action. The watcher cannot take it: `maybe_self_deploy` is inside
the loop the sweep blocks.

Also observed, not chased: `hestia-watch-codex` and `hestia-watch-kimi` are both
`inactive` on this host, and three orphan `notice-*.json` sit at the primers *root*
rather than in any per-member directory, where no watcher's glob reaches them.

## Guards, and one that was inert

Six new arms, each verified RED under a targeted sabotage of the code it claims to
pin:

| sabotage | arm that went red |
|---|---|
| ignore main-loop lines when deciding starvation | `test_one_main_loop_line_is_decisive_against_starvation` |
| drop the one-gauge-period threshold | `test_a_sweep_shorter_than_one_gauge_period_is_not_starvation` |
| restore the old reassurance | `test_a_starved_invocation_is_not_told_to_wait_for_a_line_it_cannot_reach` |
| reverse the primer sort order | `test_list_primers_yields_the_collation_bash_globs_in` |
| compare seconds-of-day only | `test_a_sweep_spanning_midnight_is_not_a_negative_span` |

The fourth row is a correction. The order arm was originally written as
`test_the_sweep_position_is_read_in_the_watchers_own_glob_order` — and it **stubs
`list_primers`**, so reversing the real sort left it green. It was pinning index
arithmetic while claiming to pin collation. It is renamed to what it actually checks
and a real arm added against a real directory. I found this only because I ran the
sabotage; the green suite asserted nothing about the claim in the test's own name.

Disclosure: in the sabotage harness every arm also shows
`test_the_watcher_still_emits_every_field_this_tool_reads` red, because that arm reads
the real watcher source and the harness runs from a bare temp directory. That red is
an artifact of the harness, not of the mutation.

## Preregistered falsifiers

1. If, after `systemctl --user restart hestia-watch-claude`, the journal shows more
   than 9 `RETRYING stale primer` fires before the first
   `[hestia-watch] ARTIFACT plugin=` line, my TTL-retirement count is wrong.
2. If an `ARTIFACT plugin=` line appears in this invocation (pid 1253) before the
   sweep ends, `announce_artifact` is reachable from the sweep and the whole
   mechanism claim is refuted.
3. If `process_vintage.py units` prints `STARVED` on a watcher whose journal contains
   a `DAEMON` or `ARTIFACT plugin=` line for the bound invocation, the discriminator
   is keying on sweep lines alone and is worthless.
