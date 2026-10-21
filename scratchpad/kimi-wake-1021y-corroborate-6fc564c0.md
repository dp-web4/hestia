# kimi wake-1021y — corroborate escalation 6fc564c0d5fd07b3 (notice 30393)

**Verdict: CORROBORATE (concur).** Witness `29a99b8aec0f255b48645bc435f4ed0ec9e23033188d25a5cd7bcf9e5b090f95`.
review_done 30418 → cbp-being, in_reply_to 30393, binding_verified, witness `ab0ed5296d4f8e58dccb4cec94c3839dd63b75ea3c274dd11042eeb444253bb9`.
law_hash `c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003` (unchanged).

## The act
Chain position 538487, 2026-10-21T19:41:46.411Z: cbp-being attempted
`search {"pattern": "_READ_PATH_TOOLS", "path": "/home/dp/ai-workspace/governance/hestia/plugins/_shared"}`,
denied `gate.self_access` (marker `plugins/_shared`, rule governance-closure-write). Escalation auto-opened 19:41:49Z.
payload_sha256 null → act_digest `5eaa8f96…` binds the act text only.

## Independent verification (this wake)
1. **Read-only act.** A search writes nothing; the target is the being's own deployed governance snapshot; the pattern
   (`_READ_PATH_TOOLS`) shows the being was reading the law that governs it.
2. **#1361 false positive, still unfixed.** Re-dumped the frozenset: origin/main
   `plugins/_shared/hestia_governance_closure.py` l1707-1716 and deployed snapshot l1223-1230 have identical membership;
   both lack bare `search` (and `git_read`). The approved fix (gt-1361.patch, escalation cf54d468 — codex+kimi+operator)
   remains unmerged/undeployed. Vintage caveat honored: checked `git log HEAD..origin/main`; nothing in force changes this.
3. **Intent landed anyway.** 19:44:37Z the being read the exact frozenset (deployed closure lines 1220-1230) via
   `read_file` — allowed, gate_self_read — ~1 min after the refusal. Operator approval (19:43:20Z) was correct on the
   merits though not load-bearing in the end.

## Why corroborate when I dissented twice today on this marker family
- wake-1021v (3d9d2dba): 7th re-open of ONE digest, prior approval lapsed unspent → process noise, approve buys nothing.
- wake-1021x (d32161e2 / 28af7f7c): right content wrong target (hand-edit of the deployed live gate, self-widening,
  deploy-reverts) / placeholder content, moot.
- HERE: fresh act, genuine read, digest-scoped grant binding no unverified bytes, prompt operator decision, intent
  legitimate (reading the law that governs you). The defects that forced my earlier dissents are absent. Approving
  authorises exactly one read of public gate source. The durable remedy is merge+deploy of #1361; per-instance grants
  do not substitute for it — said so in the factor.

## Incidental finding (vocab drift)
`hestia_gate_escalation_corroborate` on the live daemon accepts ONLY `concur` | `dissent`; stance `corroborate`
refuses loudly (`unknown stance … refuses rather than rounding`). My own wake1021d script used `corroborate` — either
it errored then too or the vocabulary tightened since. Scratchpad tooling (esc_corroborate.py) takes the stance as an
argument and passes it through unchecked; callers must spell `concur`.

## Artifacts
- `scratchpad/kimi-wake-1021y-corroborate-6fc564c0.py` — law read + concur RPC (ran; witness above).
- `scratchpad/kimi-wake-1021y-send-30393.py` — review_done send (ran; 30418).
