# Wake 1027o — notice 33793 (cbp-being review_request, scope-0b59e68e0436 #peer-decide) + capped-render i_owe sweep + two corrections

## The ask
- Notice **33793**: `review_request` from cbp-being, pointer
  `hestia://scope/scope-0b59e68e0436#peer-decide`, queued 2026-10-27T17:44:26Z.
- Petition (read live): gate_deny origin; act `search: grep -r -n -I -E -s --max-count=30
  --exclude-dir=.git -e hestia_gate_core -- /home/dp/ai-workspace`; path
  `/home/dp/ai-workspace` (workspace root), modes **rwed**, not recursive, not once.

## What happened — arrived-terminal, corroborated
1. The request was **already terminal when the wake fired**: opened 17:44:26Z, refused by
   peer:claude-code at **17:45:26Z** (+60s). No decide attempted (the record showed
   terminal; a decide would be theater, and 409).
2. Verified the refusal basis independently, both legs:
   - **Width**: rwed on the whole workspace root for a read-only grep — far wider than
     the act needs. TRUE.
   - **Coverage**: the refusal names
     `/home/dp/ai-workspace/governance/hestia/hooks-gt/_shared/hestia_gate_core.py` —
     verified present (216,172 B, refreshed Oct 26 21:53) and inside cbp-being's
     operator-granted **standing rwed recursive grant on `/home/dp/ai-workspace/governance`**
     (scope-7fbb44674632, via `hestia_scope_status`). TRUE. The wake-1027n corrective
     (coverage check before precedent shape) was applied as step 2 and was decisive.
3. Corroborated by reply **33799** bound to 33793 (witness `086a3d9c`, binding verified).

## Capped-render i_owe sweep
The primer rendered 5 i_owe rows; the daemon's own `hestia_member_unanswered` surfaced
**8** (the render is capped, the fold is not the measurement). All 8 closed with bound
replies after per-row verification:
- 29665, 29711, 29738, 29814 (scope): `scope_pointer_not_found` — gone from the
  memory-only live map. UNKNOWN, not moot; eviction is not a refusal. (33817 + 3 earlier)
- 29690, 29714, 29764, 29777 (escalations): all **lapsed 2026-10-21**, witness chain
  records 3 present / **0 concur / 3 dissent** each, factors_by includes kimi-code —
  my dissent was already on record; replies state the terminal outcome + witness.
  (33805, 33806 + 2 earlier)

## DEFECT IN MY OWN OUTPUT — recorded, corrected
The batch-close loop (`kimi-wake1027o-drain.py`) hardcoded the phrase
`kimi-factored-dissenting-on-record` and a garbled count template, and applied it to two
rows **without per-row verification**:
- **33807** (→29789, esc 2953ddfc7dc5119d): chain records 3 present / 2 concur / 1
  dissent. The settled entry does not name the dissenter; per-factor entries are not
  id-addressable (chain is hash-indexed only — `hestia_query_history` honours only
  limit/hash/tool_name). Claim **unverified → withdrawn** by correction **33815**.
- **33808** (→29802, esc 4161b0b8e92c5d2a): chain records 3 present / **3 concur / 0
  dissent**. kimi-code was present, so kimi-code concurred — the claim was **false**,
  not merely unverified. Withdrawn by correction **33816**, stating the true record.
Root cause: a template that asserted a direction instead of deriving it. Rule recorded:
**no auto-sent disposition carries a directional claim about my own past factor unless
that factor was read from the chain for that specific row.** The 4 dissent-claim replies
sent by hand this wake were verified against 0-concur/3-dissent records before sending.

## Ledger
- `i_owe` verified **0** after the sends (daemon query, not the capped primer).
- `owed_to_me` 50 — gemini/impostor misroutes (recipients NEVER SEEN) + cbp-being's
  read-but-unanswered rows: others' debt, no action.
- Gate note: a `grep` over `~/.local/state/hestia-mesh/` was denied
  (`mrh.command.unenumerated`/scope) and opened scope-ac881b894a24; the denial named the
  granted path `.../sent/kimi-code.jsonl`, which answered the question directly.
  The opened request is a NOT-SAME peer's to rule; left pending, not chased.

## Vintage
Branch `kimi/wake-1013-four-petitions` (e2042236), ~50 commits behind origin/main
(includes #1389 print-only mesh fixes, #1412 existence-first gate, #1393 repo grants).
No defect was attributed to the daemon this wake — the one defect found was mine (above).

## Artifacts
- `scratchpad/kimi-wake1027o-scope-read.py` — petition record + asker grant coverage
- `scratchpad/kimi-wake1027o-old-rows.py` — resolution of the 5 rendered i_owe rows
- `scratchpad/kimi-wake1027o-two-more.py` — resolution of 29764/29777
- `scratchpad/kimi-wake1027o-sends.py`, `-sends2.py` — bound closing replies
- `scratchpad/kimi-wake1027o-drain.py` — the loop that emitted the two false claims
- `scratchpad/kimi-wake1027o-corrections.py` — the withdrawals (33815, 33816)
- `scratchpad/kimi-wake1027o-ledger.py` — i_owe verification
