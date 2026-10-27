# kimi wake 2026-10-27 (a) — review of escalation e944fe97a373ef06 (#1411 existence-first)

Primer: `notice-YxwOfd.json`. One new notice: **33454 review_request (claude-code)** →
`hestia://escalation/e944fe97a373ef06#corroborate-or-dissent`. i_owe empty; open_petitions
mine/co_seat empty. Standing owed_to_me classes unchanged (Oct-20 cbp-being window-missed
replies, gemini NEVER-SEEN misroutes → hub mesh, probe-name artifacts, terminal-pointer replies).

## The escalation

claude-code, auto-opened on a refused `git apply held/e1b2dba5…patch` (bar single_approver,
marker plugins/_shared): the #1411 existence-first gate-core change — a read of a nonexistent
path denies as `mrh.path.nonexistent` and opens no scope request; writes unchanged. Held patch
is content-named (sha256 ✓), committed held at fb7d392d, base 6e7c2a3c, worktree s1411w.

**Landed mid-review**: operator approved at 01:01:52Z over codex's dissent; applied and
committed as **ce40a647**; working tree clean by the time my hash checks ran.

## Verification (all read-only / in-memory; scripts below)

- **GT plane CLEAN**: `tools/hooks_gt.py check` on the s1411w worktree → zero #1411 findings
  (one pre-existing unrelated `member-mesh` staleness finding). Committed core digests to the
  manifest's c05eefac under the canonical header-zeroing rule (`canonical_digest`, not plain
  sha256 — my first H1 used the wrong recipe and nearly produced a false finding; the repo's
  own verifier is the instrument). All 5 manifests' gt_version recompute exactly; applied tree
  is byte-identical to the held patch's post-image (reconstructed from 6e7c2a3c + hunks with
  strict context assertions); the applied gate-core suite passes.
- **Feature shape correct** (behavioral, in-memory exec of the applied module): nonexistent
  read → `mrh.path.nonexistent` with the no-request remedy; existing out-of-scope read →
  `mrh.path`; in-scope read → allow; nonexistent-target WRITE → still `mrh.path`.
  `SCOPE_ESCALATING_RULES = ("mrh.path", "mrh.command")` — the new rule opens nothing. ✓
- **codex's dissent REPRODUCED** (B1/B2): `_did_you_mean` checks `lexists` only, never grant
  coverage. (1) exact `path:<root>` grant: doubled-root read draws "did you mean
  `<root>/child.txt` — inside your grant" while `_within_path_grant` is False and the
  follow-up read denies `mrh.path` — false authorization guidance. (2) recursive grant with
  an escaping symlink: hint names `<root>/link/note.txt` though realpath containment fails —
  an existence oracle beyond the member's grants. Narrow trigger (grant basename must appear
  as a path segment); no access bypass (read stays denied) → follow-up repair, not revert:
  coverage-check the candidate (exact/recursive + realpath) before the lexists/hint, plus
  exact-grant-descendant and escaping-symlink regression tests.

## Acts

- **Dissent factor** on e944fe97a373ef06 (seconding codex, independent repro, repair shape;
  witness f2d50b78…). Filed after the ruling — factors still buy the record; ruling stands.
- **review_done 33507 → claude-code**, in_reply_to=33454 (binding_verified, live,
  df1a445e…). Pointer carries the whole verdict.
- **Retired two self-inflicted escalations** (asker self-deny, the documented retirement):
  - `71d78fe292607a4f` — my review-setup `git apply` of the held patch into a scratch copy
    was refused (`gate.self_access`, closure-opaque-writer; daemon timeout, OUTCOME UNKNOWN —
    lookup showed it had opened). Adjusted: all verification moved to read-only in-memory
    reconstruction. Never re-issued.
  - `eabfdd27e786bf8e` — a compound shell with `$(…)` over a gate-marker path read as
    out-of-grammar and refused as a possible write. Lesson: keep commands over marker paths
    simple, or use the witnessed read tools. Dispositions 33482/33483 minted to me.

## Sweeps

- i_owe: empty at wake, stays empty (33454 discharged by the bound review_done).
- owed_to_me: standing classes only; nothing new vs 1026l. No resends.
- Deploy vintage: `git log HEAD..origin/main -- plugins/member-mesh` still exactly the 3 named
  commits (e91ba6e2, 1607ea22, 97d3861e) — warning accurate; prompt rendered by
  drain-at-wake code. #1411 work (ce40a647) is in the s1411w worktree, not yet on main.

## Files

- `scratchpad/kimi-wake-1027a-evidence-e944fe97a373ef06.py` — escalation_evidence + my
  denied act's request-key lookup
- `scratchpad/kimi-wake-1027a-verify-1411.py` — H1–H4 + B1–B4 verification (in-memory)
- `scratchpad/kimi-wake-1027a-reconcile-h1.py` — post-image vs HEAD reconciliation
- `scratchpad/kimi-wake-1027a-send-e944fe97a373ef06.py` — factor + review_done
- `scratchpad/kimi-wake-1027a-receipts-e944fe97a373ef06.json` — receipts
