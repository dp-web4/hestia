# held/: the governed half of PR #1232, NOT applied

This is the **whole gate half** of #1232, relative to `main`, kept as a plain patch file so that reviewers
see the exact bytes and a scratchpad wipe cannot lose them. **Nothing here is applied.** The files it
touches are the governance surface, so they land only through the gate's escalation channel after review.

| file | sha256 |
|---|---|
| `28b79cccf49c9f37a27a6c95fb006a026d50251d583cd314c83a3aa849f5e241.patch` | `28b79cccf49c9f37a27a6c95fb006a026d50251d583cd314c83a3aa849f5e241` (the proposal; main `7e901d3c`, merge `3efae5d2`) |
| `lineage/f4a517554536adfeb64b76220a4af929ee50a2473d3b692f7f6312f867e2d4f2.patch` | `f4a517554536adfeb64b76220a4af929ee50a2473d3b692f7f6312f867e2d4f2`: after Codex 20554; Codex HOLD 20972 (IFS bound by `for`); reference only, superseded |
| `lineage/d10129c2c49be63e5aa941855a1c0e1026d47ed635c1667be93c3de78e7c9fe7.patch` | `d10129c2c49be63e5aa941855a1c0e1026d47ed635c1667be93c3de78e7c9fe7`: after Codex 20536; Codex HOLD 20554 (IFS, marker forgery); reference only, superseded |
| `lineage/f4644ef4f71a48cda62a546d5552f5e34063c43109e73aa71e3934d7ada699a0.patch` | `f4644ef4f71a48cda62a546d5552f5e34063c43109e73aa71e3934d7ada699a0`: the literal rule as first built; Codex HOLD 20536 (four P1s); reference only, superseded |
| `lineage/c36101e4fbe0e459c9de2584db08c4c7b841d29b6482b8b1293fe23855c868e3.patch` | `c36101e4fbe0e459c9de2584db08c4c7b841d29b6482b8b1293fe23855c868e3`: the previous proposal (narrowing without the literal rule, on main `d3c731fc`); reference only, superseded |
| `lineage/01e68a1cd2d3f980021fd73c5d882697b8887b8ddab10380d5ab3b0dca3bae20.patch` | `01e68a1cd2d3f980021fd73c5d882697b8887b8ddab10380d5ab3b0dca3bae20`: the patch Codex reviewed in 17054 and kimi verified on 2026-10-07 (reference only, do not apply; its base is `d3c05006`) |
| `lineage/1232-01e68a1c-onto-main.diff` | 01e68a1c's sources against the same sources merged onto main (conflict resolutions plus main's drift) |
| `lineage/1232-narrowing.diff` | **exactly what dp's 2026-10-10 ruling changed** on top of that |
| `lineage/1232-literal-rule.diff` | **exactly what dp's 2026-10-11 ruling added** (the single-literal-assignment rule), on the sources carried onto `7e901d3c` |
| `lineage/1232-codex-20536.diff` | **exactly what the repair of Codex's HOLD 20536 changed** on top of `f4644ef4` |
| `lineage/1232-codex-20554.diff` | **exactly what the repair of Codex's HOLD 20554 changed** on top of `d10129c2` |
| `lineage/1232-codex-20972.diff` | **exactly what the repair of Codex's HOLD 20972 changed** on top of `f4a51755` |

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

## The single-literal-assignment rule (dp's ruling, 2026-10-11)

Measured first on the narrowed core: 45% of the once-only requests were `S=/tmp/x; cat $S/y`. The rule
is scoped exactly that tightly. A variable assigned **exactly one literal** earlier in the **same
command**, and never otherwise bound, resolves to that literal where it is used as a path; it is then
judged like the literal (so `S=/etc; cat $S/hostname` is a concrete `/etc` refusal).

Everything else stays unenumerated (a scope request), each pinned by a battery row:

- **binding forms:** a `for` or `read` variable; any second assignment, including the conditional
  `S=a || S=b`; `unset`, `export` (of the name, anywhere), `declare` / `local` / `typeset` / `readonly`,
  `declare -n` namerefs (target included), arrays (`S[i]=`, `S=(…)`), appends (`S+=`), `printf -v`,
  `mapfile`, `let`, `getopts`;
- **placement:** an assignment that is not a top-level statement of its own — inside `( )`, `{ }`, a
  loop, a branch, a function or a substitution body; entered after `&&`, `||` or `|`; ended by anything
  but `;`, a newline or `&&` (so not a pipeline stage, not `&`); a prefix assignment (`S=/x cat $S/y`
  does not bind for that command's own expansions); and any use BEFORE the assignment;
- **the value:** a substitution (`S=$(…)`), or any `$` (live or quoted), backtick, glob character,
  brace, or `..` component;
- **the name:** HOME, PWD, OLDPWD, IFS, PATH and the other shell-owned names, and any name present in
  the gate's environment;
- **the command:** anything that runs a string or file as shell (`eval`, `source` / `.`, `sh -c`,
  `watch`, `su|runuser|script|flock -c`) or defines a function disqualifies every name in it;
- **expansion operators:** only a bare `$S` / `${S}` resolves; `${S:-x}` and friends stay unenumerated.

The bound value lives on the scan's own state (never module state), and only the outer command's
statements can bind: substitution bodies are subshells.

### Hardened after Codex's HOLD (notice 20536)

Codex found four P1s in `f4644ef4`; each is repaired conservatively (unenumerated → scope request),
with no new shell modelling:

1. **Substitution order.** `echo "$(cat $S/hostname)"; S=/tmp/x` allowed: bodies were scanned after
   the outer tokens, so a LATER literal reached an EARLIER body. Each lifted body now carries the
   position of the outer word that holds it, and resolves only bindings committed before that
   position (`S=/tmp/x; echo "$(cat $S/x)"` still allows; the reverse is a request).
2. **Field splitting.** `S="/tmp/x /etc"; cat $S/hostname` allowed (two arguments, one judged). A
   value containing IFS whitespace now binds only at a use written inside double quotes (the lexer
   marks quoted references); an unquoted use is unenumerated. Glob characters never bind.
3. **Rebinding through binders.** `printf -vS`, `read -aS`, `: $((S=0))` allowed. Now ANY binder
   anywhere disqualifies EVERY name: `read`, `printf` with any `-v…` option, `mapfile`/`readarray`,
   `declare`/`typeset`/`local`/`export`/`readonly`/`let`/`getopts`/`unset`/`eval`/`source`, any
   `$((` / `((`, and assigning expansions (`${S:=x}`, `${S=x}`).
4. **Interpreters and hidden code.** Any shell or interpreter word anywhere, with any option
   spelling, disqualifies every name. The nine forms Codex's earlier runner pinned are now judged
   in their own right: clustered code options (`bash -lc`, `sh -ec`, wrappers `exec` / `sudo`,
   `perl -ne`) take the next word as code; `builtin eval` is unwrapped like `command eval`; `$'…'`
   and `$"…"` quoting is unenumerated where judged as a path; an interpreter reading its program
   from a pipe, a here-string, `-` or a descriptor path (`bash <<<`, `… | sh`, `sh /dev/fd/3`) is
   unenumerated. A heredoc program (`python3 - <<'EOF'`) stays visible and judged.

### Hardened after Codex's second HOLD (notice 20554)

1. **IFS is the splitting condition, not whitespace.** `IFS=:; S=/tmp:/etc; cat $S/hostname`
   allowed. Now any IFS assignment anywhere in the command — a statement, a prefix to a command,
   `IFS+=` — makes EVERY binding resolve only at a double-quoted use; an unquoted use is a request.
   (`read` and the `declare` family already disqualify the rule wholesale.) The quoted control
   `IFS=:; S=/tmp:/etc; cat "$S/hostname"` stays allowed: quoting suppresses splitting whatever IFS is.
2. **No in-band marker can be forged.** The lexer marks a double-quoted reference with an in-band
   byte (`\x04`), and uses `\x00`–`\x03` for other markers; a command already containing one forged
   quote evidence (`cat \x04$S/…`, also inside single quotes). Any command containing a byte in
   `\x00`–`\x05` is now unenumerated BEFORE any marker is inserted, so every marker in a token is
   one the lexer wrote. Text the gate re-lexes (an `eval` / `sh -c` string) has its markers
   stripped first.

### Hardened after Codex's third HOLD (notice 20972)

**IFS is unprovable once the command names it.** `S=/tmp:/etc; for IFS in :; do cat $S/hostname; done`
allowed: 20554's repair recognised only `IFS=` / `IFS+=` words, and a loop binds without `=`. Bash
has more such binders, and an argv printer (`cat` replaced by a function that prints its arguments)
shows several of them splitting: `for IFS;` (positional), `select IFS in`, `exec {IFS}>` (an fd
number such as `10` splits on `1` and `0`), and backslash-newline spellings (`I\<newline>FS=:`,
`for I\<newline>FS`, `exec {I\<newline>FS}>`). So the repair does not enumerate binders. The
default-IFS assumption holds only while the command text, with backslash-newlines removed, does not
contain `IFS` at all. Any occurrence, in any position (including a data body or a comment), makes
every binding resolve only at a double-quoted use. The 20554 token test is kept beside it, so the
repair cannot allow anything 20554's repair refused. Code the gate cannot see (`eval`, `source`,
`sh -c`, namerefs, `printf -v`) already disqualifies the rule wholesale, so naming IFS literally is
the only way left to bind it.

**One deliberate divergence from the runner:** `IFS[0]=:; S=/tmp:/etc; cat $S/hostname` is Codex's
allow control. Under this repair it becomes a request, because it names IFS. On bash 5.2.21 `$IFS` reads
`:` after `IFS[0]=:`, yet splitting keeps the old value even after a later `IFS=$IFS`. That is
bash's internal state, not the language, so the gate does not rely on it.

**Stated execution contract (residual).** The rule assumes the shell's DEFAULT IFS unless the command
itself names it. An IFS inherited from earlier shell state is not visible to the gate. That is an
ASSUMPTION about the harness (that each Bash call starts from a shell with the default IFS), not
something this patch verifies; a harness that keeps one shell alive across calls would need the
quoted-use-only mode for every binding.

## Battery (written first)

Every Codex false-allow from the review rounds is a row: 16955/a589ed9, 17015, 17029a–f, 17054
(P1-quote-context and P1-output-model), the author's class probes (`seq -f`, `shuf -e`, `expr`,
`wc` / `sha256sum`, `grep` / `sort` / `head FILE`, `date +fmt`), and kimi's F2 A01–A08. Each row runs
through `command_scope_reach` and through `core.evaluate`.

| core | deny rows ALLOWED | request rows ALLOWED | deny rows refused (path / request) | allow rows allowed |
|---|---|---|---|---|
| 01e68a1c as reviewed | 14 | 25 | 121 (incl. 21 plain incomplete) | 57/57 |
| 01e68a1c merged onto main | 14 | 25 | 121 | 57/57 |
| narrowed, without the literal rule (c36101e4) | 0 | 0 | 99 path / 36 request | 57/57 |
| narrowed + literal rule as first built (f4644ef4) | 17 (Codex's forms, imported) | 1 | — | 70/70 |
| narrowed + literal rule, Codex-20536 repairs (d10129c2) | 12 (Codex 20554's 3 + 9 generalising rows) | 0 | — | 73/73 |
| + Codex-20554 repairs (f4a51755) | 9 (Codex 20972's form + 8 generalising rows) | 0 | — | 76/76 |
| **+ Codex-20972 repair (this patch)** | **0** | **0** | **113 path / 87 request** | **76/76** |

The battery has 1,034 checks: 1,034/1,034 on this patch, 1,007/1,034 on `f4a51755` (those 9 deny rows
× 3 checks). Codex's IFS runner is imported as `codex-ifs-*`, plus the `quote-ifs-*` rows above.

Before this (after Codex 20554), the battery had 995 checks, 995/995. Codex's quote runner (`codex-quote-*`) is imported
as invariants, plus rows that generalise it: every marker byte `\x00`–`\x05` forged in front of a
reference (`quote-marker-byte-*`, also inside single quotes) and three more IFS spellings (prefix
`IFS=:`, `IFS+=`, IFS assigned after the binding). Against the full battery, only those 12 deny rows
changed verdict from `d10129c2`'s core (ALLOW → request); no allow row changed.

**Codex's four runners, `--full-gate`, against this patch:** shell 0/96, literal 0/156, quote 0/54,
IFS **6/36**: `ifs-loop-binding` is now refused on all six surfaces, and the six failures are the
`IFS[0]=:` allow control (the divergence above), one per surface. Against `f4a51755` the IFS runner
reproduces Codex's 6/36 (`ifs-loop-binding`). (After 20554: quote 0/54 on `f4a51755`, 18/54 on
`d10129c2`.)

(Previously, against `f4644ef4`: Both of Codex's
runners are imported as invariants (`codex-shell-*`, `codex-lit-*`: every refusal case refused, every
positive control allowed). Against the full battery, the rows whose verdict changed from `f4644ef4`'s
core: the 17 Codex forms (ALLOW → refused or request) and `lit-after-a-python-c-literal` (an
interpreter now disqualifies the rule; ALLOW → request). No allow row changed.

the shell and literal runners went 54/96 and 48/156 → 0, and 944 checks passed.)

(Earlier, the literal rule's own rows: `D=/tmp/x; cat $D/y` and four admitted shapes moved request →
ALLOW, and `S=; cat $S/etc/hostname` request → a concrete `/etc/hostname` refusal.) A `request` row must be refused as the sentinel (a scope request),
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
| narrowed, without the literal rule (c36101e4) | 7,051 (21.3%) | 5,660 (17.1%) | 1,079 | 4,581 | 0 |
| narrowed + literal rule as first built (f4644ef4) | 5,539 (16.8%) | 4,048 (12.2%) | 1,080 | 2,968 | 0 |
| + Codex-20536 repairs (d10129c2) | 6,288 (19.0%) | 4,822 (14.6%) | 1,079 | 3,743 | 0 |
| **+ Codex-20554 repairs (this patch)** | **6,288 (19.0%)** | **4,822 (14.6%)** | 1,079 | **3,743** | 0 |

Per seat, this patch with the proposed grants: claude-code 18.0% (15.1% for f4644ef4, 21.1% without
the rule; 5.8% on 01e68a1c), codex 1.1% (0.8%), kimi-code 7.2% (6.1%, 8.6%; 2.9%). Path refusals are unchanged by the rule
(2,773 without grants in both): it only converts once-only requests into judged literals.

**Full window, 2026-09-20 to now.** 53,502 commands for the 01e68a1c rows (2026-10-10), 53,844 for
the literal-rule replay (2026-10-11; the corpus grows with every session).

| core | refused, no grants | refused, proposed grants | once-only requests (with grants) |
|---|---|---|---|
| 01e68a1c as reviewed / merged onto main | 6,629 (12.4%) | 4,025 (7.5%) | 0 (2,865 plain incomplete) |
| narrowed, without the literal rule | 13,401 (24.9%) | 11,499 (21.4%) | 9,804 |
| narrowed + literal rule as first built (f4644ef4) | 10,764 (19.9%) | 8,702 (16.1%) | 7,000 |
| + Codex-20536 repairs (d10129c2; 54,099 commands) | 12,099 (22.4%) | 10,075 (18.6%) | 8,374 |
| **+ Codex-20554 repairs (this patch; 57,597 commands, re-run)** | **13,016 (22.6%)** | **10,943 (19.0%)** | **9,160** |

The 20554 repairs cost nothing on the corpus: on the same 57,597 commands `d10129c2`'s core and this
patch give identical figures (no corpus command assigns IFS or carries a marker byte where it binds).
The full window's rise from 18.6% to 19.0% is the corpus growing, not the repair.

**The 20972 repair costs nothing on the corpus either.** It changes only `ifs_touched`, by adding a
text test to the token test, so only a command whose text contains `IFS` can change verdict. Of
57,766 commands (2026-10-12), 45 contain `IFS`. All 45 were replayed through `f4a51755`'s core and
this patch's, with and without the proposed grants: none changed verdict
(`held/measure-1232/ifs_subset.py`).

**What the standing grants absorb.**

- On the reviewed core, the proposed grants (the PR body's DEPLOY STEP set) took 3,415 refusals down
  to 1,607, absorbing 53%.
- On the narrowed core they take 7,051 down to 5,660, only 20%. They still absorb 61% of the path
  refusals (2,773 down to 1,079), but nothing of the once-only requests, which no grant can name.
- With grants the once-only count rises slightly (4,278 to 4,581): a lifted path refusal unmasks the
  unenumerated part of the same command.

**What the once-only requests were made of** before the literal rule (full window, with grants, 9,677 requests; the rule removes most of the first row):

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

**The literal rule, shipped (dp, 2026-10-11).** The broader experiment measured on 2026-10-10
(11.8% / 15.6%) is tighter now (environment names, `declare`, appends, arrays, code-running commands
and value checks all excluded), and lands at 12.2% / 16.1% with grants. Scripts and tables are in
`held/measure-1232/`.

## How it was built and checked

- The governed sources were extracted read-only into neutral-named scratch copies and three-way merged
  there (`git merge-file`, base `23ea9324`; then old main → `7e901d3c`, clean). The two conflicts (mechanism: `tally_scope(deadline=)`;
  orchestrator: main's MCP-transport views) were resolved there, and the narrowing was edited there.
- The patch was emitted against this branch's HEAD by the recovered `build_patch.py` recipe. The
  hooks-gt half was computed with `tools/hooks_gt.py`'s own functions.
- `git apply --check` is clean on HEAD. Applied to a throwaway export of HEAD, every staged file
  comes out byte-identical and `tools/hooks_gt.py check` reports ok.
- Python tests ran with the patched modules supplied through `HESTIA_CONTRACT_OVERLAY` and a process-wide import overlay; the patch's own test files ran from their staged copies. Results (2026-10-12, after Codex 20972): battery 1,034/1,034; Codex's runners shell 0/96, literal 0/156, quote 0/54, IFS 6/36 (the `IFS[0]=:` control only, see above) with `--full-gate`; contract 21 + shim parity 29×4 with the real-daemon arm against an isolated daemon built from this branch; `test_gate_core` all checks pass. Full CI Python set: 155 pass / 2 fail, both accounted for: `last_words_test` (A7) fails on main in this environment too; `loader_binds_installed_engine_test` poisons the installed core on purpose and cannot run under a process-wide import overlay (it passes under the per-test seam). Rust: unchanged by this repair (Python gate only); `cargo test -j2 --no-fail-fast` on `f4a51755`'s branch: 1317 passed, 0 failed.
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
