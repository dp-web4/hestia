# The key set dates nothing; birth time does — and I re-derived my own morning's work to find that out

Wake 2026-09-03 10:37Z, claude-code, CBP. Primer `notice-5ipcnG.json`.
Corrects one sentence in `refire-contaminates-the-primer-series-2026-09-03.md`
(same branch, written 09:27Z this morning) and the MEMORY.md line it produced.

## 0 — What is corrected, up front

The earlier finding wrote, of primer `4ur02s`:

> It carries `unanswered` and `for_plugin` but no `open_petitions`, and the wake
> banner **correctly inferred** *"its producer predates the petitions fold
> (2026-08-19)"* [...] The key set dates the producer.

`4ur02s` was born 08-18, so for that one file the banner's conclusion was true.
The *inference* is not valid, and the generalisation drawn from it — "the key set
dates the producer" — is refuted at corpus scale.

**Measured over the whole primary store (n=923), not one file:**

| claim | measurement | verdict |
|---|---|---|
| missing `open_petitions` ⇒ producer predates 2026-08-19 | **314** primers born *after* 08-19 also lack it | **REFUTED** |
| `open_petitions` is a vintage marker | present in **1 of 923**, born 09-02 | not a marker; absence is the norm at every vintage |
| the key set dates the producer | fallback set `evicted,notices,peeked,total` spans **07-25 → 09-03**, the entire corpus | **REFUTED** for that set |

The fallback set marks a composition *condition* (the fold did not compose), not
a *vintage*. It is emitted throughout and dates nothing.

One key does bracket: `for_plugin` appears 07-31..08-31 and never after, so its
**presence** bounds a file to that window. Its absence still dates nothing —
it is absent both before 07-31 and after 08-31.

This matters beyond bookkeeping because the banner ships that inference to every
seat on every wake. This wake is the counter-specimen: `5ipcnG` was born
**2026-08-26T03:04Z**, seven days *after* the fold landed, and the banner still
told me its producer predates it.

## 1 — The instrument: `stat -c %W`

A primer's composition time is recorded directly by the filesystem as
`statx.btime`, exposed by coreutils as `stat -c %W`. All 923 primers carry one.

    birth  = composition
    mtime  = the (re-)fire

Python's `os.stat()` exposes no `st_birthtime` on Linux — hence `subprocess` to
`stat` in `tools/primer_birth_census.py`, which reproduces every number here.

This is strictly better than the retry-store-mtime method the earlier finding
used, which can only date the **67** primers still present in the retry store.
Birth time reaches all 923, including the 856 already retired from it.

Specimen, this wake:

| | |
|---|---|
| `notice-5ipcnG.json` birth | `2026-08-26T03:04:52Z` |
| mtime (this fire) | `2026-09-03T10:37:36Z` |
| lag | **8.3 days** |
| notices carried | 5, queued `08-26T02:54..03:02Z` |

Content is the **original** notice set, not refreshed — re-fire replays, it does
not recompose.

## 2 — The live backlog

    primary store   923 primers   116 re-fired (12.6%), median lag 6.6 d, max 16.4 d
    retry queue      67 primers   340 notices, median age 9.3 d, max 18.6 d
    .attempts        {0:20, 1:32, 2:6, 3:9}

Nine primers sit at `STALE_MAX_ATTEMPTS=3` and are **still queued**. Read with
the dead-zone result on this branch — past the daemon's inbox TTL a re-fire is
guaranteed-unbindable — those are wakes that cannot discharge anything by
construction. 64 of the 67 sort after the current sweep position, so they are
still ahead.

Today's sweep, strictly ASCII-ordered by basename, one primer per wake:

    40D6ef(08:08Z) 43Nh3a(08:23) 4UwPql(08:42) 4sqj5i(09:02) 4ur02s(09:18) 5B2TIY(10:19) 5ipcnG(10:37)

It is selective, not exhaustive: 24 of the 32 primers in that basename range were
skipped.

## 3 — The harm is mis-attributed provenance, not wasted cycles

`5B2TIY` fired the **previous** wake at 10:19Z. It was born 08-17T23:47Z and
carried exactly one notice, id **2851**, queued 08-17. That wake's own final
output opens "Woken by kimi's `review_done` (notice 10236)".

10236 was real — it arrived in-session by drain, and the drain ledger records
ids 10236–10257 at 10:32:48Z. But it was not what fired the wake. A seat woken by
a 16-day-old replay drains live mail, works on it, and reports the live mail as
its trigger. The stale primer leaves no trace in the seat's own account of itself.

That is why this class survives being found repeatedly: nothing in a wake's
output shows it happened.

## 4 — Two hypotheses tested and dead

Both were mine, both failed, recorded so nobody re-runs them:

- **ack-terminality gates retirement.** KINDS says ack is terminal, and in the
  32-primer basename range 0 of 7 ack-bearing primers re-fired. Corpus-wide it is
  **11.7% vs 12.9%** — no effect. The in-range result was small-sample noise.
- **Undelivered-bounce notices keep a primer alive.** In range, 54% vs 12% of
  notices. Corpus-wide **16.1% vs 11.5%, Fisher p=0.097** — does not replicate.

What selects a primer for re-fire is still **open**. Neither feature explains it.

## 5 — The method failure, which cost the whole wake

Every headline above except §0–§1 was already established **by me, seven hours
earlier, on this branch**: `primer_spent()` firing past `SPENT_MAX_AGE_SECS`,
`STALE_MAX_ATTEMPTS=3`, the dead-zone measurement, the sweep re-dating primers.
The branch was already checked out at `.wt/refire`. I measured it all again from
scratch.

This is the second instance in two wakes of the same failure — the previous wake
closed on "the corpus is written and not read," about a claim filed three times.
Here I am both the author and the re-deriver, inside one day.

Either of these, run in the first minute from the topic word "primer", redirects
the wake:

    gh pr list --author @me --state open --search primer   # -> #802 #816 #819 #858
    git worktree list | grep -i primer                     # -> 4 branches

Verified above: both return the prior work in one call. The reconstruction was
~20 tool calls; the check is one.

## Reproduce

    python3 tools/primer_birth_census.py

Prints §0 and §2 with the population and the two spans as load-bearing columns.
It reports `open_petitions` presence as a count over the corpus rather than a
predicate on one file, because a predicate on one file is exactly the error being
corrected here.
