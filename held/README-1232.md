# held/: the governed half of PR #1232, NOT applied

This is the **whole gate half** of #1232, relative to `main`, kept as a plain patch file so that reviewers
see the exact bytes and a scratchpad wipe cannot lose them. **Nothing here is applied.** The files it
touches are the governance surface, so they land only through the gate's escalation channel after review.

| file | sha256 |
|---|---|
| `c36101e4fbe0e459c9de2584db08c4c7b841d29b6482b8b1293fe23855c868e3.patch` | `c36101e4fbe0e459c9de2584db08c4c7b841d29b6482b8b1293fe23855c868e3` (the proposal) |
| `lineage/01e68a1cd2d3f980021fd73c5d882697b8887b8ddab10380d5ab3b0dca3bae20.patch` | `01e68a1cd2d3f980021fd73c5d882697b8887b8ddab10380d5ab3b0dca3bae20`: the patch Codex reviewed in 17054 and kimi verified on 2026-10-07 (reference only, do not apply; its base is `d3c05006`) |
| `lineage/1232-01e68a1c-onto-main.diff` | 01e68a1c's sources against the same sources merged onto main (conflict resolutions plus main's drift) |
| `lineage/1232-narrowing.diff` | **exactly what dp's 2026-10-10 ruling changed** on top of that |

Each patch filename is its own sha256, so `sha256sum held/*.patch held/lineage/*.patch` verifies them.

## What changed in the branch, and why the gate half moved here

The branch used to carry two applied governed commits, `a589ed9` and `5ab5ee5` (dp approved them as
escalations `72761edd…` and `4dcc05f7…`), plus the held patch `01e68a1c`. Merging current main
conflicted in nine governed files (main's stage-C cutover #1231, #1274, #1248 and #1247 all touched
them). Resolving those conflicts in a worktree would mean writing governed paths there, so the merge
commit takes **main's bytes for every gate-side path**. Those are the governed patterns plus the shell
battery, which travels with the gate patch. The entire gate half (`a589ed9` + `5ab5ee5` + `01e68a1c`
+ the narrowing) now lives in this one patch against main. The merge itself was built with
`git merge-tree` and a scratch index. No conflict marker was ever written into a governed file.

## Provenance of 01e68a1c: RECOVERED, byte-exact (not rebuilt)

The scratchpad that held `scope-gap-01e68a1cd2d3f980.patch` (`scopestage/`) was wiped. Its bytes
were recovered from the authoring session's own record:

- The authoring subagent's transcript records every `Edit`/`Write` to the neutral working copies.
  There were about 150 edits and one Python rewrite, with no failed edits. It also records the
  extraction script, which seeded the copies from `23ea9324`, and `build_patch.py` itself.
- The recovery replayed those edits in order onto the seeded copies, rebuilt `build_patch.py` from
  its `Write` plus one `Edit`, and ran it against a detached `d3c05006`.
- The output was `scope-gap-01e68a1cd2d3f980.patch` at 174,459 bytes, sha256
  `01e68a1cd2d3f980021fd73c5d882697b8887b8ddab10380d5ab3b0dca3bae20`, which matches the pin. The
  sources half matched too (`75759e979d878fdc…`, 103,795 bytes).
- So `lineage/01e68a1c…patch` is the reviewed artifact, not a rebuild.

## The narrowing (dp's ruling, 2026-10-10: "narrow and land")

**Removed.** The output-model tables (`_VALUE_COMMANDS`, `_LISTER_COMMANDS`, `_LINE_FILTERS`,
`_expand_pipeline`) are gone, together with every model of what an expansion produces (`_expand_one`,
`_expand_word`, and the environment / loop-variable / `read` tracking). Four Codex rounds found the
same defect in new members of those tables, and the author's own probes widened the class: `date +/x`,
`seq -f`, `shuf -e`, `expr`, `wc` and `sha256sum` operand echo, `grep` / `sort` / `head FILE`, and
`find -printf` all print paths.

**Unenumerated.** Each of these makes a reach unenumerated wherever its value would be judged as a path:

- a command substitution or a process substitution;
- a variable, quoted or not, since a linear scan is not the shell's scoping;
- brace expansion;
- argv built from stdin (`xargs`, `parallel`);
- an expansion used as the program, or handed to a command in its environment;
- shell the lexer cannot read.

The core refuses such an act with #1274's sentinel, `hestia:unpriceable:unenumerated`, as its
`target`. The orchestrator then opens a scope request for **the act**: its "path" is the sentinel
plus the first 16 hex of the complete-act digest, so two acts are two requests. The daemon grants it
**once or not at all**, because a session or standing grant would need a path. The surfaces offer only
"this act once" (`once_only`). Budget overflow escalates the same way, with
`hestia:unpriceable:overflow`.

**Kept.** Literal path words are still judged like Read paths: absolute, `~` / `$HOME`, relative
against the cwd, and redirect targets. Globs are judged as their directory's subtree, and a `..` after
a glob is unenumerated. Arithmetic and `$?` `$#` `$$` `$!` `$-` become placeholders, since their
values cannot contain `/` or be `..`. Substitution bodies are still judged as commands.

**Also closed.** These turned up writing the battery first; the first five allowed on 01e68a1c too:

- a relative path after `cd` / `pushd` / `git|make|tar -C` is also judged under every literal target;
- `eval`, `watch`, `su|runuser|script|flock -c`, and `sh -c` anywhere in argv run their string as shell;
- an interpreter anywhere on a heredoc's consumer line makes the body code (kimi's F2 A04/A06);
- a command that reassigns HOME makes its home spellings unenumerated;
- dequoted substitution bodies are lifted with `quotes=False` (Codex 17054, P1-quote-context);
- the workspace path is normalised before comparison. A workspace spelled with `..` made an inside
  path look like a traversal out of it, and under a temp-root workspace it admitted the workspace's
  own ungranted repo. This was a 01e68a1c regression; main refused it. The staged contract run found it.

## Battery (written first)

Every Codex false-allow from the review rounds is a row: 16955/a589ed9, 17015, 17029a–f, 17054
(P1-quote-context and P1-output-model), the author's class probes (`seq -f`, `shuf -e`, `expr`,
`wc` / `sha256sum`, `grep` / `sort` / `head FILE`, `date +fmt`), and kimi's F2 A01–A08. Each row runs
through `command_scope_reach` and through `core.evaluate`.

| core | deny rows ALLOWED | request rows ALLOWED | deny rows refused (path / request) | allow rows allowed |
|---|---|---|---|---|
| 01e68a1c as reviewed | 14 | 25 | 121 (incl. 21 plain incomplete) | 57/57 |
| 01e68a1c merged onto main | 14 | 25 | 121 | 57/57 |
| **narrowed (this patch)** | **0** | **0** | **99 path / 36 request** | **57/57** |

The narrowed battery passes 671/671. A `request` row must be refused as the sentinel (a scope request),
and it must also be liftable by exactly a one-time approval of the act.

## What it costs (re-measured over the real corpus)

These figures come from the same methodology as the 2026-10-05 replay: every workspace repo counts as
granted, each seat keeps its home marker, and only the delta over main's core counts. "Request" means
the act gets a once-only scope request, which no standing grant can absorb.

**Same corpus as the 2026-10-05 run.** That is 33,054 commands from 2026-09-20 to 2026-10-05:
claude-code 24,536, codex 3,359, kimi-code 5,159. The reviewed core reproduces that run's numbers:
claude-code 2,726 refused, and 1,607 against 1,609 with grants.

| core | refused, no grants | refused, proposed grants | of which: path (a grant can answer) | of which: once-only request | of which: plain incomplete (dead end, no request) |
|---|---|---|---|---|---|
| 01e68a1c as reviewed | 3,415 (10.3%) | 1,607 (4.9%) | 783 | 0 | 820 |
| 01e68a1c merged onto main | 3,415 (10.3%) | 1,607 (4.9%) | 783 | 0 | 820 |
| **narrowed (this patch)** | **7,051 (21.3%)** | **5,660 (17.1%)** | 1,079 | **4,581** | 0 |

Per seat, narrowed with the proposed grants: claude-code 21.1% (was 5.8%), codex 1.1% (was 0.8%),
kimi-code 8.6% (was 2.9%).

**Full window, 2026-09-20 to 2026-10-10.** That is 53,502 commands; the narrowed run saw 53,590,
the difference being this session's own commands.

| core | refused, no grants | refused, proposed grants | once-only requests (with grants) |
|---|---|---|---|
| 01e68a1c as reviewed / merged onto main | 6,629 (12.4%) | 4,025 (7.5%) | 0 (2,865 plain incomplete) |
| **narrowed** | **13,316 (24.8%)** | **11,415 (21.3%)** | **9,727** |

**What the standing grants absorb.**

- On the reviewed core, the proposed grants (the PR body's DEPLOY STEP set) took 3,415 refusals down
  to 1,607, absorbing 53%.
- On the narrowed core they take 7,051 down to 5,660, only 20%. They still absorb 61% of the path
  refusals (2,773 down to 1,079), but nothing of the once-only requests, which no grant can name.
- With grants the once-only count rises slightly (4,278 to 4,581): a lifted path refusal unmasks the
  unenumerated part of the same command.

**What the once-only requests are made of.** Full window, with grants, 9,677 requests:

| share | cause |
|---|---|
| 45.0% | a variable assigned ONE LITERAL earlier in the same command (`S=/tmp/x; cat $S/y`) |
| 25.6% | a variable assigned an EXPANSION in the same command (`D=$(dirname $f); ls $D`) |
| 12.8% | a `for`-loop variable |
| 4.9% | a substitution's output used as a path |
| 4.4% | an expansion exported, or handed to a command in its environment |
| 1.4% | an expansion used as the program |
| 1.2% | a `read` variable |
| 1.1% | a process substitution |
| 0.8% | `xargs` / `parallel` |
| 0.8% | a home spelling after HOME is reassigned |
| 2.0% | other (positional parameters, `${…}`, brace expansion, unbalanced quotes) |

**An option for dp to rule on (MEASURED, NOT in this patch).** A literal-assignment rule would say:
`$N` resolves to its literal only when N is assigned exactly once in the command, as a top-level
statement entered from `;` / newline / start, ended by `;` / newline / `&&`, and N is never a
`for` / `read` / `export` / `unset` operand, with no `eval` / `source` / function definition in the
command. On the same corpus this takes the narrowed rate with grants from 17.1% to **11.8%** on the
2026-10-05 window, and from 21.3% to **15.6%** on the full window. Once-only requests fall from
4,581 to 2,831, and from 9,727 to 6,652. The narrowed battery stays green with it, except for the one
row it is meant to flip (`D=/tmp/x; cat $D/y`). dp's ruling excludes variable modelling, so this is
reported for a decision and not shipped. The scripts are in `held/measure-1232/`.

## How it was built and checked

- The governed sources were extracted read-only into neutral-named scratch copies and three-way merged
  there (`git merge-file`, base `23ea9324`). The two conflicts (mechanism: `tally_scope(deadline=)`;
  orchestrator: main's MCP-transport views) were resolved there, and the narrowing was edited there.
- The patch was emitted against this branch's HEAD by the recovered `build_patch.py` recipe. The
  hooks-gt half was computed with `tools/hooks_gt.py`'s own functions.
- `git apply --check` is clean on HEAD. Applied to a throwaway export of HEAD, every staged file
  comes out byte-identical and `tools/hooks_gt.py check` reports ok.
- Python tests ran with the patched modules supplied through `HESTIA_CONTRACT_OVERLAY` and a
  process-wide import overlay. The patch's own test files ran from their staged copies. Results: the CI Python set (153 files) plus the battery came out 150 pass / 4 fail in one run, and every failure is accounted for. The staged contract suite failed only on a repo path spelled with `..`. Main's own suite fails under that spelling too, and the narrowed suite passes 21 + shim parity 29×4 with the normalized path. That same spelling exposed the workspace-normalisation defect fixed above. `loader_binds_installed_engine_test` cannot run under a process-wide import overlay, because it poisons the installed core on purpose; under the per-test seam it passes. `last_words_test` (A7) and `shared_target_split_test` (it cannot locate the real cargo behind the shim) fail on main in this environment too. Also run: battery 671/671; `test_gate_core` all checks pass; `gate_holes_test` (gemini) passes on patched and on main modules (HOLE 3's command changed, see the PR); dashboard decide contract and operator-surfaces spec pass.
- The contract suite's real-daemon arm ran against an isolated daemon built from this branch, on
  :7799. The sentinel request opens through the real handler, and a re-issue finds it.

## Declared residuals (unchanged by this patch, stated so they are not rediscovered)

- Interpreter code that computes a path (`python3 -c "open(p)"` with `p` built at runtime) is judged
  only by its quoted absolute literals.
- A link that already exists inside a `path:`-granted tree keeps #953's allowance. A repo-name grant
  is lexical for Read and shell alike.
- A string that some other program runs as shell (`ssh host '…'`, a custom wrapper) is not followed.
  `sh -c` is followed anywhere in argv, and so are `eval`, `watch`, and `su` / `runuser` / `script` /
  `flock -c`.
- Over-judging, accepted as the narrow direction: a heredoc fed to a remote or container shell is
  judged locally, and `docker exec … sh -c '…'` paths are judged as host paths.
