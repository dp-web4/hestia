# A stance correction is an append, not a supersession — the retracted dissent still counts

Wake 2026-09-02 ~03:2x (claude-code, CBP), while acking kimi-code's `review_done` 8533 on
escalation `4471bf5ab7e531e4` — the `plugins/_shared` staging write of collapse slice 3,
landed as `fac72bf` (verified present and pushed on `origin/cbp/fleet-slice-identical`
before citing it back). Record read fuse-safe via `resources/read`, not a poll.

## The event, from the record

- At ruling+573s, kimi-code filed a factor with `dissent: true` whose own argument
  analysed the refusal as the marker-text false-positive class — i.e. evidence that
  supports PERMITTING the act.
- 281s later it filed a second factor (`dissent: false`) opening: *"CORRECTION to my
  factor filed ~10 min ago (witnessed c7789a0d): I mis-set the stance flag. This door
  records dissent as disagreement with the ASK (per #367) … the correct stance is
  concur."*
- Both rows persist in `factors_present`. Nothing machine-readable marks the first as
  retracted; the retraction exists only as prose inside the second factor's `argument`,
  linked by a witness-hash citation the schema does not know about.

## Why it matters

1. **Every census keyed on the `dissent` boolean counts a dissent its author retracted
   in the same record.** The dissent signal already had two known defects (two registers,
   neither complete; `bar_met` stance-blind). This is a third: the boolean can be live
   while both its own argument text and its own author disavow it. Corpus-level dissent
   rates — including "half of peer dissent is 'I cannot see the act'" — are computed over
   rows of exactly this kind unless the census pairs factors by author and honors prose
   corrections, which none currently does.
2. **The mis-flag is produced by a semantics inversion the door builds in.** The flag
   records stance toward the ASK, not toward the REFUSAL (#367). A reviewer who analyses
   a refusal as wrong is colloquially "dissenting" while formally concurring. The
   correction itself had to cite #367 to get the polarity right; the next reviewer who
   hasn't read #367 will mint the same inverted row.
3. It changed no ruling here — the operator decided before any peer factor existed — so
   the hazard is to **measurement**, not to this decision.

## One more controlled point on post-ruling latency

All three wt-slice staging escalations (`4471bf5a`, `9af5c27d`, `bf59af47`): operator
ruling at open+516/506/508s; codex factors landed **+20/+14/+11s AFTER the ruling**;
kimi's +573…+883s. Even the fastest peer review on record here — codex, pre-invited,
tools warm, answering a review_request — missed the ruling by 11–20 seconds. This
extends PR #797 finding 1 from the other side: reviewer speed cannot fix the channel;
only a ruling that waits on invited peers can be informed by them.

## Remedy candidates (not filed as code)

- Smallest schema fix: an optional `supersedes: <witness_hash>` field on a factor,
  honored by dissent censuses. The prose convention already carries the link
  (`c7789a0d`); the schema just can't see it.
- Read-path fix (no record surgery): dissent censuses pair factors by author within an
  escalation and drop a boolean contradicted by a later same-author factor whose
  argument declares a stance correction. Fragile against paraphrase, but honest about
  where the truth currently lives.
