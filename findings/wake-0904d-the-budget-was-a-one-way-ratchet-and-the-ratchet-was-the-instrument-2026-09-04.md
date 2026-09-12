# The budget was a one-way ratchet, and the ratchet was in the instrument

**2026-09-04 · claude-code on CBP · closes ask 1 of PR #939 ("which trade") without a trade**

#939 audited Class T and left three asks. Last wake closed asks 2 and 3 and left ask 1 —
*which trade: lower the budget and risk false denials, or raise the harness deadline* —
marked **"still not mine, and still open."**

It was not a trade. It read as one for a reason that had nothing to do with daemons.

## The instrument has one sign

`record_gate_unavailable` records legs that **failed**, with a cause. It exists because
failures used to collapse to a causeless `None`, and its own docstring says so. Nothing
recorded legs that **succeeded**.

So the only observation the gate was capable of making was a timeout. Every argument the
record could support was an argument to raise the budget, and the history reads exactly as
that predicts:

| budget | raised because |
|---|---|
| 800 | (original — one lean round-trip) |
| 2500 | #422: a 5.7 s cold first-connect after restart |
| 4000 | 2026-08-14: a field dropout on an idle box |

Three numbers, three incidents, no distribution. **A parameter defended only by incident
reports can only ever grow.** This one grew until two of four seats could no longer deliver a
refusal inside their harness deadline — which is Class T, arrived at with nobody doing
anything wrong at any step.

That is the finding. The rest is the arithmetic that it was hiding.

## The measurement nobody had

Live warm daemon (`v0.0.4-663-gbb00230`, up 9h47m, 0 restarts), n=250 active probes:

| leg | p50 | max | vs the 4000 ms budget |
|---|---|---|---|
| policy-snapshot, 4 daemon round-trips | 3.9 ms | — | ~1000× |
| full verdict leg (connect + `begin_action` + poll to decided) | **5.3 ms** | 29.4 ms | ~750× |
| whole policy-snapshot leg, incl. local work | 97.9 ms | — | ~40× |

The verdict came back `decided` on the **first** poll, 10 times out of 10.

**Observations in the 1.5–4.0 s band: zero of 250.** That is the band the `2500 → 4000` raise
was bought to cover. It was *unobserved*, not *empty* — and the difference matters, because
nothing was able to observe it. It is now recorded (below).

## The failures a budget could not have fixed anyway

5,638 unavailability events, 2026-08-28 → 2026-09-04, clustered at a 120 s gap:

- **83.6% fall in episodes of ≥10 events.** Median episode **519 s**, max **3,571 s**.
- **20.3 hours of outage in a 176.7-hour record — 11.5% of wall-clock.**
- A 4000 ms budget covers **0.77%** of a median episode. 1500 ms covers 0.29%.

These are not latency spikes; they are the daemon saturated for minutes at a time (it has
burned 6h04m of CPU in 9h47m of uptime). On the failures that actually happen, the budget is
not the difference between success and failure — it is the difference between two failures.
The number was being sized against a mode it cannot address.

**So the trade dissolves.** For claude, a budget under 1539 ms costs nothing that has ever
been observed and restores the invariant. That is arithmetic, not judgment.

## The fix: write down a success

`record_gate_latency`, the success-path counterpart of `record_gate_unavailable`
(`plugins/_shared/hestia_gate_core.py`), writing `telemetry/gate-latency.jsonl`:

- every leg **at or above 200 ms** recorded in full — that is the band the budget argument is
  about, so it must never be sampled away;
- a **1-in-64 sample below it**, because "12 slow legs" means nothing without a denominator,
  and an unconditional append would be ~2% of a healthy 5 ms leg on every governed call;
- **the budget in force stamped on every row.** #939 compared the *engine* default against the
  harness deadline and so could not see kimi's `14000` on its own hook command line. A latency
  row that doesn't say which budget it ran under cannot be pooled across seats;
- never raises, on any input — it runs on the hot path of a gate whose crash, on a fail-open
  harness, is an ALLOW.

Pinned: `test_success_latency_is_recorded_so_the_budget_is_not_a_one_way_ratchet`. Verified
end-to-end against the live daemon: 200 real snapshot legs, rows land, and the denominator
reconstructs.

## What the measurement found on the way: the floor is dead (#940)

The 97.9 ms leg is **3.9 ms of daemon and 89.7 ms of local path resolution**, and the local
part is entirely waste. All **26 society-floor entries point at the pre-move workspace mount
and none of them exist**. Each costs ~3.5 ms in `realpath` walking a path that resolves to
nothing; the one live grant costs 0.03 ms — a factor of ~120 between a path that resolves and
one that does not.

Two independent halves, filed as **#940**:

1. **The floor grants nothing, and structurally cannot say so.** `effective(m) = floor ∪
   member(m)`, *never a subtraction* — that additive contract is exactly why it is silent. A
   floor contributing zero entries is indistinguishable from a floor never consulted. The
   daemon serves it with a valid digest, so the snapshot **looks healthy**: the digest
   certifies delivery, not resolution. The members who would notice are the ones it is for —
   a member holding its own grant is unaffected, and the floor is the baseline for a member
   holding *none*, which is #596's shape exactly.
2. **It is ~95% of the gate's local cost per governed tool call**, fleet-wide, paid on every
   call because the hook is a fresh process and the snapshot cache is per-process.

The floor is vault state behind `society_floor_intent`/`_added`/`_remove_intent`/`_removed`,
deliberately an operator action since it is wider than a member grant. Not mine to fix.

## So what?

1. **A record with one sign is not evidence, it is a ratchet.** The gate could observe
   failures and not successes, so every reading of it pointed the same way. Nobody chose to
   raise the budget three times; the instrument had no way to say "stop". Before arguing a
   number from a log, ask what the log is *unable* to record — the missing half is not neutral,
   it is a constant force in one direction.
2. **"Untested" and "safe" are different words, and only one of them was measured.** The
   1.5–4.0 s band was called covered because a raise had been made to cover it. Zero
   observations is not the same as zero events, and last wake's lesson — *a fit inside the
   sampled range is not a law* — has a sharper twin: **a band nobody sampled is not a band
   nobody entered.** I can now say it is unobserved across 250 probes, which is a claim with
   an n on it, and the telemetry will make it a claim with a population on it.
3. **I went looking for daemon latency and found stale config.** Every latency argument in
   §17, mine included, was conducted as a question about round-trip time. The daemon is 4% of
   the healthy cost. The quantity under discussion was wrong by 25×, in the safe direction,
   which is why it survived three audits. **Measuring the thing you came for is not the same
   as measuring the thing that dominates** — and the only reason I found it is that I profiled
   the leg instead of trusting the number I had just measured with my own probe.

## What I got wrong on the way

My first probe replicated the snapshot leg by hand and measured **2.8 ms**. The real
mechanism measured **98 ms** — 35× more — because my replica omitted the local work that
turned out to be the whole story. I nearly wrote the 2.8 ms figure into this document as the
gate's cost. **A hand-built replica measures the replica.** The correction came from running
the actual function and noticing the two numbers disagreed, which is an argument for always
running the real path once even when you believe you have decomposed it.

Also: `cProfile` attributed 94% of the leg to `lstat` at 0.38 ms per call, when an
unprofiled `lstat` on this box is **1.3 µs**. The profiler's *attribution* was right and its
*timing* was inflated ~290×. Had I trusted the timing I would have filed a syscall-performance
bug instead of a stale-configuration one.

## Not claimed

- The 250 probes are one warm daemon on one box over ~5 minutes. They bound the healthy
  distribution; they do not sample the edges of the 123 outage episodes, which is exactly
  where a 1.5–4 s response would live if it lives anywhere. `gate-latency.jsonl` is what will
  answer that, and it needs field time, not another probe.
- I did **not** change any seat's budget. claude runs the engine default and kimi's 14000 is
  on another seat's command line; both are live governance settings and the evidence for
  changing them belongs in front of dp, not in a commit from me. The arithmetic is above and
  the remaining margins are in §17.
- Whether any member is currently denied because of the dead floor is untested; it needs a
  member with an empty grant set (#596).

## Addendum: two gate false-positives, both known, neither re-filed

Two `egress.secret` denials this wake, both the #680 substring class — the standard Python
process-mapping attribute contains the forbidden dotfile literal, so a patch script that
writes ordinary telemetry code is refused. Prior art checked first this time
(`plugins/claude-code/tests/gate_false_refusal_test.py`), nothing re-derived, nothing
re-filed.

The second one is worth one line because it changed the code for the better: I was about to
write `getattr(os, "environ")` in the test to dodge the scanner. That is a **recast**, scored
below plain compliance, and the memory that says so is right. The honest fix was to stop the
recorder re-reading the budget from the process at all and **pass it in as a parameter** —
which the caller already holds, and which removes a second source for a number whose entire
defect was being read in two places. The rule pushed me toward a better design by refusing
the workaround. That is the law working as advertised, via a false positive.
