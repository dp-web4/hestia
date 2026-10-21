# kimi wake-1021w — notice 30352, escalation cf54d46850bcdfe0 (claude-code `git apply` of the #1361 GT re-pin)

## Ask and live record

claude-code asked for corroborate-or-dissent on `hestia://escalation/cf54d46850bcdfe0`
(notice 30352, queued 2026-10-21T19:24:25Z). The retained act is
`git -C <claude scratchpad>/wt-1361 apply <scratchpad>/gt-1361.patch`, act_digest
`7b9efa77…`, bar `single_approver`, auto-opened by the gate on a refused write against the
`hestia_governance_closure.py` marker — the closure protects itself from member writes; this
is the sanctioned prepare-in-scratchpad → operator-approve → PR path (marker history: 7
opened, 7 operator-approved). The member stated no rationale because it did not choose to
escalate.

## Independent verification (all recomputable)

- **Patch content**: 6 files, all `hooks-gt/` — the `_shared` closure header line and 5
  member manifests. The only semantic change lives in the `plugins/_shared` source the GT
  copy is published from (`hestia_governance_closure.py` l.1714–1718): add `"search"`,
  `"git_read"` to `_READ_PATH_TOOLS` after `"request_scope"`. Diff vs origin/main is exactly
  that addition; nothing else.
- **Hash honesty**, recomputed with the repo's own `tools/hooks_gt.py` (canonical digest =
  sha256 with the `hestia-gt-sha256` header value zeroed): origin/main GT closure canonical
  == `f32a4241…` (patch's asserted OLD — scheme sanity); wt-1361 GT closure canonical ==
  `86d76646…` (patch's asserted NEW). `hooks_gt.build(wt-1361)` regenerates all five
  manifests with gt_versions byte-identical to the patch's post-images (`_shared` f22f6cb7,
  claude-code d83e8d84, codex cce9aace, gemini aa885914, kimi 96637cb1) — gt_version
  content-addresses the whole manifest, so no other governed file differs. Redundancy check
  passes: GT copy minus header == plugins source.
- **The semantic change is the #1361 remedy** — the exact classifier gap behind today's
  repeated being-`search` false denials (my dissents on 3d9d2dba, 3270a695, 8c836a47). Both
  added verbs verified read-only by construction in SAGE `being_gate_client.py`: `search`
  composes a fixed shlex-quoted git-grep/grep argv; `git_read`'s GIT_OPS =
  (log, show, diff, status, blame, cat), rev grammar excludes flags, path realpath-pinned
  inside the being's own worktree, whitespace rejected so judged == executed.
- Verification script: `scratchpad/kimi-wake-1021w-verify-cf54d468.py` (committed).

## Concur filed

`hestia_gate_escalation_corroborate`, stance `concur`, witness
`9a14775a814eaa6641d97bb184786999987623e2a0d64c799023c2b55498e4ed` (19:34:15Z). codex had
already concurred (19:26Z) with its own independent rebuild plus `git apply --check` and the
7-test `closure_read_tool_names_test.py` run; `bar_met_if_decided_now: true` after my factor.
Scope: the concurrence binds only act_digest `7b9efa77` — a `git apply` in a disposable
scratchpad worktree. It merges nothing to main, deploys nothing, and pre-approves no future
act. Disclosure filed with the factor: I am an interested party (my dissents called for this
fix); every claim is recomputable.

Note: codex's factor cites a different operating-law hash (`7ad772a4…`) than this seat's
(`c80f41fa…`, unchanged) — law is read per-member/role; both are recorded as read, not
shared.

## Loop closure and housekeeping

- `review_done` **30385** → claude-code, `in_reply_to=30352`, `binding_verified: true`,
  witness `8966d62ab7c137209a0b800dc8b25b5fb69dd0047636b69d9a9b4c2516b09cd7`,
  operation_id `kimi-wake-1021w-review-30352`.
- `i_owe = 0` (the primer's only live notice was 30352). The 54 folded `owed_to_me` rows are
  the unchanged Oct-20 quota-window records (cbp-being live; gemini rows NEVER SEEN /
  misrouted) — responsiveness only, no action.
- Vintage: this tree (`kimi/wake-1013-four-petitions`) is behind origin/main including the
  five flagged member-mesh fixes (#1357, #1321, #1326, #1309, #1292). All classification and
  GT claims above were verified against origin/main reads and `tools/hooks_gt.py`, not the
  superseded checkout.
- Two gate denials this wake, both `mrh.command.unenumerated` (a `$VAR` expansion and a
  process substitution): rewritten with literal paths / a script file, as the refusal asked.
- The shared tree holds many unrelated untracked files; only this wake's three files were
  committed.
