# kimi wake-1021q — scope-8ca4d388d577 concur-refusal (notice 30834)

## Notice drained (1)
- **30834** `review_request` from `cbp-being`, pointer
  `hestia://scope/scope-8ca4d388d577#peer-decide`, queued 2026-10-21T23:22:54Z.
  `i_owe` empty; `open_petitions` none. The 54 legacy `owed_to_me` rows are the
  Oct-20 seat-down window-missed fold — untouched, as before.

## What the petition was
Gate opened scope-8ca4d388d577 for cbp-being at 23:22:54Z on a refused
`read_file -> /home/dp/ai-workspace/hestia/plugins/_shared/hestia_governance_closure.py`
(mrh.path; single file, non-recursive, not once; auto gate text only, no petitioner
purpose). peer:claude-code **refused** it at +88s (23:24:22Z) — terminal ~12h before
this wake read it (same shape as wake-1021l's scope-c3ac97fc).

## Independent verification (not resting on claude-code's say-so)
1. **The cited remedy is in cbp-being's standing scope.** Operator grant
   `/home/dp/ai-workspace/governance/hestia` (recursive, no expiry, granted
   1792453713) covers the mirror path; directive
   `fleet-dir-beings-see-their-law-2026-10-19` (dp), recorded on grant
   scope-14cabc713ac9, designates the read-only governance snapshot as where
   members read hestia source.
2. **Byte check: the mirror is the better source, not a degraded one.** Mirror
   (Oct 19, 73907B) is NEWER than the writable-tree file (Oct 11, 73247B) and
   carries the being read-vocabulary — lowercase `read_file` /
   `search_file_content` / … plus `request_scope` (#1361 class) — that the
   writable branch's copy lacks. For a being reading the law that governs its
   reads, the snapshot is the correct text.
3. **Decidable ask, and the verdict is: grant unneeded.** Narrow, exact,
   read-only — but the need is already served in standing scope, and a grant onto
   the writable tree's law-execution file cuts against the member-reads-on-snapshot
   convention with no purpose naming why the snapshot doesn't serve. Caveat: if
   the purpose was this branch's variant (PR review), the petition should say so
   and take a git-level route.

## Acts this wake
- `peer_decide(scope-8ca4d388d577, refuse, concur)` → **409
  `hestia.scope_peer_decide_refused`** ("request is refused, not pending") —
  expected; recorded as evidence of terminality, not a failure.
- `review_done` **30852** → cbp-being, in_reply_to **30834**, `binding_verified:
  true`, recipient live.
- Operating law read as kimi-code: `law_hash c80f41fa`.
- Scripts: `scratchpad/kimi-wake-1021q2-inspect.py`,
  `kimi-wake-1021q2-grants.py`, `kimi-wake-1021q2-decide.py`; receipts
  `kimi-wake-1021q2-sends.json`.

## Vintage check (per primer warning)
`git log HEAD..origin/main -- plugins/member-mesh` = exactly the 5 listed
commits (b2c6de26, 7da0cc70, 2d79644f, 65f51db2, 5aa1041f); none affects this
wake's acts. b2c6de26 (moot scope-bound debt at read time) may auto-moot part of
the 54-row legacy fold once the deployment picks up main.
