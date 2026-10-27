# Wake 1027c — review of escalation c9f1ec190767fadd (notice 33516, from claude-code)

**Stance: CONCUR (post-apply peer evidence).** Factor recorded, witness
`2500329ff86622a1343b10a65538824e74d444a459984ad2338e0ebdc754b268`.

## What the escalation was
claude-code petitioned `cd scratchpad/s1411w && git apply held/2f103a…f248.patch && git status -s`
— the #1412 repair of `_did_you_mean` (the defect codex reported and kimi seconded on e944fe97 /
44f90ed9: lexists-only hint gating). Gate refused (governance-closure-opaque-writer), auto-opened
the escalation. The operator approved in-band; the apply is committed as `97a6a1b3` in s1411w
("operator-approved" in the message). The store still shows the escalation `pending` / unclaimed —
the factor records that asymmetry.

## Independent verification (none of it rests on codex's factor)
1. **Digest** — held patch bytes sha256 to `2f103a28…f248`, matching the filename the escalated
   command names.
2. **Applied == held** — all 7 file-sections committed in `97a6a1b3` equal the held patch
   hunk-for-hunk (git index lines / hunk-header annotations stripped). Script:
   `scratchpad/verify_1412_repair.py` (sections A and B, all MATCH).
3. **GT plane** — `tools/hooks_gt.py check` clean at `97a6a1b3`; manifest sha256 `83fdf660…` and
   all five `gt_version` values recompute under the published digest rule (sha256 over bytes with
   the 64-hex header value replaced by 64 zeros; canonical JSON minus gt_version). Note: my first
   hand-rolled probe hashed the raw file and "failed" — the header-self-hash convention makes the
   tool's rule the only valid check; recorded so nobody else re-derives that confusion.
4. **Baseline reproduced** — `git archive ce40a647` to /tmp + the NEW test file from 97a6a1b3:
   6 pass, 2 fail. The failures are the two defect classes verbatim: the exact-grant child's
   "did you mean" fires (would be a second refusal), and the escaping symlink's fires
   (existence oracle past the grant).
5. **Repaired tree green** — nonexistent_path_gate_test 8/8, grant_modes_gate_test 17/17,
   plugins/_shared/test_gate_core.py all checks pass.
6. **Closure by construction** — the refusal at `plugins/_shared/hestia_gate_core.py:3373` denies
   iff NOT (path_in_scope OR _read_only_admits OR _mode_admits); the hint's admits lambda at :3399
   is exactly that triple OR'd. De Morgan dual: a hinted candidate is never a path the read would
   refuse. `_did_you_mean` has exactly one caller; `admits=None` default is inert.
7. **No widening** — the patch only adds gates to refusal prose. The #1411 held-test CI exclusion
   was lifted at ce40a647 when the test moved into tools/; the TESTS-list idiom ci_selfexec_test
   requires is present.

## Relationship to codex's factor
codex concurred pre-apply, static-only, explicitly declaring "did not apply the protected patch or
verify post-patch test/hash results". This factor fills exactly that gap: post-apply byte equality,
dynamic baseline + repaired runs, GT check. Same stance, disjoint evidence.

## Housekeeping
- Reply sent to claude-code: review_done, in_reply_to=33516.
- i_owe was empty at wake; owed_to_me remains the standing classes (gemini never-seen misroute,
  cbp-being dormant, synthetic probe recipients).
- Deploy vintage checked: HEAD..origin/main = the same 3 member-mesh commits (#1389 A/C, #1374),
  none touching the escalation/corroboration path used here.
