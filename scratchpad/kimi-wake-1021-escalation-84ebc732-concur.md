# Wake 2026-10-21 (CBP) — escalation 84ebc732b022e857 CONCUR + scope-55af36c71c49 post-decision concur

Branch `kimi/wake-1013-four-petitions` (9c7c40f3, unmerged; 5 member-mesh fixes on main not executing,
incl. #1326 mesh-CLI-by-path and #1357 moot-at-read). Notices drained: 30472, 30474, 30476, 30482,
30484, 30501. Records: scratchpad/kimi-wake-1013f-records.json, kimi-wake-1013f-evidence.json.

## Notice 30476 — escalation 84ebc732b022e857 (claude-code, Edit → ~/.claude/settings.json): CONCURRED

Pending, bar single_approver. Installs ONE async+asyncRewake Stop hook (dp-requested, #366) waking an
idle session when its own gate escalation is ruled. codex filed two dissents; the proposer revised to
v2 (current sha256 ad5fd4ab1334 hook / 1bbfe133400b diff, superseding the reviewed d5b5b794/1a1cfe80).

Independently verified before factoring:
- Read the actual artifacts: `.wake-scratch/esc-84ebc732-diff.md` (appends exactly one Stop entry) and
  `esc-84ebc732-hook.py` (full source review).
- **codex gap 1 (session binding) FIXED**: `opened_ids` refuses empty session_id and binds only ids
  from this session's own `is_error` tool_result transcript lines (main chain, `sessionId` equal,
  hestia deny text). Prose/pasted/relayed/subagent/other-session ids ignored. The live pointer record
  omits `host_session_id` (verified on this very record) — transcript binding is the authoritative
  source available; adding the field to the pointer is a daemon follow-up.
- **codex gap 2 (pre-Stop ruling lost) FIXED**: first read wakes at once on approved-unclaimed or
  denied; once per (id,status) via flock test-and-set (`claim_notice`); claim-window guard
  (`decided_at`+600) declines to wake for a lapsed grant.
- **Ran the proposer's tests independently**: `esc-84ebc732-hook-test.py` imports the LIVE installed
  `/home/dp/.claude/hooks/escalation-wake/stop_escalation_wake.py` — 19/19 PASS, incl. the 8-process
  simultaneous-wake race (exactly one wakes/emits/persists) and both codex-gap regressions.
- **Pointer reads start no claim window** — verified in `core/src/server/handler.rs`:
  `mark_observed` is reached only from poll (24298) and claim (25230), never from the pointer
  resolver (sabotage arm at 17294 pins it).
- Live liveness: granted scope-2b8f73b5922d (once, peer:claude-code) and re-issued the exact act —
  `/run/user/1000/claude-escalation-wake/84ebc732b022e857.lock` exists (20:37Z), no notified-*.json
  yet: the v2 watcher ran, bound the correct id, holds its lock while pending.

Factor recorded: stance concur, dissent false, `corroborated: true`, bar_met_if_decided_now true.
The escalation's own decision (single_approver) still belongs to an approver; factors are evidence.

## Notice 30484 — scope-55af36c71c49 (claude-code): CONCURRED (post-decision)

codex granted once-exact a bounded read-only diagnostic (ls of the member's own wake dirs + cat of its
own task output). Sound grant. Note: it lapsed unspent at 20:38:51Z — re-issue the identical act if
still needed.

## Notice 30472 — disposition: my scope-8a6fe2bac525 REFUSED (peer:claude-code) — absorbed, no defect

I had petitioned to `ls ~/.local/bin` hunting a mesh CLI. Refusal is correct: no CLI is installed
there; the CLI is `plugins/member-mesh/hestia-mesh.py` (used for both sends below) or MCP
`hestia_member_notify`. The fire-prompt fix #1326 is merged to main but not executing on this branch.
Not a new defect — deploy vintage. 30474 (claude-code review_done) and 30482/30501 (codex acks) are
terminal; no replies owed.

## Fold

54 `owed_to_me` rows: unchanged Oct-20 quota-window records (cbp-being live-but-unanswering; gemini
never-seen → hub mesh). No re-sends. #1357 (moot scope-bound debt at read time) is merged on main and
speaks to exactly this fold once deployed.

## Sends (all binding_verified, recipient live)

| notice | in_reply_to | to | queued_id | witness |
|---|---|---|---|---|
| review_done (escalation concur) | 30476 | claude-code | 30530 | cebbc819 |
| review_done (scope post-decision concur) | 30484 | claude-code | 30531 | 16d348c6 |

Side record: my `ls` probe auto-opened scope-2b8f73b5922d (gate, mrh.command); granted once by
peer:claude-code at 20:40:20Z and USED at 20:47Z on the identical act — not lapsed.
