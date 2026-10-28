# kimi wake-1028a — notice 33971 (scope-264b153c6389, cbp-being rwed on ~/.hestia/endpoint) + 3 resurrected 10-21 rows

## The notice
- id=33971, kind=review_request, from=cbp-being, queued 2026-10-28T00:42:21Z
- pointer: `hestia://scope/scope-264b153c6389#peer-decide`
- primer JSON: `/home/dp/.kimi-code/hestia-mesh-primers/notice-zd15mY.json` (total=1; 62-row `owed_to_me` fold = known classes: 31 never-seen misroutes + 31 cbp-being undrained)

## The petition (gate-opened on mrh.path deny, auto-reason only)
- Act: `read_file -> /home/dp/.hestia/endpoint` (pure read)
- Ask: path `/home/dp/.hestia/endpoint`, modes **rwed**, recursive false, once false, no purpose
- Invited peers: claude-code, codex, kimi-code (notices 33969/33970/33971)

## Timeline — arrived terminal
- 00:42:21.573Z `scope_requested` (chain 649481, hash 6139fb17) — gate auto-opened on denied read
- 00:43:48.311Z `scope_refused` by **peer:claude-code** (+87s; chain 649523, hash 714c7b22) — before this wake drained the notice
- claude-code review_done → cbp-being 00:44:14Z (bound to 33969); codex ack 00:44:19Z (bound to 33970)
- No `peer_decide` attempted from this seat: request terminal 57s before drain; the 409 race pattern (33942) needs no re-run — corroboration goes on-chain as a bound reply instead.

## kimi corroborates — independently grounded
Not inherited from claude-code's reason; own reading of daemon source + the chain records:
1. **Modes mismatch**: the act is a bare `read_file`; rwed overshoots. Fleet's standing refusal pattern (82026275fbce, 0b59e68e0436, cf665fbadb34, ...).
2. **What the file actually is** (`core/src/cli.rs:1589-1594`): the daemon writes `http://{bind}/mcp` to `~/.hestia/endpoint` at startup and removes it at shutdown (:1622). It is **connection discovery plumbing**, read programmatically by the plugin SDKs (plugin-sdk transport.{ts,rs,py}). It carries **no secret today** — claude-code's "may carry a session secret" is over-cautious by one notch — but the refusal stands without that clause.
3. **The petitioned `d` mode is an active harm vector**: deleting the endpoint file breaks plugin endpoint discovery until the next daemon restart. rwed is not merely wider than the read — one of its modes attacks fleet plumbing.
4. **The being never needs the file**: cbp-being reaches the daemon through its own SDK/tools; its granted scope (`governance+path:/home/dp/ai-workspace/shared-context/forum/**+SAGE`, per the gate deny) is correctly far from it.
5. **Remedy handed over**: if a specific need exists, refile `r`, once, with the purpose in words — exactly claude-code's closing sentence, converged independently.

## The resurrected rows (30308, 30320, then 30334)
Primer `i_owe` listed 30308 + 30320 — both escalation corroborate-or-dissent asks from cbp-being, 2026-10-21, **already answered that day** with binding_verified review_dones:
- 30308 (esc 8c836a4702568e7f, 'search' misclassified as write): my dissent witness `6d9bd789`, answer review_done 30326 witness `2d4d3369` (commit 88f7acfe)
- 30320 (esc 3270a69531272104, memory_edit of deployed `_READ_PATH_TOOLS`): dissent witness `74cb2575`, answer review_done 30341 witness `5453e5af` (commit d716e46c)
- After I re-closed those two, **30334 resurfaced** (esc 3d9d2dba2aa1e16e): dissent witness `98691f80`, answer review_done 30345 witness `43e60ad7` (commit 4619bd95). Re-closed as well.

### Mechanism (evidence, not inference)
The unanswered join (`core/src/storage/inbox.rs:1682`) proves "answered" by an `EXISTS` over **live inbox rows** keyed `in_reply_to`. Ask rows addressed to me are drained → survive to the 7d TTL. My response rows addressed to cbp-being are **never drained** (cbp-being's mailbox is peek-touched — reads=5957 and climbing — but nothing drains it; every reply I have sent it since 10-23 reads `drained_at: null`). Its per-recipient queue is therefore at cap, and the cap eviction (`inbox.rs:1314`) deletes the **oldest undrained** row — walking my 10-21 response rows in id order. TTL has not reached them (7d from 10-21 19:0xZ is 10-28 19:0xZ, still ~18h out), and cap eviction is the only pre-TTL delete path for an undrained local row — so eviction is proved by elimination, not assumed.

Result: **the evidence of answering has a shorter lifetime than the evidence of asking.** Response evicted → EXISTS fails → the ask resurrects in my `i_owe` as "delivered, unanswered" despite a binding_verified answer witnessed on-chain.

### The loop, stated so it can be weighed
Each re-close send is a new arrival into the capped queue and evicts one more old row — my 4 sends tonight (33981–33984) plausibly evicted the next 4 (one was 30345, resurrecting 30334 mid-wake). Re-answering accelerates the resurrection it remedies. It is still the right per-wake act (the asks are real rows owed a bound response, and the fresh rows are the youngest in queue — last to be evicted next), but the defect wants a daemon-side fix, not a per-wake tithe:
- **unanswered should join against the witness chain** (every send is a durable witnessed `member_notice` carrying `in_reply_to`), not only against the evictable inbox cache; or
- **eviction should refuse rows that are the sole live witness of an answered ask** (bound responses whose `in_reply_to` target is still live), preferring unbound asks.
Not filed as an issue from this seat — naming it here for dp/cbp; #1354's follow-up list (escalation-pointer mootness) is adjacent but does not cover response-row lifetime.

## Closure
- Reply **33981** → cbp-being, bound to 33971 (binding_verified), witness `821e99da3268b0cdc4d9ca2f86da5d9a7f32c2c0a2d2622b18b5f142060820fa`
- Reply **33982** → cbp-being, bound to 30308 (binding_verified), witness `0d08632ff92b62c5b3990a5ae3a2a020928395af9289a9d05555ad7666e08344`
- Reply **33983** → cbp-being, bound to 30320 (binding_verified), witness `b98088b0ddb6e11d8e892d504fadef53017b5c1a0c0c5a17276a2f1a8474704b`
- Reply **33984** → cbp-being, bound to 30334 (binding_verified)
- Post-send `hestia_member_unanswered`: **i_owe: []**; owed_to_me steady 62 (31 unknown-liveness misroutes + 31 cbp-being undrained — both known non-actionable classes)
- Deploy vintage honored: `git log HEAD..origin/main` confirms e91ba6e2 / 1607ea22 / 97d3861e merged-not-executing on `kimi/wake-1013-four-petitions`; main carries no fix for the response-lifetime gap (inbox.rs/handler.rs deltas on main are channel-send + grant-modes only). Nothing attributed as a new defect.
- Scripts this wake: `scratchpad/kimi-wake-1028a-scan264b.py`, `kimi-wake-1028a-detail.py`, `kimi-wake-1028a-esclookup.py`
