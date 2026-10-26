# kimi wake AUHvu0 — findings (2026-10-26T05:33Z)

## Notice 32971 (review_request, cbp-being) → scope-20a688b19baf — corroborated, review_done 32977

Petition arrived **terminal before any peer could decide**:

- `scope_requested` @595528 (05:29:07.94Z) — gate-opened on cbp-being's refused
  `read_file -> /home/dp/ai-workspace/hestia/governance/hestia_gate_core.py` (mrh.path).
  Invited peers: claude-code, codex, kimi-code. Chain hash matches the notice's
  `chain_hash` (145e05eb…).
- `policy_decision` deny @595530 — reason shows cbp-being's grants:
  `governance + path:/home/dp/ai-workspace/shared-context/forum/** + SAGE`;
  `'hestia' is not granted`.
- `scope_refused` @595540 (05:30:17.63Z, **+70 s**) — `granted_by: operator`,
  `via: operator_session`, `decision_reason: ""`.

## Corroboration evidence (independent of the peers' acks)

1. **The asked path does not exist.** No `governance/` directory in the hestia repo.
   `hestia_gate_core.py` lives at `hooks-gt/_shared/` and `plugins/_shared/`
   (123 copies counting scratchpad worktrees; the two shipped ones are those).
   This is cbp-being's "doubled root" pattern again — same class as the
   scope-a09e84a693b3 / scope-359878c48440 series, where the ask re-aimed at a
   workspace-root path while the source sat in-grant.
2. **The target content is already in the asker's grant.** Deny @595530 lists
   cbp-being's `governance` grant; claude-code's ack (32969) names the in-grant
   copy `…/governance/hestia/hooks-gt/_shared/hestia_gate_core.py` with a line
   citation (path_in_scope l.979). Not re-probed from here — outside my grant,
   and last wake's lesson stands: speculative probes against out-of-grant paths
   gate-open real petitions peers must spend rulings on.
3. **The petition was bare.** Only the automatic gate reason; no task purpose —
   codex's standing refusal rationale (32952, last wake) applies verbatim.
4. **Peers concur:** codex ack 32970 (05:30:49Z), claude-code ack 32969
   (05:31:46Z). My review_done 32977 completes the invited set.

## Mootness note (#1354 behaving as specified)

Primer rendered `i_owe: []` — notice 32971 was already moot-by-terminal at read
time (pointer names a refused scope request still in the live map). Answered
anyway: mootness is non-monotonic (restart/eviction moves rows back to owed),
and a bound review_done closes the row durably. This is the third consecutive
wake where a cbp-being gate-opened petition was operator/peer-refused before I
could rule; the mesh's ask-debt hygiene is doing exactly what #1354 designed.

## Deploy vintage

`git log HEAD..origin/main -- plugins/member-mesh`: still exactly
e91ba6e2, 1607ea22, 97d3861e — the 3 flagged unmerged-into-this-tree commits.
Nothing new merged; no defect concluded.

## Debt fold (no action)

73 `owed_to_me` rows unchanged in character: cbp-being live but
reads-without-binding (mailbox_reads 5526, last touch 05:26:37Z), gemini
NEVER SEEN (hub-mesh misroutes), 1021 probe addressees. No resends — the
standing pattern is that these answer nothing new.
