# held/ — the governed half of #1248, NOT applied

`8a072b686a9dbb48552bdda5eb22507b70d05ef28e8d586037f9f81c1d515c1b.patch`

- sha256: `8a072b686a9dbb48552bdda5eb22507b70d05ef28e8d586037f9f81c1d515c1b`. The file name is its digest, so `sha256sum held/*.patch` proves it.
- Status: **held, not applied.** It touches governance markers (`plugins/*/hooks`, `hooks-gt`), so landing it is the operator's act: one reviewable `git apply` from the repo root.
- Codex cleared this exact digest on head `2e69ea9e` (PR comment, notice 17617). It supersedes `fbe9113c…`, the first cut, which lacked the standalone `agent_ok` test.
- Diffstat: 5 files, +166 −18.
  - `plugins/claude-code/hooks/disposition_deliver.py` (+49 −7)
  - `plugins/claude-code/hooks/hooks.json` (+32)
  - `hooks-gt/claude-code/hooks/disposition_deliver.py` (+50 −8)
  - `hooks-gt/claude-code/hooks/hooks.json` (+32)
  - `hooks-gt/claude-code/manifest.json` (+3 −3)
- Base: `f785001`. The merge of `origin/main` at `d2b1f7c` changed nothing under `plugins/claude-code` or `hooks-gt`, so the patch applies unchanged.

## What it does

- **Template.** Registers `disposition_deliver.py` on PreToolUse, PostToolUse and UserPromptSubmit, each with a 3 s timeout and `HESTIA_HOME=@HESTIA_HOME@`.
- **Reader.** Keeps one cursor per (session, agent). When a row carries a `for_agent` key, only the agent it names renders the row.
- **Ground truth.** Republishes `hooks-gt` with `tools/hooks_gt.py publish --emit-patch`.

## Why this file is committed

The scratchpad copy was lost overnight on 2026-10-07. The patch was then rebuilt byte-identically from the recorded edits. Committing it here means the held patch survives the box it was built on.

## After applying

`tools/register_members_test.py` (55/55) and `tools/disposition_subagent_delivery_test.py` (7/7) go green. Delete `held/` in the same commit that applies the patch.
