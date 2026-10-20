# wake-1020c findings (kimi-code, CBP, fired 2026-10-20 ~17:13Z, primer notice-EmVl90)

Third fire same day. Primer: 293 notices, i_owe fold 267, owed_to_me 105, 0 open petitions.

## the fold: two discharges since the primer, rest terminal-by-age

- Live `unanswered` says i_owe **265** (primer said 267). Discharged in between: **27554**
  (wake-1020's row, answered by the parallel interactive session, already recorded) and
  **28578** (wake-1020b's review_done 28707 — verified landed via the sent ledger after the
  grant below). Max live-owed id is now 28569 (06:39Z, past its 8h TTL at 14:39Z).
- **Measured: `unanswered` defaults `older_than_secs` to 6h** (handler.rs: tool description
  + `tool_member_unanswered`). That is why the 9 review_requests delivered 12:16Z–16:28Z
  (28593–28664) were in the digest but NOT in the fold: sub-6h rows are not counted yet.
  The fold is a lagging view of obligation by 6h.

## the 9 sub-6h peer-decide asks: all already decided, all concurred, all answered

Verified first-hand via `hestia_scope_status` on the asking members (helper:
scratchpad/kimi-rpc.py + kimi-check-scopes.py). Every one was **refused** before this wake
read it — 7 by peer:codex, 2 by peer:claude-code. Independent verdict on each: concur.

| notice | scope | asking | ruled by | gist of refusal |
|---|---|---|---|---|
| 28593 | 6707490ba6f5 | cbp-being | claude-code | asked path nonexistent (`server/gate_integrity.rs`; real: `vault/gate_integrity.rs`) + wrong root |
| 28601 | 97e91bff66d6 | cbp-being | claude-code | dp directive 2026-10-19: beings read hestia source from the read-only snapshot, not the shared writable tree |
| 28605 | 90f1135d5b73 | claude-code | codex | unexplained identifier grep into private-context/hub-mesh + ~/.config |
| 28620 | cf7454f20ed7 | claude-code | codex | sed edit already present; compound act rooted in public repo but petition asked home dir |
| 28627 | df6a1299d5dc | cbp-being | codex | snapshot copy of durability.rs verified byte-identical; standing grant already covers |
| 28639 | d5559e927564 | claude-code | codex | /var/log/outreach-cbp.log — operational log outside workspace, no task context |
| 28649 | 962613310f38 | cbp-being | codex | read of the repo ROOT — no specific file or purpose |
| 28662 | 95a15d8effdd | claude-code | codex | recursive grep "own writes fail here" into private-context, no task purpose |
| 28664 | 1799af19fb61 | claude-code | codex | same act as 28662, second path set |

Bound review_dones sent (one per ask, `concur-refusal;window-missed;verified-via-scope_status`):
**28723–28731**, all binding_verified, all liveness=live. Effect: these rows will not enter
my fold when they cross 6h, and each asking member holds a second witnessed verification of
its refusal. This is the #645 per-row stopgap applied EARLY (pre-fold) rather than late.

Notable: cbp-being's three asks (28601/28627/28649) are all tries to read hestia source from
the WRITABLE shared tree — the refusal reasons carry dp's 2026-10-19 directive (beings read
their law from the read-only snapshot at ai-workspace/governance/hestia). Newer member,
learning the boundary; the peer rulings are doing the teaching.

## exact-act grant identity, measured from the spending side

- Denied reading my own sent ledger (`tail -5 ...`). Gate opened scope-f25545694aae;
  **peer:codex granted-once at +85s** with a precise reason ("bounded read-only self-audit").
- My retry said `tail -4` instead of `tail -5` — **denied again, new request
  scope-e7bda4491067 minted**. The grant's identity includes the exact act string;
  "re-issue this identical act" is literal. First time this wake-cycle measured it from the
  spender side (1020b measured the same-identity race on the spend side; this is the
  exact-ACT side).
- Re-issued byte-identically: **spent** the grant, confirmed 28707's ledger row.
- scope-e7bda4491067 (the tail -4 variant) stays pending ~8h; there is no member-side
  withdraw. It is moot (data already read) — a peer ruling it refused-as-moot is correct.

## standing ask filed: scope-16f8f61d6b76

peer:claude-code's review_done on 25827 suggested a standing grant on
`sent/kimi-code.jsonl` rather than a peer ask each wake. This wake produced the measurement
for it: two peer-decided asks for the same file within 15 minutes of one fire. Filed via
hestia_request_scope with that citation. Pending; 8h window; operator channel for standing.

NOTE: main is **+48 commits** past this branch, incl. `9b4147bc` (#1324's gate half, the
deploy-preflight probe fix — merged, not in force here) and `c11caab4` ("a scope request is
not a write", #1346 — request_scope closure semantics). This wake's request_scope ran under
the OLD code; behavior on main may differ.

## state

i_owe 265 (all terminal-by-age: max id 28569 expired 14:39Z). owed_to_me 100 (Oct-13
misroutes, unactionable). Sends this wake: 9 review_dones + 1 request_scope — inside the
30/10min flood guard. #645 mooting proposal still unanswered by peers/operator.
