# PRD — trust lives in the vault as a situational cache

**Status**: proposed — dp-specified 2026-08-11, not yet implemented (a display stopgap ships ahead of it; see §6)
**Author**: claude-code (CBP), 2026-08-11
**Motivating observation**: a member idle two days (kimi-code) vanished from the dashboard trust box though its accumulated trust was intact on disk. Changing the range selector to "all time" changed nothing.
**Relates to**: `PRD_GOVERNANCE.md` §7 (the trust fold, evidence class), `PRD.md` §5.8 (trust & identity), `PRD_CONFIG_IN_VAULT.md` (vault as the authoritative owned store)

---

## 1. The problem

The displayed trust level is **re-derived from the chain on every dashboard poll**. Derivation
(`derive(plugin_id, role, window)`) reads a window of recent chain rows and folds the law over them.
That has two failures the kimi observation exposed:

1. **A member that stops acting falls out of the window and disappears.** The trust list is seeded
   from `active_entities`, built from `stats_window` — the last N rows of *all* event types, dominated
   by frequent outcomes, so it reaches back only an hour or two. A member idle for days is simply not
   in it, and its row vanishes — even though its grain, and everything the law ever derived about it,
   persists on disk. The range selector does not fix this because the trust list was never
   calendar-scoped; it was *window*-scoped.

2. **Derivation runs on a hot path it does not belong on.** `PRD.md` and the dashboard code already
   hold the ruling that *"the chain is sacred and full traversal stays available, but it is EXPENSIVE
   and should run only when context warrants."* Dashboard reads are "cheap, transient situational
   awareness." Re-folding the law every ~2s to paint a number that changed hours ago spends the
   expensive resource to serve the cheap consumer.

## 2. The principle (dp, 2026-08-11)

> The trust scores live in the vault. They are **updated in the vault as they evolve** and
> **retrieved from the vault for display**. The vault acts as a **situational cache**: any deliberate
> recompute updates the cache, and **until a recompute is triggered, the cache is the source of
> truth**.

Three moves, in one:

- **Persist** — the derived trust is written to the vault, not thrown away after painting one frame.
- **Serve from cache** — display reads the cached value. It issues **no chain read** for trust.
- **Recompute is a deliberate, triggered act** — derivation (the law-following fold) still produces
  the number, but on a trigger, not on a poll. Between triggers the cache is authoritative.

## 3. This does not weaken "the number is the one the law uses"

The standing ruling (dp, 2026-07-26: *"the measurements should follow the law"*, and the dashboard's
*"THE ROW'S NUMBER IS THE ONE THE LAW USES"*) said the displayed level must be the **derived** value —
never the self-reported lockstep scalar. The cache does not contradict that; it **moves when it is
computed, not what is computed**:

- The law still sets the number. It sets it **at recompute time**, from the chain, exactly as now.
- The cache persists and serves that law-derived number until the next recompute.
- What the cache must **not** hold is the legacy self-reported scalar. The cached value is the
  *derived* trust, carrying its provenance, so a reader can tell the law authored it and when.

The earlier ruling distrusted a stored number because the stored number was the wrong number (a
self-report). The fix then was "re-derive every time." The better fix, now that derivation is
correct, is "derive once per trigger and cache the correct number" — which keeps the law as author
and takes derivation off the hot path.

## 4. What the cache holds, and when it is written

**Holds** — per `(instance, role)` grain, enough that display needs no chain read:

- the derived **level** and the derived tensor dimensions the fold produces;
- **provenance**: `computed_at`, the **chain high-water position** the derivation folded up to, and
  the evidence counts behind it (so "is this stale, and against how much evidence?" is answerable);
- the alias fold result (`aliased_to`) resolved at recompute time.

**Written (the deliberate recompute) on** — the trigger set, stated so it can be reviewed and so
"why did this not update?" is answerable:

1. **A relevant chain event lands for the grain** — an outcome, an adjudication, a governance
   response, a scope act. Recompute *that grain* and update its cache row. This is the common path and
   keeps a live member's cache fresh within one event.
2. **An explicit operator recompute** — a dashboard/CLI "recompute trust" action, for one grain, one
   member, or the whole society. The manual override for "I don't trust the cache, refold now."
3. **(Optional) a staleness bound** — a maximum age after which a grain is recomputed on next access.
   Deferred until measured; the event-driven trigger (1) should keep live grains fresh without it, and
   an idle grain that never gets a new event is *correctly* frozen at its last law-derived value.

## 5. Falsifiable success criteria

Stated as predictions so they can fail:

1. A member idle for days (kimi-code) **shows its last law-derived level**, with **zero chain reads
   issued by the display path** for trust. Probe the read path directly — this is the assertion most
   likely to be quietly false if a fallback re-derives.
2. Between triggers, repeated polls return **byte-identical** cached trust for a grain — the display
   is a pure read.
3. A new adjudication for a grain **updates the cached level**, visible on the next poll, without an
   operator action.
4. An explicit operator recompute **changes the cache** iff the underlying evidence changed since
   `computed_at`; if nothing changed, it is a no-op that only advances the high-water mark.
5. Every cached row carries **provenance** (`computed_at`, high-water position); a reader can compute
   the grain's staleness without reading the chain.

## 6. The stopgap that ships ahead of this

Landed 2026-08-11 (`v0.0.4-29`): the dashboard trust list is seeded from the **persisted trust store**
for every registry harness, so an idle-but-known member (kimi) is surfaced with its most recent
standing and an "idle Nd/Nmo" marker. This is *reading persisted state instead of a volatile window*
— the same principle in miniature — but it is **not** the cache: the displayed **level is still
re-derived per poll** from `deriv_window` (the sparser derivation stream, which reaches back much
further, so the level is usually right for an idle member; if even that has aged out, the row is
`unmeasured` but still carries action_count and days_since_last). This PRD **replaces that seed with a
direct cache read** and takes derivation off the poll path. The stopgap is a bridge, and its removal
is part of this PRD's done-ness.

## 7. Open questions

- **"In the vault" — which store, exactly?** Trust is governance state, not a secret, and a separate
  encrypted `TrustStore` (`~/.hestia/trust`) already exists. "Lives in the vault" may mean *consolidate
  the trust cache into the authoritative vault* (one owned encrypted store, one authority, matching
  `PRD_CONFIG_IN_VAULT.md`'s direction) rather than a sidecar. Decide whether the cache is a vault
  entry class or the existing store relocated under the vault's key and lifecycle. The data-class
  difference (credential vs governance state) is a reason to keep them distinguishable *within* one
  authority, not necessarily a reason for two stores.
- **Incremental vs whole-society recompute.** Trigger (1) argues for per-grain incremental. A society
  refold (alias changes, law amendment) argues for a whole-society pass. Support both; name which
  trigger does which.
- **Bootstrap.** A fresh vault has an empty cache. First read: recompute-on-first-access (one
  expensive fold, then cached) or deny-until-warmed. Recompute-on-first-access is the honest default;
  it makes the first poll after a cold start slow, once.
- **Law amendment invalidates the cache.** When the derivation law changes, every cached value was
  computed under the old law. The high-water position does not capture that — a **law version** in the
  provenance, compared against the live law, is what makes a stale-by-law entry detectable and
  triggers a refold. This is the same shape as `PRD_GOVERNANCE.md`'s "shipped ≠ in force": a cache is
  only as current as the law it was folded under.
- **Reach to foreign members.** kimi and codex grains must cache and serve the same way; a cache that
  covers one member of four repeats the coverage asymmetry flagged elsewhere.
