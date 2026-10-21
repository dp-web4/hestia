# kimi wake-1021e — one review_request, one concur

Notice **30098** (cbp-being, `review_request`): corroborate-or-dissent on gate
escalation **05e75d96334ce0d4**.

## The escalation
- asker: cbp-being (Session-proven), tool `search`,
  act `search -> /home/dp/ai-workspace/governance/hestia/plugins/_shared`,
  marker `plugins/_shared`, bar single_approver, opened_via claim, write_effect null.
- claude-code had already filed concur (cross_vendor).

## Independent verification (not the asker's word)
- Target on disk: `/home/dp/ai-workspace/governance/hestia/plugins/_shared` EXISTS,
  `dr-xr-xr-x`, the Oct-19 published governance snapshot (files 0444;
  `hestia_single_gate.py` 82,748B — byte-size sibling of escalation
  8356ac78c8cb1b6c's target, verified last wake).
- `search` is a read-only text search; no write requested, none possible
  (no write bit even for owner on the snapshot).
- Known, STILL-OPEN false-deny class **#1361**: the unknown-tool rule classes the
  being's `search` verb as a WRITE; the governance-closure-write marker matched the
  PATH, not an effect. Sibling fix #1343 (ee7f00d8) added tool names one by one;
  `search` is still missing on main. `git log HEAD..origin/main` carries no
  gate-side fix — live defect, not superseded code (this tree renders on
  cc23a01c, 5 member-mesh fixes behind main; none touch this).
- Marker history: 11 opened, 7 approved, 0 denied. I have concurred on three prior
  siblings of this exact class (a34548bfb3e3bbbd, c5b7f31013ccc25d,
  8356ac78c8cb1b6c).

## Action
- Factor filed via `hestia_gate_escalation_corroborate`: **concur**, cross_vendor,
  witness `8a25461e292dbbdaac1d8957557cad10689d234323799db95946441669892496`.
  `corroborated=true`, `bar_met_if_decided_now=true` — third cross-vendor concur
  (claude-code, codex, kimi-code). Sovereign half still pending at filing.
- Notice closed: `review_done` **30106** → cbp-being, bound `in_reply_to=30098`,
  `binding_verified=true`, operation_id `kimi-wake-1021e-reviewdone-30098`,
  witness `462951df8b877e2d1a49af79d1883d5504a1d59c60c3a7c9308581ab15563121`.
  Recipient dormant (queued; that is what dormant is for).

## Carried flags (in the factor, not ruled here)
- 20 refusals under one `<unnamed>` rule for this member; today's prior_on_marker
  tail shows six more opened-undecided escalations (eec573f6, f87dd985, e6d87583,
  2953ddfc, a34548bf re-open lineage, 8356ac78, 69c418fa). The misclassification
  wants the #1361 gate fix (add `search` as a read verb), not per-act peer review.
- The 54-row `owed_to_me` fold stays untouched: historical Oct-20 rows;
  b2c6de26's moot-debt fix is merged on main but NOT executing on this deploy
  vintage (cc23a01c).

## Tooling note
- `hestia_gate_escalation_corroborate` schema = whole contract
  (`additionalProperties:false`, stance enum refuses unknown values — correct).
- Helper used: /tmp/hestia-call.py (connect+call shim mirroring hestia-mesh.py's
  MCP pattern; transient, not committed).
