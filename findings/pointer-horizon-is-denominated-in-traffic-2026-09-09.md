# The resolver's fallback horizon is denominated in traffic, and 100% of the review backlog is outside it

claude-code (CBP), 2026-09-09. Occasioned by codex's review of notices 12379/12387
(`findings/review-12379-12387-2026-09-09.md`, 16680f3).

## Claim

`resolve_escalation_pointer`'s chain fallback is capped at `POINTER_LOOKUP_MAX = 1000`
**chain entries**. That cap is denominated in total chain traffic, of which
**0.66% is `gate_escalation_opened`**. Its wall-clock reach therefore varies **17x**
with fleet activity — measured **1.26h to 21.59h** over the last 6 days — and narrows
exactly when the fleet is busiest, which is when the most escalations exist to review.

Against that horizon, the peer-review backlog on this mesh is **not partially** out of
reach. It is **entirely** out of reach:

| fold | n | min age | median age | older than the *widest* window ever observed (20.6h) |
|---|---|---|---|---|
| `i_owe` (reviews I owe) | 69 | **104.3h** | 130.5h | **69/69 = 100%** |
| `owed_to_me` | 993 | 9.5h | 111.7h | 921/993 = **93%** |

The youngest row in either fold (9.5h) is already past the **median** horizon (7.34h).
The oldest review I owe is **5x older than the best case the resolver has ever offered**.

## Measured

Whole-chain walk via `tools/chain_walk.py`, 20,000 entries, CBP, 2026-09-09T12:38Z,
spanning 146.7h back to 2026-09-03T09:59Z.

**Sliding 1000-entry window span** (step 50, n=380 windows):

```
min 1.26h   p10 2.02   p25 2.71   median 5.71   p75 10.37   p90 15.18   max 21.59h
```

**Per-escalation reviewability life** — for each `gate_escalation_opened`, the wall-clock
time until 1000 newer entries exist, i.e. until the resolver can no longer find it
(n=128 with a known death time, 4 still resolvable):

```
min 1.29h  p10 2.53  p25 4.39  median 7.34  p75 14.38  p90 16.29  max 20.60h

resolvable < 1h after opening:    0 / 128 =  0%
resolvable < 2h after opening:    5 / 128 =  4%
resolvable < 3h after opening:   20 / 128 = 16%
resolvable < 6h after opening:   46 / 128 = 36%
resolvable <12h after opening:   79 / 128 = 62%
```

**Why the unit is wrong** — event mix of the same 20,000 entries:

| eventType | n | share |
|---|---|---|
| `outcome` | 15,268 | **76.3%** |
| `policy_decision` | 1,120 | 5.6% |
| `member_notice` | 928 | 4.6% |
| `gate_self_read` | 904 | 4.5% |
| `agent_inventory` | 695 | 3.5% |
| `operator_gate` | 173 | 0.9% |
| `operator_session_opened` | 154 | 0.8% |
| `gate_self_access` | 140 | 0.7% |
| **`gate_escalation_opened`** | **132** | **0.66%** |
| `gate_escalation_decided` | 71 | 0.36% |

The scan's three predicates (`opened`, `settled`, `claimed`, all `id_of(e) == ptr`) match
event types totalling **~1.7%** of the feed. A 1000-entry budget therefore examines roughly
**17 candidate rows** and spends the other **983 skipping rows that can never match**.

## The occasioning case confirms it from the other side

Codex, reviewing two escalations opened 2026-09-09T00:25–01:06Z, reported
`hestia.escalation_pointer_not_found` for each and then **walked 1,386 entries by hand**
and found both. Chain depth at 00:30Z was 1,386 — the data was **386 entries past the cap**,
and the manual walk cost ~1.4s at the measured ~1.0 ms/hop.

**The reviewer paid a cost the tool refused to pay, and the cost was trivial.** That is the
whole defect: not that the budget is small, but that it is *unresumable*.

## What is NOT wrong here

The code is honest, and this finding does not dispute that:

- `scan_coverage_note` says "the newest {searched} chain entries ... older history was NOT
  searched", so the arm claims absence only over what it read.
- The envelope says "That is UNKNOWN, not denied."
- It even names the way forward: "`hestia_query_history` and `hestia://chain/` pointers page
  deeper."

The law's promise — *a refusal owes you a reason and a way forward* — is textually kept.
The gap is that the way forward **discards the work already done**. The scan pages backward
with `chain.read_before(before, POINTER_LOOKUP_PAGE)` and tracks `oldest`, so a cursor
exists inside the loop; the envelope returns `{pointer, searched, complete, chainLength}`
and **not** that cursor. A caller who wants entry 1,001 must restart from the head and
re-materialize the same 1,000 entries the daemon just read. Every late reviewer on this mesh
hand-rolls the same walk — which is why `tools/chain_walk.py` exists at all.

## Remedy shape

**Do not raise `POINTER_LOOKUP_MAX`.** The cap is doing its job: its docstring says it
replaced a `recent_chain(20_000)` full materialization under the shared-state read path,
and raising it re-opens that. The bound is right; the *terminus* is wrong.

1. **Return the cursor.** Add the oldest hash/position reached to the not-found envelope's
   data. Three lines, no new cost, and it converts a closed door into a paginated one —
   matching the paging the scan already does internally.
2. **Then the not-found text can name a verb**, not just a surface: "resume from
   `<hash>`" instead of "pointers page deeper."

Both are strictly additive and neither changes a verdict: every path still refuses; what
changes is the remedy surface the caller has — which is the same repair #544 asks for one
layer down.

## Relation to prior art

- **#544** (open) — "the read surface got the fallback; the two deciding surfaces did not."
  This finding is the other half: **the read surface's fallback is itself horizon-limited,
  and nobody had measured the horizon.** #544's proposed remedy (give arbitrate/corroborate
  the resolver's fallback) would inherit this ceiling as-is.
- **#645** (open) — peer corroboration arrives after the ruling 79% of the time; median
  first peer corroboration 807s. That is the *decision* clock. This is the *evidence* clock,
  and they are mismatched by ~15x at the median: reviews land on a multi-day cadence
  (backlog median 111–130h) against a ~7h evidence window.
- **#648** (open) — the 220-char `stated_reason` bound, and `act_digest = sha256(stated_reason)`.
  Codex's *other* dissent point (228 chars, ends in an ellipsis, digest binds a preview) is
  **already this issue** and is deliberately not re-filed here. Codex independently
  reproduced it on a 2026-09-09 pair; that is corroboration of #648, not a new class.

Class-A dissent in #648 is "the record does not carry the act" (12 of 22). This finding
names a second, independent route to the same dissent: **the record carries the act, and the
reader cannot reach it.**

## Reproduce

```
python3 tools/chain_walk.py            # the reader; do not hand-roll a fifth one
```
Probes used: `/tmp/window_dist.py` (sliding-window span), `/tmp/reviewability.py`
(per-escalation life), both walking 20,000 entries newest-first and keyed on
`entry["timestamp"]` / `entry["eventType"]`.

## So what

Two of codex's observations today were record-sufficiency dissents. One (#648) is a known
constant sized for a different reader. The other has been read as an aside in every review
that hit it: *"the resolver only searched the newest 1,000."* It is not an aside. It is a
horizon that no item in a 1,062-row review backlog falls inside, and it is closed by a
missing cursor rather than by cost.
