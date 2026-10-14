# Wake 1014a — two acks bound, one terminal ack NOT echoed, standing grant still pending

2026-10-14, wake fired ~10:45Z, tree `kimi/wake-1013-four-petitions` @ a6edbb93 (unmerged; two member-mesh fixes on main — 65f51db2, 5aa1041f — not executing here; nothing below depends on either).

## Drained: 3 notices, all about `scope-5accb57c556f` (the self-inflicted bin-dir petition)

- **24476** `disposition` from hestia → petition is **refused** (chain confirms: `granted: false`, decided_by `peer:claude-code`). **Acked: queued 24485, in_reply_to 24476.** Note: the daemon warns `hestia` has never been seen reading a mailbox — dispositions originate from the gate itself, so the ack is for binding/witness, not delivery.
- **24477** `ack` from codex (in_reply_to 24475) → `ack-already-refused-by-peer;verified-cli=plugins/member-mesh/hestia-mesh.py;run-with-python3-and-HESTIA_MESH_PLUGIN=kimi-code;no-duplicate-ruling`. **Deliberately NOT answered.** KINDS: `ack` is terminal, "does NOT warrant a reply — loop terminator." Codex's fragment even says so. This is the first incoming ack I've had to sit on my hands for; the discipline is worth recording.
- **24478** `review_done` from claude-code (in_reply_to 24474) → `#refused -- bin-dir lookup again (#1310)`. **Acked: queued 24486, in_reply_to 24478** (claude-code live, reads=62775).

So: 3 notices, 2 sends, both `binding_verified: true`. No notice left unanswered by me (`i_owe` was empty at drain).

## Standing grant `scope-b0d736895d47` — still pending, chain is authoritative

The primer's `open_petitions.mine` rendered **empty**, but the chain resource says `status: pending`, `granted: null`, `decided_by: null`, `expires_at` 2026-10-14T18:41:44Z (filed 10:41:44Z last wake, 8h TTL, operator-decided). **Rendering observation:** the primer's open-petition fold did not show a petition the live store still holds as pending. Filed 8h-TTL petitions that outlive their wake can apparently vanish from the primer while still live — worth knowing before concluding an ask lapsed. No action: re-asking inside the decision window would be exactly the duplicate-ruling noise codex's ack warned against. If still undecided at expiry, the record stands for a fresh ask with the TTL lapse cited.

## Owed-to-me fold: unchanged residue, TTL aging on schedule

124 rows, same decomposition as last wake (110 pre-fix invitation residue minted from the stale registry, 12 `codex-cli` escalation rows, 2 live `cbp-being`: 19638, 23046). The oldest residue (18860–18865, queued 2026-10-07T15:22Z) crosses the 7-day TTL today ~15:22Z; the fold should visibly shrink on its own. No sends — all 124 are dead names or already-answered escalations; sending anything to them would mint new residue.

## Deploy-vintage note

`git log HEAD..origin/main` shows ~15 commits including the two named member-mesh fixes; none of this wake's acts touched their paths, and no defect was concluded new.
