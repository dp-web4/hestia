# One act, one ruling: coalesce a re-asked act into its pending petition (#668)

**Seat:** claude-code on CBP, mesh wake 2026-09-01 06:09Z (notice batch ffZlGh).
**Driver:** `tools/reopen_census.py` (public; imports `tools/chain_walk.py`). Chain walk
of 120,000 entries, 2026-08-02T10:08Z → 2026-09-01T06:33Z, ~1 ms/hop idle (265 s).

## The specimen that started it

Seven `disposition` notices woke this seat for petitions the OTHER claude-code session
(`host_session 888f190a…`, working in `/tmp/wt-collapse`) had auto-opened on refused writes.
Read through `resources/read` (no fuse), joined to the chain:

| id | opened | decided | claimed | act |
|---|---|---|---|---|
| 50f8d3a1 | 06:10:12 | 06:10:30 `y` | **06:11:17** | `cp … pre_tool_use.py` |
| 246836b2 | 06:10:16 | 06:10:36 `y` | — | shell loop over `/tmp/absent-shared-$$` |
| 8791447f | 06:11:09 | 06:11:27 `g` | — | 50f8's command `&& echo INSTALLED && git diff` |
| b72793a8 | 06:12:11 | 06:12:35 `k` | — | ci_discovery loop |
| 4ec27c68 | 06:19:28 | 06:33:13 `k` | **06:33:36** | `cp … pre_tool_use.py` |
| b4b410f1 | 06:19:37 | 06:33:27 `k` | — | **byte-identical to 4ec27c68**, 9 s later |
| c4284ca7 | 06:19:39 | 06:33:17 `k` | **06:33:37** | `cp … cross_harness_closure_test.py` |

Eight ids for five digests today (`decided_awaiting_claim` on the c428 open payload already
listed three of them). b4b410f1 is the clean case: same seat, same marker, same `act_digest`,
minted while 4ec27c68 was still **pending**, and the operator typed a keystroke for each.
Two rulings, one act, and the second ruling could never have been claimed once the first was
(single use).

## The population (re-grading #668 with the prior petition's STATE)

#668 measured 1.5 ids/act on 08-25..27 and proposed "de-duplicate by `act_digest` at open
time". Nobody built it. Before building it I asked what state the prior petition was in at
the moment of each re-open, because that decides which class a pending-only fold retires:

```
opened_with_digest 210 | distinct_acts 161 | ids_per_act 1.30 | reopens 49
prior PENDING                      25   <- retired by this PR
prior approved + SPENT  (<=600s)   11   <- a real second act; single-use says mint
prior approved + SPENT  (>600s)     6   <- same
prior approved, STALE   (>600s)     7   <- a legitimate new ask
prior approved, LIVE unspent        0   <- the claim door has NO leak
prior DENIED / EXPIRED-unruled      0
reopens per seat: claude-code 30, kimi-code 19; median gap to the prior ask 53 s
```

Two things fall out that the 1.5x number alone did not say:

1. **The retirable class is exactly the pending one, and it is 51% of re-opens.** Every
   other class is a second ask that *should* mint: the grant was spent, stale, or refused.
2. **Zero re-opens over a live unspent grant.** The obvious competing remedy — "coalesce
   into an approved-and-claimable twin too" — has no population. The claim door already
   routes a matching act to a live grant; there is nothing there to fix.

## What shipped

- `EscalationStore::open_or_coalesce` + `pending_twin`: same (plugin_id, marker,
  act_digest), `status_at(now) == Pending`, oldest wins so a chain of re-asks converges on
  ONE id. `open()` is untouched — still the pure mint every existing test pins.
- Both doors (`hestia_gate_escalation_open`, and the claim door the hook actually calls)
  witness **`gate_escalation_coalesced`** on the fold — carrying the digest, the door, and
  `secs_since_first_open` — and answer with the twin's id, `coalesced: true`, `invitations: []`.
  The response keeps every key a pre-#668 hook reads off a refusal (`escalation_id`,
  `permits_write:false`, `how_to_decide`, `retry_within_secs`, `expires_at`, `witnessEntryHash`).
- Governance ledger: the event is declared, projected as an annotation on the open row
  (`coalesced: N`), and adds **no row** — a second ledger row would re-create for the
  operator the inflation the fold removed. The drift guard covers it.
- Tool descriptions for both doors say what `coalesced: true` means.

Not shipped, said plainly: the claude-code hook still prints `ESCALATION <id> opened` on a
coalesced answer. Wording only — the id, the how-to-decide and the retry window are right —
and I do not edit this seat's own gate hook from inside its seat. A one-line branch on
`coalesced` in `_escalate_or_claim` is the follow-up.

## Verification

- 6 store tests, 1 handler test through the claim door, 1 ledger projection test, the
  existing declared-vs-projected drift guard: 9/9 green.
- **Sabotage:** `pending_twin(...).filter(|_| false)` turns the two tests that pin the fold
  RED (`a_second_ask_for_a_pending_act_is_the_first_ask`,
  `a_hook_that_retrips_on_a_pending_act_gets_the_same_id_and_no_second_open`) and leaves the
  four negative-case tests green — the guard is as strong as its domain and its domain is
  the fold.
- Full `cargo test --lib`: see the PR.

## Limits

- The digest is `sha256(act)` where the act is the seat hook's own composition of the
  refused command, capped per seat (220 / 400 chars — #627). Two different long commands
  that agree on their first 220 chars would fold on claude-code. That is #627's cap problem
  wearing a new hat, not a new defect; act-binding (#318) is the fix on both.
- A pending twin from a DIFFERENT session on the same seat folds too — the grant is
  per-seat, so the ask is per-seat. Whichever session re-issues the act first spends it.
- `MAX_PENDING` is checked in `open`, after the fold; a fold consumes no quota.

**Not in force until rebuilt + restarted** (running daemon: v0.0.4-559-gda0613b).
