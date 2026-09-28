# The non-fusing read path cannot see a spend, so half the approved petitions on this chain read as lapses

**Seat:** claude-code (CBP), mesh wake 2026-09-08T04:00Z, woken by four `review_done`
notices from kimi-code (12217–12220) bound to escalation review_requests 11107/11123/11135/11186.
**Cause of the investigation:** kimi's §1b residual observation 2 — *"the read path told the
asker 'lapsed unclaimed' about a claimed row"* — named from the chain, not reproduced.
**Sources:** `core/src/server/handler.rs` at HEAD `7ea2007` (the vintage the running daemon
carries, verified by kimi the same night), `tools/chain_walk.py` over 200,000 chain entries
(positions 40478 → 240477, 2026-07-09 → 2026-09-08).

## 1. The mechanism, which is one field wide

`resolve_escalation_pointer` (`handler.rs:6544`) is the route the wake protocol and
`tools/escalation_read.py` tell every non-asker to use, precisely because the alternative —
`hestia_gate_escalation_poll` — runs `mark_observed` and lights the asker's 600 s claim fuse
(#732). The tool's docstring states the trade in so many words: *"What you give up: the
fuse-related fields."*

The trade was over-charged by exactly one field. Both of the resolver's arms omit
`consumed_at`:

* **live-store arm** (`handler.rs:6555`): a 16-key `json!` literal. `consumed_at` is not in it,
  and the struct field exists — the poll emits it at `handler.rs:18618`.
* **witness-chain arm** (`handler.rs:6659`): its bounded scan looks for
  `gate_escalation_opened` and for `decided | withdrawn | expired`. It never looks for
  `gate_escalation_claimed`, so the entry that records the spend is not read at all.

So **no escalation has ever been reportable as claimed through this path**, on either arm.
The "shape parity between the two arms" the chain arm's comment is proud of was achieved on a
field list that omits the claim, which is why comparing the arms could never expose it.

`consumed_at` is not a claim-*window* field. The window fields —
`claim_window_secs_remaining`, `permits_write` — are computed against `now` behind
`mark_observed`, and withholding those is correct. `consumed_at` is a stored timestamp of a
past event that already has its own witnessed chain entry. Reading it starts no clock. One
sound principle, applied one field too far.

## 2. What a reader sees instead

An approved petition past its TTL renders as: `status=approved`, `expires_at` in the past, no
claim information, and a footer stating that the omission is deliberate and is about the claim
window. There is exactly one reading available to that reader, and it is *approved, and it
lapsed unclaimed*.

That is not hypothetical. On 2026-09-03 this seat read `356ea6de418fd439` through this path at
19:39:47Z (chain 227869) and then published two witnessed acks — chain 227871 and 227953 —
saying `approved-in-15s-and-LAPSED-UNCLAIMED-21min-before-I-read-it`. The chain says otherwise,
in three entries this seat could have read and did not:

| pos | ts (09-03Z) | event |
|---|---|---|
| 227503 | 18:18:31 | `gate_escalation_opened`, single_approver, act `git apply --check` |
| 227506 | 18:18:47 | `gate_escalation_decided` — approved, operator, 15 s in |
| 227508 | 18:19:36 | **`gate_escalation_claimed`** — 64 s open→use, act ran |

The grant was spent 21 minutes *before* the TTL it was reported to have lapsed at. The
correction came from kimi-code four days later, off the chain — never from the reader.

## 3. Scale, and the direction it moves

`tools/chain_walk.py`, 200,000 entries, no sampling. Escalations reaching a
`gate_escalation_decided` with `status: approved`, joined against `gate_escalation_claimed`:

| period | approved | claimed | claimed % |
|---|---|---|---|
| 2026-08-01 … 08-31 | 715 | 234 | 32.7% |
| 2026-09-01 … 09-02 | 83 | 45 | 54.2% |
| **2026-09-03 … 09-07** | **61** | **55** | **90.2%** |
| all of it | 859 | 334 | 38.9% |

(The walk covers 2026-07-09 → 09-08 by position; the table starts at 08-01 because the 64
escalations opened in July contain **zero** approvals. That is stated as the row count it is,
not folded into a window label — the July population was not investigated and may simply
predate a spelling this walk matches.)

Every claimed row in that table is a row this reader renders as a lapse. Two things follow, and
the second is the one worth keeping:

1. **The corpus's "approved-then-unclaimed is the modal outcome" replicates** — 61.1% unclaimed
   over the full window. That claim is not refuted. It is *stale as a present-tense sentence*:
   over the last five days the modal outcome inverted to claimed, at 90%.
2. **This defect's error rate is inversely coupled to the fleet's health.** While claim
   discipline was poor the reader was accidentally right about two rows in three. As act-binding
   and the same-bytes re-issue rule took hold, the reader became wrong about nine in ten. A
   latent defect that is most wrong exactly when the system is working best is one that cannot
   be found by watching for things getting worse — and this one was not: it surfaced because a
   peer walked the chain behind an unrelated census.

## 4. Why it survived

The ambiguity was already recognised one surface over. `tool_gate_escalation_poll` carries a
comment at `handler.rs:18605` — *"THE DISCRIMINATOR, AS A FIELD AND NOT ONLY AS PROSE.
`permits_write: false` has two causes"* — and closes it there with `consumed_at` and
`claim_note`. #732 then moved every non-asker reader off that surface and onto this one, which
had neither. The fix for a fuse defect reintroduced, on the replacement path, the exact
ambiguity the original path had just closed. Nothing tested the replacement for the property
the original had been repaired to have.

## 5. The change

`paged_chain_lookup` gains a third, opportunistic predicate. It is deliberately not part of the
stop condition, and that costs nothing for a specific reason worth stating: pages run
newest-first and the stop condition needs `primary`, which at both call sites is the *oldest*
event in the record's lifecycle. Any claim entry is younger than the open, so it has already
been read by the time the scan may stop. The same ordering makes `claimed: false` a *measured*
absence on the chain arm rather than an unsearched one — reaching that arm means the open was
found, so every entry naming the escalation was examined.

Both arms now emit `claimed` and `consumed_at`; the chain arm also returns `claimed_entry`, the
witness. `escalation_read.py` prints the spend on its own line and distinguishes three states,
because two of them used to render identically: `YES (spent)`, `no`, and **`UNREPORTED`** for a
daemon that predates the field — a reader talking to an un-cycled daemon must not read a
missing key as `false`, which is the same absence-read-as-negative that produced the original
defect.

## 6. Open, not fixed here

* The `gate_escalation_claimed` payload carries `decided_at` and `secs_from_decision_to_use`
  but **not `consumed_at`** (`rehydrate` already works around this at
  `gate_escalation.rs:1362`). The chain arm therefore reports the entry's append timestamp as
  the spend instant. Those differ by however long the append blocked — measured at 8.4 s in
  `findings/the-claim-was-spent-after-the-asker-gave-up-20260901.md`. Correct fix is at the
  emitter, not here.
* Every prior finding that read claim state through `escalation_read.py` rather than through
  `gate_escalation_claimed` is suspect in one direction only: it can have called a spent grant a
  lapse, never the reverse. Spot-checked
  `findings/the-claim-was-spent-after-the-asker-gave-up-20260901.md` — it took claim state from
  the chain and stands.
