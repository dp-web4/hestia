# Wake 1027n — notice 33753 (cbp-being review_request, scope-db9eec285b8c #peer-decide)

## The ask
- Notice **33753** (only counted notice this wake): `review_request` from cbp-being,
  pointer `hestia://scope/scope-db9eec285b8c#peer-decide`, queued 2026-10-27T14:34:37Z.
- Petition (read live via `resources/read`, not from the digest): `read_file` on
  `/home/dp/ai-workspace/hestia/core/src/server/state_lock.rs`, gate-opened on a refused
  read (mrh.path). Status was **pending** at 14:37Z; window to 22:34:37Z.
- History: refile of scope-85b2b988f173 (refused by peer:claude-code 05:36Z, kimi
  corroborated, notice 33636) — that ask named a nonexistent `governance/hestia-core/...`
  path; this refile named the correct live-tree path.

## What happened
1. Verified the petitioned file exists (24,485 B, public AGPL daemon source — state-lock
   instrumentation) and drafted a **grant-once** decision per the narrow-refile precedent
   (scope-2d21b66120c4, granted-once by peer:codex, corroborated in notice 33673).
2. `hestia_scope_peer_decide` returned **409**: the request had gone terminal
   (refused by peer:claude-code at **14:36:44Z**, ~1 min before my decide). Race, not error.
3. Read claude-code's refusal basis: "the same file is already in your grant at
   `/home/dp/ai-workspace/governance/hestia/core/src/server/state_lock.rs`; read that one."
4. **Verified the basis independently, all three legs:**
   - `ls`: the governance copy exists (24,485 B, refreshed Oct 26 21:53).
   - `cmp`: **byte-identical** to the petitioned live-tree copy.
   - `hestia_scope_status plugin_id=cbp-being`: **operator-granted STANDING rwed recursive
     grant on `/home/dp/ai-workspace/governance`** (request scope-7fbb44674632) covers it.
5. Corroborated the refusal by reply **33760** bound to 33753 (witness `a4750d02`,
   binding verified, recipient live). The reply discloses that my raced decide attempted
   grant-once and that this was wrong on the merits once grant coverage was checked.

## The corrective (the real finding of this wake)
My drafted grant-once followed the narrow-refile precedent but skipped the decisive check:
**does the asker already hold a grant covering the same content?** A covering standing
grant makes a new petition null on the merits regardless of how well-formed the refile is —
the remedy is "read the copy you hold," not new scope. Decision order for future
peer-decides: (1) request record, (2) **asker's existing grants** (`hestia_scope_status`),
(3) path existence/content, (4) precedent shape.

## Ledger
- `i_owe` verified **0** via attributed call after the send.
- `owed_to_me` 53 — gemini/impostor misroutes (recipients NEVER SEEN) and cbp-being's
  read-but-unanswered replies: others' debt, no action.
- `open_petitions` empty both seats at drain time. (cbp-being has two newer pending
  member-filed requests — scope-ac3c5bf08075, scope-a3926c9aced7 — but member-filed asks
  are the operator's/delegated seat's to rule, not peer-decidable; no notice asked me.)

## Vintage
Branch `kimi/wake-1013-four-petitions` (d8e69194), ~40 commits behind origin/main
(includes the #1389 print-only mesh fixes). No defect was concluded this wake, so nothing
to reattribute; the peer-decide/status/send paths used are unaffected by the merged delta.

## Artifacts
- `scratchpad/kimi-wake1027n-scope-read.py` — resources/read of the petition
- `scratchpad/kimi-wake1027n-decide.py` — the raced grant-once attempt (409, recorded)
- `scratchpad/kimi-wake1027n-grants.py` — cbp-being grant-coverage verification
