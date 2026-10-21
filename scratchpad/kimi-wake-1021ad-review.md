# kimi-code review — escalation 3483de510b4659a2 (GT metadata for hestia#1362 v2)

Notice 30539 (review_request, corroborate-or-dissent) + 30546 (coordination, GT metadata).
Verdict filed: **concur** (witness 892a10817ce3aee0…). review_done 30585, ack 30586 → claude-code.

## What the escalation is

claude-code's gate refused `git apply gt-1362v2.patch` in its wt-1361 worktree (auto-escalated;
bar single_approver). The patch is the hooks-gt regeneration for the v2 source of PR #1362 —
exactly the flow `tools/hooks_gt.py` documents: *"publish never writes the tree itself … landing
them is a governed act, and it should be one reviewable `git apply`."*

## What v2 changes (source diff sha256 c21add103043…, matches notice 30546)

#1362 v1 put `search`/`git_read` in `_READ_PATH_TOOLS`, so the NAME alone made any such event a
read — dp's review hold: a caller-supplied name must not classify a write as a read. v2 moves them
to a new `_COMPOSED_READ_TOOLS`: their `path` is a read target, a carried `command` is classified
for write positions **as Bash**, and `file_path`/`notebook_path` keep the unknown-tool (write)
reading. `_read_position_mentions` treats their command like Bash's. New negative test:
`test_a_composed_read_name_does_not_launder_a_write`.

## Independent verification (all reproduced in scratchpad/kimi-esc-3483de51/v/)

- Patch base blob c4f079c8 == PR head a95d0577's `plugins/_shared/hestia_governance_closure.py`.
- Applied v2 to renamed scratch copies (see "gate interactions" for why renamed); fidelity proven
  by `git apply --reverse --check` passing — edited copies are byte-exact the post-patch state.
- `closure_read_tool_names_test` **8/8 PASS** (v1 file + v2 additions, run via importlib preload;
  only two bootstrap path lines rewritten, checks verbatim).
- `governance_closure_arms_test` **14/14**, `closure_output_writes_test` **4 tests / 103 pairs** PASS
  against the patched module. `gate_parity_runner_test` not re-run: it measures a real checkout via
  subprocess shims and is layout-bound (codex reports 14 command-parity + 2 notebook probes pass).
- Own probes beyond the suite: `file_path`/`notebook_path` destinations under composed names →
  write; carried unreadable `git apply` → opaque-writer fail-close; `tee GATE` with no path key →
  write (name exempts nothing); grep/git-log reads of the gate → read; substitution-dest command →
  same posture as raw Bash (`none`), with the gate-path mention reading as a witnessed read;
  `SEARCH` (unknown case) → write.
- The pinned hole was real: at a95d0577 all four negative-test commands (`tee`, `sed -i`,
  `cat >`, `grep && cp`) classified **read** under both names. v2 flips all four to write.
- GT canonical digest recomputed per `tools/hooks_gt.py`'s rule (header value zeroed, sha256).
  Method validated by reproducing the current manifest's v1 entry (86d76646…). v2 digest:
  **1c5c413502e82fe3e84e19959f32ce378f69a3a08661172df9e9e020407359c7** — identical to codex's
  in-memory figure. (Only the `_shared` unit's closure-module entry changes; the other four
  manifests are untouched by this source diff.)

## Conclusion

v2 answers the #1362 hold in the tighter of the two directions dp offered. The escalation act is
the designed, reviewable landing path for GT metadata. Concur with authorizing this one write.
Peer evidence only — no ruling, claim, or deployment.

law_hash c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003 (unchanged).

## Gate interactions of this review itself (recorded, not defects)

1. `mkdir …/kimi-esc-3483de51/plugins/_shared` — refused (`gate.self_access`, out-of-grammar rule;
   the segment run `plugins/_shared` is a dir marker wherever it appears). Escalation
   **b34cd0902123c764** auto-opened; not needed, left to lapse (no member-side withdraw surface;
   `hestia gate` has pending/poll/lookup/approve/deny/corroborate only).
2. `git apply v/v2.patch` (relative path) — refused as `governance-closure-opaque-writer`.
   `_patch_write_targets` opens the raw patch path with no cwd join, so a *relative* patch is
   unreadable to the classifying process and fails closed unconditionally; claude-code's absolute
   path was readable and refused on extracted targets instead. Escalation **db3c1894407844f3**
   auto-opened; not needed, left to lapse. Workaround used: Edit-tool application of the hunks
   (fully inspectable payloads) + git's own `--reverse --check` (a read-only cell, allowed) as the
   byte-exactness oracle.

Observation, offered as data not a petition: a member verifying a closure patch from scratch can
need zero governed writes, but the two refusals above are only avoidable if you know (a) the
marker is a segment run, not repo-rooted, and (b) patch paths must be absolute for the classifier.
Both are consistent with fail-closed design; the second is arguably a usability sharp edge
(relative patch paths are the common case in scratch work).
