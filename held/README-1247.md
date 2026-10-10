# Held governed patch for #1247

`held/README.md`, `held/ca833c34…patch` and `held/lineage/{2e0547b5…,574426d6…,2e0547b5-to-ca833c34.diff}`
are #1239's. This file is #1247's.

This keeps the **governed half** of #1247 as ONE digest-named patch, so the reviewed bytes live in
the repo and not only in a scratch directory. The patch changes files the gate governs (the shared
closure, the common gate, the core's canonical list, their tests, and their published copies under
`hooks-gt/`), so it reaches any tree or INSTALLED copy only through the gate's escalation path, as
one `git apply`.

## Current: `88c5095c…`, re-stacked on #1274 (`716ae2d1`, #1239's clean replacement)

| file | sha256 |
|---|---|
| `88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb.patch` | `88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb` |

**Base: `716ae2d155e2e8625fb5b8e7c208871e659609c9`**, the head of #1274. #1274 replaces #1239,
which is closed. It is `c535619d` merged with main `ecd888f1`. `c535619d` is #1239 with its
Codex-cleared held patch `ca833c34…` applied (escalation `1617aee101fc9d1d`). #1247 was stacked
on #1239's older, regressed base (`574426d6…`, via `1d82846e`). This branch now merges
`716ae2d1` in (no force). Its governed tree is `c535619d`'s plus main's claude-code hooks change
(`disposition_deliver.py`, `hooks.json` and the claude-code manifest). This patch touches none of
the source files that change.

**This branch's governed tree is `716ae2d1`'s, byte for byte** (`plugins/` and `hooks-gt/` are
716ae2d1's tree objects). That changes the earlier arrangement, where the branch tree already
contained `e2b891c2…` (see the correction in History). Now **none** of #1247's governed delta is
in the tree, and `88c5095c…` applies to the branch head directly:

    git apply held/88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb.patch

That is the landing act, one gated write. Verify first: `sha256sum held/88c5095c*.patch` must
print the name.

**What it writes (14 files).** Sources: `plugins/_shared/{hestia_gate_core.py,
hestia_governance_closure.py, hestia_single_gate.py, seat_gate_boundary_test.py}`, plus two new
tests, `member_install_surface_test.py` and `registered_surface_test.py` (mode 100755). Published
copies: `hooks-gt/_shared/{hestia_gate_core.py, hestia_governance_closure.py,
hestia_single_gate.py}` and the five `manifest.json` (`_shared`, `claude-code`, `codex`,
`gemini`, `kimi`). It does not touch `hestia_gate_mechanism.py`, `claim_self_write_test.py` or
`hestia_governance_closure_test.py`. #1247's delta there was only `574426d6`'s, which
`ca833c34` supersedes.

Sha256 of each source after the patch:

| file | sha256 (prefix) |
|---|---|
| `hestia_gate_core.py` | `c3c15a04a5d1` |
| `hestia_governance_closure.py` | `93e894818aba` |
| `hestia_single_gate.py` | `84d5585a0ca1` |
| `member_install_surface_test.py` | `276604560f6e` |
| `registered_surface_test.py` | `3d3333b64fcd` (identical to the one Codex cleared in `01cf91e4`) |
| `seat_gate_boundary_test.py` | `d07ddbc4261f` |

The republished engine's canonical digest is
`10cd8ec2bca7db3e42269c1e74544ae4a526cb9c9aac07bd82049dd7b966502a`, and the shared `gt_version`
becomes `aa1def96f9a0cd00974663018357ab4658d41ce34d2da3db3ec3f26465d3a71e`. Each GT copy with its
header stripped equals its source.

### What the re-stack resolved

It was a three-way merge of the governed sources. Base `1d82846e` (old #1239). Ours is #1247 as
Codex cleared it: `18f91db` plus `01cf91e4`. Theirs is `c535619d` (#1274 changes none of these sources). Two files conflicted textually,
the closure and the common gate, and both conflicts were the same clash.

- **`ClosureVerdict.resolved` stays #1239's cleared TUPLE** of every other spelling the match
  consulted (`Closure.forms()[1:]`). #1247's single location, which #1247 had also called
  `resolved` (`Optional[str]`), is renamed **`landing`**. The two fields answer different
  questions: `resolved` lists the spellings, and `landing` names where the bytes go.
  `resolve_location` is unchanged (home-expanded, cwd-joined, realpath'd), and `landing` is still
  set on a `RULE_WRITE` verdict only. I renamed instead of deriving the location from the tuple
  because the tuple is empty for an absolute path, and it does not expand `~` in the cwd the way
  `resolve_location` does. Deriving it would have changed #1247's cleared semantics in edge cases.
- **A silent clash, not a textual one:** `_closure_verdict` passed `rv.resolved` to
  `_reaches_registered_entry`. Against the tuple, `isinstance(target, str)` is False, so the
  registered-entry marker would never have fired. It now reads `landing`.
- **`_closure_write_set` keeps `against` AND #1239's rules.** It still has the `against` closure
  argument, threaded through `write_verdicts(..., closure=against)`. Its targets follow #1239's
  order: resource, then each spelling in `resolved`, then `landing` only if that location is not
  already in the list. That keeps #1239's exact lists (`[alias, realpath]`,
  `[ordinary, gate]`, `[glob]`). Completeness is #1239's rule (in-grammar `RULE_WRITE`, target
  absolute or pinned by a spelling) AND #1247's (the `landing` is absolute). A set either rule
  calls incomplete rides the `unenumerated` sentinel. In practice the two rules agree. The
  conjunction just means neither cleared rule can be the weaker reading.
- `member_install_surface_test.py` reads `v.landing` where it read `v.resolved`. Nothing else in
  #1247's tests changed.
- The daemon side (`core/src/server/gate_escalation.rs`, not governed) merged with no conflict.
  #1239's two-tokenization change to the act-text loop in `markers_of`, which lets a bracket
  class survive whole, sits beside #1247's loop for location-qualified entries in act text. That
  loop still splits on `[`/`]`. `member_gate_entry_of` matches exact segments, so a bracket-class
  token could not match there in either tokenization. Glob entries are priced from the resolved
  targets (`member_gate_entries_matching`), which carry them.

### How it was built and checked

The patch was built read-only. It wrote no governed path (`docs/reviews/restack-1247-build/`
holds the scripts):

- `extract3.py` extracted base, ours (with `01cf91e4` applied in memory over `18f91db`'s blobs)
  and theirs under neutral names. `git merge-file` merged them, and `resolve.py` resolved the two
  conflicts with anchors asserted once each.
- `build_held.py` emitted the patch against a checkout of `716ae2d1` (verified), recomputed the
  hooks-gt half with `tools/hooks_gt.py`'s own functions, and checked it the way
  `hooks_gt.py check` does. It then re-applied the patch IN MEMORY over `716ae2d1`'s blobs and
  required byte-identical results for all 14 files.
- The merge commit was composed with plumbing in a scratch index (`make_merge.py`). Its tree is
  `git merge-tree`'s, except for two things. The governed subtrees are `716ae2d1`'s, which an
  assertion checks. And `held/` gains this patch and moves #1247's superseded patches to
  `held/lineage/`, as #1239 did with its own.

### Tests (2026-10-09, on my own worktree of this merge, `716ae2d1` + #1247)

The patched governed modules (core, closure, common gate) and patched tests were swapped in by
`run_one.py`. It sets `HESTIA_CONTRACT_OVERLAY` for subprocess fixtures and preloads the modules
for in-process importers, so no governed path was written. HOME and HESTIA_HOME were isolated,
and nothing touched the live daemon.

- **Python, 17 of 18 suites green:**
  - registered_surface: 9
  - member_install_surface: 9
  - seat_gate_boundary: 17 tests × 4 seats
  - claim_self_write: 45/45
  - governance_closure: 39
  - gate_core, gate_mechanism (30), cross_harness_closure (4/4), shim_structure (86/86), shell_grammar
  - sprintD (82), sprintE (9), sprintF (10)
  - one_gate_decide_contract: 19, plus shim parity 29×4
  - supersession_hard_stop, attempted_summary, hooks_gt_test

  Control: registered_surface and member_install_surface go red against the unpatched modules,
  with 8 and 7 failures.
- **`tools/governance_class_drift_test.py`: red on the branch as committed, by construction.** It
  parses the matcher from disk, and on this branch that is the unpatched core, so `<gate-alt-entry>`
  matches no governed name. With only the matcher read swapped for the patched core
  (`drift_probe.py`), it is green: "the matcher, the bar and the declaration agree", with all 13
  mutations RED as designed. It turns green on the branch when this patch lands.
- **Codex's earlier counterexamples (`probe_codex.py`), 20 of 20 pass:**
  - escaped brackets (`x\[ab]y*`, `x\[ab]efore_*`), `[^z]`, `[[:alpha:]]`, `[[=b=]]`;
  - relative, `cd`, dotdot, alias and summary-cut targets;
  - `$TARGET` and a relative target with no cwd are both incomplete;
  - `resolved` is the tuple, `landing` is the location, and the write set keeps #1239's order.
- **Rust, full suite (`cargo test -j2 --no-fail-fast -- --test-threads=2`, debug=0, private
  target dir, under the 3 s watchdog): 25 test binaries, 1302 passed, 0 failed, 2 ignored.** The
  lib suite alone is 1215 passed.
- **Real daemon (`tools/escalation_bar_real_daemon_test.py`), 4 of 4 PASS.** The daemon is built
  from this tree and runs isolated on 127.0.0.1:7797 with a throwaway home. The tests:
  - registered legacy entry: two factors, under the registered-entry marker;
  - wildcard and unresolved destinations, including caret negation and a POSIX class, with
    `zz_*` as the one-approver control;
  - every seat's own entry, relative, `cd` and summary-cut: two factors, with the location among
    the resolved targets;
  - a same-named file outside every location: one approver.

  The unpatched control arm fails all 4. That is a weak control: it fails on the missing
  seat-boundary helpers before any bar is read.

## History (before the re-stack on `716ae2d1`)

Everything below describes earlier states. The patches it names, `01cf91e4…`, `29ae13a6…`,
`fc95be2e…` and `e2b891c2…`, are now under `held/lineage/`, kept for reference. Do not apply
them. Their base (`18f91db` / `1d82846e`) carries `574426d6`, which `ca833c34` supersedes. The
"tree ALREADY CONTAINS `e2b891c2…`" correction that follows was true up to `0cac5783`. It is not
true after the re-stack, because the governed tree is now `716ae2d1`'s.

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
