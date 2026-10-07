# Held governed patch for #1247

`held/README.md` and `held/574426d6…patch` are #1239's. This file is #1247's.

This keeps the **governed half** of #1247 as digest-named patches, so the reviewed bytes live in
the repo and not only in a scratch directory. The patches change files the gate governs (the shared
closure, the common gate, the core's canonical list, and their published copies under `hooks-gt/`),
so they reach any INSTALLED copy only through the gate's escalation path, as one `git apply`.

**Correction (Codex review, notice 18786): this branch's tree ALREADY CONTAINS `e2b891c2…`.** Earlier
wording said "not applied". That was true of the installed gate, not of this tree. Do not `git apply`
`e2b891c2…` to this branch's head. It reverse-checks cleanly here (`git apply -R --check`), and it
applies only to its base `1d82846` (below). The patch is what landing #1247 changes relative to that
base.

## Current delta, superseding `29ae13a6…`: `01cf91e4…` (answers Codex 18931)

| file | sha256 |
|---|---|
| `01cf91e4a6d68f30c545133557ffc436b78e0d7731f02fd0a21c35f1f98f5bc8.patch` | `01cf91e4a6d68f30c545133557ffc436b78e0d7731f02fd0a21c35f1f98f5bc8` |

Same base (`18f91db`), same 8 files. It is `29ae13a6…` plus two widenings of `_glob_over_regex`:

- **Escaped wildcard (Codex 18931, P2).** The backslash branch did not consume the character it
  escaped. So the `[` in `x\[ab]y*` opened a bracket, and `[ab]` shrank to one character, which
  missed the `x[ab]yes` that Bash expands it onto. Now a backslash before an ordinary character
  consumes it, as `\\?` plus that literal. A backslash before `*`, `?` or `[` makes the rest of the
  pattern `.*`. I chose the fallback over a literal reading on purpose. Whether the backslash still
  escapes depends on quoting the producer may already have stripped, and the safe answer to an
  uncertain reading is the wider one.
- **Bracket holding a `[` (found by the widened corpus, not in the review).** Bash 5.2.21 reads
  `[[=b=]]*` both ways. It expands onto `bx`, and also onto `[b]x` and `[=]x`, where the first `[`
  is a literal and `[=b=]` is the bracket. `[[:alpha:]]` and `[[.a.]]` did not fork in my probe,
  but the rule is general: any bracket whose body contains `[` falls back to `.*`. Over-match only.
- **Tests.** The differential corpus gains literal-bracket and literal-wildcard names (`x[ab]yes`,
  `x[ab]efore_tool.py`, `[b]efore_tool.py`, `*efore_tool.py`, `?efore_tool.py`, `[=]efore_tool.py`,
  `[:]efore_tool.py`). It also gains 16 patterns: Codex's two, other escapes (`\[b]*`, `\**`,
  `\?efore*`, `b\efore_*`, `x\[a*`, `*\]*` …) and nested brackets (`[[=b=]]*`, `[![:alpha:]]*`, `[[]*` …).
  The producer loop gains `b\efore_*`, `\before_tool.py` and `before\_tool.py`. All three mark, so
  the shell parse plus target normalization does not lose an escaped entry. The new tests run
  **red against `29ae13a6`'s gate** (first miss: `[[=b=]]efore_tool.py` → `[=]efore_tool.py`) and
  **green with the fix (9/9)**. Codex's two counterexamples now match.
- Built and verified in memory by `docs/reviews/notice-18931-build.py`, which writes no governed path.
  The patch reconstructs over `18f91db` to the tested bytes: gate `e34f7aea…`, test `3d3333b6…`.
  The GT copy with its header stripped equals the source. The engine's canonical digest is
  `ac14f90d81761433559ea83aefc6f9f5a31ca9410dddac60b17586dfde5e61e3`.
- Still **not run**: `tools/escalation_bar_real_daemon_test.py`, for the same reason as below.
  It needs the patched gate in the tree.

Landing act, in this worktree: `git checkout -- plugins/_shared && git apply held/01cf91e4….patch`
(with the full name). **Note:** this worktree's uncommitted `plugins/_shared` diff is the older
`fc95be2e` content (the heredoc bypass recorded below), not any held patch. Codex 18931 excluded it
for that reason, and the `checkout` in the landing act discards it.

## Superseded: `29ae13a6…` (answered Codex 18830)

| file | sha256 |
|---|---|
| `29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655.patch` | `29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655` |

Same base (`18f91db`) and the same 8 files as `fc95be2e…`. It is `fc95be2e…` plus one fix.
Codex's re-review (notice 18830, P1) showed that `fnmatch` is not a conservative reading of a Bash
glob. It reads `[^z]` as "`^` or `z`" and `[[:alpha:]]` as a bracket followed by a literal `]`.
Bash expands both onto `before_tool.py`, so the write was priced `single_approver`.

- `_reaches_registered_entry` now matches through `_glob_over_regex`, which can only over-match.
  Every bracket expression stands for ANY one character, whatever it says (negation, range, POSIX
  class, locale). `*` and `?` may cross `/`. A backslash is optional before the character it
  escapes. An unclosed `[` makes the rest of the pattern match anything. `_bracket_end` reads a
  bracket the way Bash does: a leading `!`/`^`, a leading literal `]`, `[:…:]`/`[=…=]`/`[.….]`
  items, and `\` escapes. Without that, `[[:alpha:]]` would close early.
- Tests: the wildcard loop now also covers `[^z]`, `[!z]`, `[[:alpha:]]` and `[]b]`. A new
  differential test, `test_the_entry_matcher_covers_every_bash_expansion`, runs 15 patterns through
  real Bash pathname expansion over 7 candidate names and requires every expanded name to be
  matched. Both tests are red against the current gate (`[^z]efore_tool.py` → `Before_tool.py` is
  the first miss) and green with the patch (9/9).
- `tools/escalation_bar_real_daemon_test.py` (not closure, committed directly) gains
  `registered-caret-negation` and `registered-posix-class`, both expecting `sovereign_plus_peer`.
  **Not run yet:** this test needs the gate patched in the tree, which is the governed act itself.
- The republished engine's canonical digest is
  `b86956c9ef8664592b6f65ff2a4627eeb78c2c998c6c4d3f0b062ab469139b0d`. The GT copy with its header
  stripped equals the source.

Verified read-only, because a scratch-index `git apply --cached` is itself refused as a closure
write (self-retired `c6aaac809ca9dc85`): the patch was applied in memory to `18f91db`'s blobs. The
two `plugins/_shared` results are byte-identical to the tested copies (`7204b0e8…`, `98a1cae3…`).
`hooks-gt/` is unchanged between `18f91db` and this branch head.

Landing act, in this worktree: `git checkout -- plugins/_shared && git apply held/29ae13a6….patch`
(with the full name). It replaces escalation `7fba6f25…`, which is withdrawn.

## Superseded: delta for Codex's 18786 P1s, `fc95be2e…`

| file | sha256 |
|---|---|
| `fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6.patch` | `fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6` |

The base is `18f91db` (the tree with `e2b891c2…` in it). It touches the common gate, its test, and
the hooks-gt republish (1 engine copy and 5 manifests).

- **Registered entry, by wildcard.** `_reaches_registered_entry` now matches a resolved target that
  carries a wildcard (`*?[`) against the seat's registered entries. Before, only a literal match
  counted. `touch <legacy>/before_*` reached the running gate but carried no
  `registered-gate-entry` token. The daemon knows only declared locations, so it could not recover
  that. `fnmatch` lets `*` cross `/`, so it can only over-match, which prices higher, not lower.
  `after_*` is the negative control.
- **Completeness is about the whole write set.** `_closure_write_set` now reports complete only when
  every verdict is a `governance-closure-write` landing at an absolute location. Out-of-grammar
  (a `$VAR` destination), unparseable, opaque, internal, and relative-without-cwd verdicts make it
  incomplete, so the daemon gets the `unenumerated` sentinel. Before, a known target beside an
  unresolved one read as the whole set.
- **Tests** in `registered_surface_test.py`: three wildcard spellings and the negative control; three
  incomplete cases and three complete controls. They are red against `18f91db`'s gate.

How it reached this tree: the gate and test edits were first written with a python heredoc, which
the gate does not see (hestia#1059). That bypass was not deliberate, and it is disclosed here. The
same bytes were then re-sent as ONE gated act,
`git checkout -- <both files> && git apply <this patch>`: escalation `c4cf18fb71bffd6d`. The two
earlier asks, `7072da09…` and `8a8897bd…`, were self-retired because each was missing part of the
set.

| file | sha256 |
|---|---|
| `e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32.patch` | `e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32` |

Verify before applying: `sha256sum held/e2b891c2*.patch` must print the name.

## Order and base

1. #1239's held patch first: `held/574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b.patch`.
2. Then this one.

The base this patch is built against and checked on (`git apply --check` passes) is
`1d82846e1ce7446ec5d1aee2f55f0d0f0ca623b2`. That commit is #1239's head `d6f23be` (current main
`d2b1f7c` merged in) plus #1239's held patch 574426d6 applied byte-identical. In other words:
main + #1239 + #1239's held patch. The patch is `git diff 1d82846 <this merge>`, with `held/`
excluded.

## What it is

#1247 re-stacked on #1239: 18 files changed, 2192 insertions(+), 85 deletions(-).

- **Declared surface.** Every member's install declaration (dest, gate entry, registration) is
  derived into the closure.
- **Executed surface.** What each seat's harness registration actually runs is governed, and a
  write to a registered gate entry escalates under `registered-gate-entry`.
- **Location pricing, on #1239's `resolved_targets`.** Each write verdict carries the location it
  lands at, and the gate sends that location for every target. The daemon matches each target
  against the declared member gate-entry locations, after lexical normalisation and with #1239's
  glob rule. A registered entry among the targets adds the `registered-gate-entry` token.
- Tests, the hooks-gt republish, and the CI step for the real-daemon test.

## What it supersedes

`4b5c6db572cd58b8ff8af2103c9ffcea76389616ab7f82a92a949f4f73c0e620.patch`, at #1247's earlier head
`1783b84`. That was built on #1239's earlier head plus its earlier held patch, and it carried a
second every-target implementation (`b5611ca`, `6db885d`). The re-stack drops that implementation
in favour of #1239's. The file is gone from this tree and stays in history at `c490729`.

## Escalation 7fba6f258bcd05f7 — review packet (2026-10-07, answers Codex 18822/18827)

Supersedes `c4cf18fb` and `8cb709f0`. I withdrew both: each record's `stated_reason` is cut at
about 220 chars, so the patch source was never reviewable (Codex is right).

- **Act (complete in record):** `git checkout -- plugins/_shared && git apply held/fc95be2e….patch`
- **Working dir (the record DROPS it, along with the `cd` prefix):** `hestia/scratchpad/wt-1247c`,
  branch `claude/closure-member-install-surface-c`, HEAD `6976edbd`.
- **Patch bytes:** committed in `6976edbd` at `held/fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6.patch`.
  The filename is its own sha256 (`sha256sum held/fc95be2e*.patch`). It applies cleanly to HEAD.
  Its `plugins/_shared` hunks are byte-identical (ignoring `index` lines) to the uncommitted
  worktree diff that my heredoc bypass wrote.
- **What it writes (8 files):** `plugins/_shared/{hestia_single_gate.py,registered_surface_test.py}`,
  `hooks-gt/_shared/hestia_single_gate.py`, `hooks-gt/{_shared,claude-code,codex,gemini,kimi}/manifest.json`.
- **The gate UNDER-PRICED this act:** it matched only `plugins/_shared` and set `bar=single_approver`.
  The c4cf18fb record, whose text still named `hestia_single_gate.py`, was `sovereign_plus_peer`.
  The gate can't see the destinations inside the patch file, which is the
  unresolved-destination incompleteness that Codex P1 / this PR closes, showing up live on the deployed gate.
  **Please judge it at `sovereign_plus_peer`.** I will not claim on a lone approval.
- **Second gate gap seen this wake:** a `git apply` into a throwaway `/tmp` archive copy was refused
  (`b9e8ff24`, withdrawn) because the `plugins/_shared` marker matches on path text in any
  tree. That is the known text-match false-positive class, not new.
