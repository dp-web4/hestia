# The claim was spent after the asker gave up — a 1.5 s hook budget against a chain store that stalls 7 s every 21 s

**Seat:** claude-code (CBP), mesh wake 2026-09-01 15:39Z, on dispositions `f470e81a` (mine, known) and
`90e98698` (sibling `888f190a`, dp's interactive session). Records read via `tools/escalation_read.py`
(non-fusing), acts from the asker's own transcript, daemon side via `tools/chain_walk.py` (20,000
entries, 2026-08-27 → 09-01), stalls measured live with `tools/chain_store_stall_probe.py`.

## 1. What happened, to the second (UTC)

| when | act | hook told the asker | daemon did |
|---|---|---|---|
| 15:32:20 | `cp … pre_tool_use.new.py plugins/claude-code/hooks/… && echo LANDED` | `ESCALATION 90e98698 opened` | opened; `decided_awaiting_claim: []` (correct) |
| 15:33:39 | — | — | dp approved, reason `k` (78 s) |
| 15:41:02 | **same bytes** | **plain `deny [gate-self-access] … (WITNESS FAILED)`** at 15:41:05.8 — no escalation line, no word "timeout" | `consumed_at = 15:41:03`; `gate_escalation_claimed` appended **15:41:11.4** — 8.4 s after the consume, ~6 s after the hook had already answered |
| 15:41:11 | asker: *"First re-issue denied without claiming, as every time; second identical re-issue:"* | | |
| 15:41:14 | same bytes | `ESCALATION 72e951d5 opened` (0.8 s) | `90e98698` is spent, so a NEW petition; `decided_awaiting_claim: []` — truthfully: nothing spendable |
| 15:41:29 | — | — | dp approved again, `k` (15 s) |
| 15:41:51 | same bytes | `LANDED` | `72e951d5` claimed in 0.2 s |

Two operator keystrokes for one write. The second was spent on **transport**: the asker re-issued the
exact bytes (the rule I posted on PR #747 at 15:32:59Z, 38 s *after* this petition opened), the daemon
spent the grant, and the only surface that reports a spend — the RPC response — never reached the
hook. The chain now says `90e98698` was *claimed* (`secs_from_decision_to_use: 444`) for a write that
was refused; the write that happened rides `72e951d5`.

Same shape at 06:42Z: `f9a517d6` consumed → appended 6.7 s later; asker saw three plain denies in a
row (06:42:23, 06:43:07, 06:43:44), re-petitioned as `693218f7` at +39 s, dp pressed `k` again.

## 2. The mechanism — three parts, each already in the tree

1. **The daemon consumes before it can answer.** `tool_gate_escalation_claim` (`handler.rs`): `now` is
   stamped, the state lock is taken, `gate_escalations.claim()` sets `consumed_at`, *then*
   `s.append_chain("gate_escalation_claimed", …)` runs — and `append` takes the chain store's
   **write-connection mutex** (`storage/chain.rs`). A request whose client has already hung up is not
   cancelled; it completes and answers a closed socket.
2. **The hook gives the whole exchange 1.5 s.** `ESCALATION_RPC_TIMEOUT_S = 1.5` covers `initialize`,
   `initialized`, `hestia_connect` and the claim itself (four round trips). On timeout
   `request_self_write` returns `("unreachable", "no answer from the daemon (TimeoutError) -- refused")`
   and the call site does `debug_log(detail)` and renders the generic `deny_self_access` text. The
   asker never sees the word *timeout*; the only tell is `(WITNESS FAILED …)`, which means the separate
   witness call also got no answer — i.e. the daemon was stalled for *everything*.
3. **The chain store stalls, on its own, on a clock.** Measured unloaded (`chain_store_stall_probe.py`,
   90 s, 392 samples): `hestia_query_history(limit=1)` takes **~7 s every ~21 s** (12.7, 33.9, 55.4,
   76.7 s) plus **~0.7 s every ~2 s**. In the same seconds `hestia_gate_pending_escalations`
   (state lock, in-memory) answers in **0.00 s** (178 samples, max 0.00) and `GET /` in 10 ms. So it is
   neither the tokio runtime nor the state lock: it is the chain store's connection. `query_history`
   → `recent_chain` → `read_recent` → **`self.conn`**, the *write* connection; every read path except
   `scan_recent`/`tail_hash` shares that one std `Mutex` with `append`. During the 7 s the daemon burns
   ~0 CPU and reads ~0 bytes from disk; the other 14 s of each cycle it sits at 100 % of one core
   with `rchar` ≈ 120 MB/s (4.9 GB in 41 s — sixteen times the 306 MB `witness.db`, from page cache).
   The browser dashboard polls `/api/dashboard` every **2 s** (`REFRESH_MS = 2000`), each GET
   requests a projection (`scan_recent` ×2, 2,000 rows each, SQLCipher-decrypted) — coalesced, so it
   runs back-to-back forever while a tab is open. What idles for 7 s while holding the write
   connection is **not resolved** here (rusqlite 0.31 defaults `busy_timeout` to 5,000 ms; the stall
   is 6.8–7.5 s; no disk IO; hypothesis, untested: a busy-handler sleep on a WAL/shm lock). Under load
   the picture does not change shape, only frequency: drvfs `find` max 8.07 s, CPU×3 7.40 s, ext4
   `find` 6.80 s.

Put together: any claim RPC that lands inside a stall exceeds 1.5 s. If the stall bites *before* the
claim reaches the daemon, nothing is consumed and the next re-issue claims — the "first retry denies,
second claims" ritual the sibling has already normalised (its own words, 14:34:47Z and 15:41:11Z;
`cd8834ca` is that benign face: plain deny at 14:34:10, poll shows `consumed_at: null`, second
re-issue lands). If it bites *between* the consume and the response, the grant is spent and the
next re-issue mints a petition — the burn.

## 3. How often

- Chain, 38 `gate_escalation_claimed` rows (08-27 → 09-01): claim→append latency median **0.6 s**,
  **2 rows ≥ 2 s** (`f9a517d6` 6.7 s, `90e98698` 8.4 s) — and those are **exactly the two** whose
  digest was re-petitioned by the same session within 40 s. Instrument: `use_at = decided_at +
  secs_from_decision_to_use` vs the row's own chain timestamp; re-open = same `host_session_id`,
  same `sha256(stated_attempted_act)` (verified equal to `act_digest`), within 300 s.
- Asker side, sibling transcript, 159 escalations since 07-30: **7 approve→re-issue cycles hit a plain
  deny first, all since 08-31 18:38Z, none before.** 3 of the 7 opened a new petition on the next try.
- The investigator too: during this wake my own read-only `grep` was refused `no verdict [fail-closed]
  … cause=timeout` — same stall, ordinary policy path, 800 ms budget.

## 4. Why this is not the asker's fault and not the operator's

Mechanisms for approved-then-unclaimed so far: asker death (`946aab05`), text edit (`c9af97ae`), an
FP the asker declines to spend (`f470e81a`). This is a fourth: **the daemon spent it and told a closed
socket.** The asker did what the refusal, the PR comment and the memory all say — same bytes, same
marker, inside the window. The operator ruled twice on one act. The record shows a claimed row with no
consuming act and a second petition with `decided_awaiting_claim: []`, which is *true* and useless.

## 5. What would close it (not shipped here — a seat cannot deploy its own gate)

- **Daemon:** treat a claim as spent only when the response is written, or make the claim idempotent:
  a second claim for the same `(host_session_id, act_digest)` within N s of a consumed row that no
  `outcome` row has joined returns `claimed: true` again instead of opening a petition. Either way,
  stamp `consumed_at` inside the same critical section as the append.
- **Hook:** when the claim RPC times out, *say so*, and say the grant may already be spent — "re-issue
  the same bytes once before reading a new petition as the daemon's answer." Today `detail` goes to
  `debug_log` only.
- **Chain store:** reads on `read_conn`, not on the write connection; and a dashboard tab should not
  schedule a 2,000-row decrypting scan every 2 s.

## 6. Refuted / untested

- REFUTED: "the daemon was loaded by the co-seat" as the cause — stalls occur unloaded with the same
  ~7 s duration; load only changes how often a claim meets one. My `find` over `hestia/` at 15:41:00–19
  coincided with the burn but did not create the stall.
- REFUTED: drvfs/9P specifically — CPU-only and ext4 loads reproduce it.
- UNTESTED: that closing the dashboard tab ends the 21 s cycle (needs the operator); the identity of
  the 7 s idle holder of the write connection; whether kimi's 15 s hook clamp changes the face
  (it should convert burns into benign retries — kimi rows show no ≥2 s claims, n=12).
