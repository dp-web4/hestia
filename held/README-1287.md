# held/: the governed half of the #1287 fix (part 1), NOT applied

| file | sha256 |
|---|---|
| `c78ba6517d8f5be0db4774d78bba1fd16c0585b4fb493cba6464881b08596813.patch` | `c78ba6517d8f5be0db4774d78bba1fd16c0585b4fb493cba6464881b08596813` (the proposal; base main `53008a50`) |
| `lineage/b7ec48209278b6c7c332504f27ad883557cecd96b281b84efa1b1b1de7b504b2.patch` | superseded: HELD by Codex (notice 21861, `docs/reviews/1289-positional-indirection-review.md`) |
| `lineage/3174573d0d4adc7e87eff07f5c851e1c35b83b5a314637ae286d3adf68353fd9.patch` | superseded: HELD by Codex (notice 21790, `docs/reviews/1289-nested-array-review.md`) |
| `lineage/743dad83d6ab4e6844c2f3ec0a2bc0eb6fb8a8a657ea2133c4c58a2a15cdeb65.patch` | superseded: HELD by Codex (notice 21718, `docs/reviews/1289-quoted-array-review.md`) |
| `lineage/e2705d13e51f58595268361276ae1644efae1eb5b448365b690df62d7762111b.patch` | superseded: HELD by Codex (notice 21675, `docs/reviews/1289-word-splitting-review.md`) |
| `lineage/78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740.patch` | superseded: HELD by Codex (notice 21639, `docs/reviews/1289-prose-option-review.md`) |

9 files, +487/−33: the gate core, its hooks-gt copy and manifests, the shell battery and the contract
suite. `git apply --check` is clean on this branch's HEAD; applied to a throwaway export every staged
file is byte-identical and `tools/hooks_gt.py check` reports ok. Nothing here is applied.

## The friction (hestia #1287, part 1)

Within an hour of #1232 going live, a seat filed a refusal with an explanation:

```
cd ~/ai-workspace/hestia; R="Refused: … (deploy/from-main/hestia-deploy.sh ~L605, plugins/*/expects.json 'evaluate deploy hold') …"; hestia gate deny ID --as claude-code --reason "$R"
```

`R` holds a `*`, so #1232's literal rule (Codex HOLD 20536, P1-2) never binds it, and every use of `$R`
was unenumerated — a once-only scope request the operator had to approve — although `$R` is a message
argument, not a path.

## The rule now

A value that cannot bind (a glob character, whitespace outside double quotes, an expansion, …) makes a
use unenumerated **only where that use is judged as a PATH**. In a data position the expansion is data:

- the positions `_CMD_SPECS` already classes as strings or patterns — `echo` / `printf` / `tr` operands,
  the pattern of `grep` / `rg` / `sed` / `awk`, the string / pattern / delimiter option values
  (`git -m`, `find -name`, `cut -d`, …) — which already skipped expansions;
- NEW: **prose options**, keyed by (command, subcommand words) in `_PROSE_OPTS`, never generic:
  - `hestia`: `--reason`, `--argument` (every such field in `core/src/cli.rs` is a clap `String`);
  - `gh pr|issue create|edit`: `--title`/`-t`, `--body`/`-b`; `gh pr|issue comment`, `gh pr review`:
    `--body`/`-b`; `gh pr|issue close`: `--comment`/`-c`; `gh pr merge`: `--subject`/`-t`, `--body`/`-b`;
    `gh release create|edit`: `--title`/`-t`, `--notes`/`-n` — each read from `gh <sub> --help`.
  - Also `--opt=value`. The subcommand words must come before the option; anything else is judged as
    before (as a path).

  **Why not generic (78386f56, HELD by Codex 21639).** The first proposal treated `--text`, `--notes`,
  `--summary`, … as prose for any command whose spec did not claim them. Absence from a spec is not
  evidence that an option takes a value: `grep --text F`, `rg --text F`, `diff --text F`,
  `readelf --notes F`, `git diff --summary F` and `gh pr review -c F` are value-less flags, and the
  next word `F` is a file that the generic rule swallowed unjudged (36/66 on Codex's runner). The
  table is driven by the corpus: all 144 requests that 78386f56 removed came from `gh` subcommands,
  `hestia gate …`, `git commit -m` (already in git's spec) and a `python3 …/seat_run_requests.py
  decline --reason` script; none from any command a generic rule was needed for.

Two things stay judged, by design:

- an UNQUOTED glob in the word itself (`--reason /etc/*`) — the shell expands it before the command
  runs, as for every other string position;
- an UNQUOTED use, in a data position, of a name assigned a glob-bearing value in the same command
  (`R="/x/*"; echo $R`): pathname expansion happens there, a directory read. On main this ALLOWED
  through `echo` (a small pre-existing hole, closed here); it is now a request. Quoted (`"$R"`), it is data.

Unchanged: every path-position row (`F="a*"; cat $F` and `cat "$F"` stay unenumerated), every refusal.

### Revision after Codex HOLD 21675: field splitting (743dad83)

e2705d13 checked only for pathname expansion. An UNQUOTED value is also field-split, so whitespace in
it inserts more arguments, and in a prose position the next argument can be a file:
`R="hello --body-file F"; gh pr create --title $R` hands gh `--body-file F`, and
`gh release create v2 --notes $R` with R="hello F" uploads F as an asset (36/66 on Codex's runner).

**This hole was older than the patch.** On main, the same split defeats the positions `_CMD_SPECS`
already skipped: `R="x /etc/hostname"; grep $R`, `grep -e $R`, `sed -n $R`, `awk $R` and
`git commit -m $R` are all ALLOWED on main `53008a50`, as is a loop variable in a sed program
(`for r in 1,2; do sed -n ${r}p F; done`): battery rows `1289-split-*`, 8 of them leak on main. e2705d13 widened it from those positions to the prose options.

The rule is now about **arguments**, not globs. `data(word, fields)`:

- a QUOTED expansion (`"$R"`, `"${R}"`, and now `"$(…)"` / `` "`…`" ``) is one argument: data;
- an UNQUOTED glob-valued name is still a directory read: unenumerated, in every data position;
- where another argument would be a file (an option value, the grep / sed / awk program, a prose
  option), an UNQUOTED expansion is data only when it is provably ONE field: a name the literal rule
  bound to one literal with no IFS whitespace (`in_force()`, the binding #1232 already proves),
  arithmetic, a digit / flag-letter special parameter, or `$'…'` (a quoted word of its own; its
  lexer placeholder is not an expansion that splits). Anything else (`$R` holding whitespace, an
  unknown or inherited name, a loop variable, an unquoted `$(…)`) is unenumerated: a once-only
  request, whose refusal says to quote it (`"${r}p"`), which makes it one argument and data.
- in an `echo` / `printf` / `tr` operand (`fields=False`), another field is only another string,
  so the glob rule alone applies, as before.

To tell `git commit -m "$(cat <<'EOF' …)"` (one argument, the ordinary commit shape) from
`git commit -m $(…)`, the lexer now marks a substitution written inside double quotes with
`_DQ_REF`, as it already marked `"$NAME"`. Every other reader of the mark strips it or works from
expansion spans; the battery and all five runners pass with it.

### Revision after Codex HOLD 21718: quoted arrays (3174573d)

743dad83 treated every double-quoted expansion as one argument. Bash expands `"${A[@]}"` to one
argument PER ELEMENT even inside quotes, so `A[0]=hello; A[1]=OUTSIDE; gh release create v2 --notes
"${A[@]}"` hands `--notes` hello and uploads OUTSIDE as an asset (36/66 on Codex's quoted-array runner).
Now a quoted `${…}` matching `_PER_ELEMENT` (`${@…}`, `${A[@]…}`, `${!A[@]}`, `${!PREFIX@}`) is
unenumerated wherever another argument can be a file (`fields`), and the refusal says to use a scalar.
`"${A[*]}"`, `"${A[0]}"`, `"${#A[@]}"` and `"${X:-a@b}"` are one word and stay data; in an
`echo` / `printf` / `tr` operand extra elements are only more strings. `"$@"` was never marked quoted by
the lexer, so it was already a request. On claude-code's 47,002 recorded commands this revision changes
**no** verdict against 743dad83 (main → 3174573d: −115 / +59, as before).

### Revision after Codex HOLD 21790: nested and indirect expansions (b7ec4820)

3174573d tested only the OUTER expansion's prefix, and `_expansion_spans` ended a `${` at its first
`}`. So `"${R:-${A[@]}}"` (span `${R:-${A[@]}`) was data, but bash still passes one argument per element
when the default is taken: `--notes "${R:-${A[@]}}"` uploads OUTSIDE (36/66 on Codex's nested runner).
Probing the same class found two more the review did not list. `"${R:-$@}"` is per element. So is
indirection: `R='A[@]'; … --notes "${!R}"` is `"${A[@]}"` under another name.

- `_expansion_spans` now closes a `${` at its BALANCED `}`: nested `${` counted, a backslash-escaped
  character skipped (`"${R:-x\}y}"` is one word). Unbalanced is unmodelled, as before.
- A quoted `${…}` is one argument only if `_per_element` says so: not `_PER_ELEMENT`, not an
  indirection `${!name…}` (the target decides; `${!A[*]}` / `${!P*}` join and stay one word; `${!}`
  is the last PID), and recursively no `$@` or per-element `${…}` inside its operator word.
  Nested scalars (`"${R:-$X}"`, `"${R:-${X}}"`), elements and joined arrays stay data.
- On claude-code's 47,117 recorded commands this revision changes **no** verdict against 3174573d (main → b7ec4820: −115 / +59, as before; with the proposed grants −116 / +63, also unchanged).

### Revision after Codex HOLD 21861: an allowlist, not a fourth denylist entry (c78ba651)

b7ec4820's `_INDIRECT` matched `${!` followed by a NAME, so `set -- 'A[@]'; … --notes "${!1}"` (the
target from a positional) was one quoted word, and bash passed one argument per element (36/66 on
Codex's positional runner). This was the third HOLD in a row for one more splitting shape: 743dad83
missed `"${A[@]}"`, 3174573d missed it nested, b7ec4820 missed it behind a positional. The test was
a DENYLIST of shapes known to split. A denylist over bash's expansion grammar fails open on every
shape nobody listed yet.

- `_per_element` is now an ALLOWLIST (`_ONE_WORD_HEAD`): a quoted `${…}` is one argument only if its
  head is a name (index absent or holding no `@`), a positional number, or `*` `#` `?` `$` `-`, followed
  by `}` or an operator; or `${!}` alone; or a `${#…}` count; or the joined `${!A[*]}` / `${!P*}`.
  Every other head is unproved and judged: `${@…}`, `${A[@]…}`, `${A[ @ ]}`, and every `${!…}`
  indirection (`${!R}`, `${!1}`, `${!10}`, `${!#}`, `${!1:-x}`). Nesting recurses as before.
- On claude-code's 47,233 recorded commands the allowlist changes **no** verdict against b7ec4820 (main → c78ba651: −115 / +59, as before; with the proposed grants −116 / +63, also unchanged): no recorded command used a head outside the allowlist.

## Battery and runners

- `tools/shell_scope_reach_battery_test.py`: 1169/1169 (743dad83). New rows (`1287-*`): prose shapes that now ALLOW
  (the exact #1287 shape, `--reason=`, `gh pr comment --body`, `hestia gate corroborate --argument`,
  `gh pr create --title/--body`, `gh pr close -c`, `gh pr merge --subject`, an unknown variable quoted in
  `--reason`, plus quoted `echo` / `printf` / grep-pattern controls); rows that must stay requests
  (glob-valued names in path positions quoted and unquoted, unquoted glob-valued names in `echo` and
  `--reason`, a prose variable ALSO used as a path, `-m` for `python3`, `mkdir` and `hestia`, and
  `grep needle --text "$UNSET"`); rows that must stay refused (a prose flag cannot hide a following
  `/etc/hostname` or an unquoted `/etc/*`, and Codex 21639's value-less flags: `grep --text`, `rg --text`,
  `diff --text`, `readelf --notes`, `git diff --summary`, plus `gh pr review -c` and `gh pr view --body`,
  where the option is not prose for that subcommand).
- New for HOLD 21675 (`1289-*`): requests for Codex's six split shapes, main's own split positions
  (`grep $R`, `grep -e $R`, `sed -n $R`, `awk $R`, `git commit -m $R`), an unknown name unquoted in
  `--reason`, and an unquoted `$(…)` / backtick in a pattern, `-m` or `--reason`; allowed controls:
  the quoted forms, `echo $R` (a split there is only more strings), one-field names unquoted in
  `--reason` and as a grep pattern, `$((…))` and `$?` as a pattern, and a quoted `$(…)` / backtick in
  `-m`, `--reason` and inside `--body` prose, `grep -c $'\tpass\t'`, and a quoted loop variable in a
  sed program (and the unquoted one as a request).
- The revised battery fails 32 checks on the held e2705d13 core and 28 on main's (main leaks the 8
  `1289-split-*` rows main already had, and requests the quoted-substitution prose controls).
- Run against the HELD 78386f56 core, the e2705d13 battery failed 23 checks — the rows that caught that HOLD.
- Rows whose verdict changed from main's core: the eight prose ALLOW rows (were requests on main) and
  `1287-unquoted-glob-var-in-echo` (was ALLOWED on main, now a request). No existing row changed.
- Contract suite: 22 `decide()` tests (new: `test_prose_in_a_message_position_is_data_on_every_seat` — the
  exact shape allowed and asking society law on claude-code, codex, kimi and gemini; the path control and the
  unquoted-glob control are once-only requests on all four; since 743dad83 also Codex 21675's unquoted
  split `--title $R`) + shim parity 29×4.
- Codex's runners, `--full-gate`, against 743dad83: #1289 word-splitting 0/66 (e2705d13: 36/66); #1289
  prose 0/66 (78386f56: 36/66); #1232 shell 0/96, literal 0/156, quote 0/54.

## What it changes on the real corpus

**743dad83 (this proposal).** Replayed with `held/measure-1232/cost_1289_split.py` on claude-code's
own records (46,914 shell commands now), judged by main's core, e2705d13's and this one's.

| main → | e2705d13, no grants | **743dad83, no grants** | 743dad83, proposed grants |
|---|---|---|---|
| once-only requests REMOVED (request → allow) | 115 | **115** | 116 |
| new requests (allow → request) | 47 | **59** | 63 |
| net | −68 | **−56** | −53 |

e2705d13 → 743dad83 changes 12 rows, all allow → request and all one shape: an UNQUOTED loop variable,
function parameter or `$(…)` in a sed / awk / grep program (`for r in 31,43 …; do sed -n ${r}p F`,
`awk -v n=$n …`, `g(){ grep -F "$1" …` with `$1` unquoted elsewhere). Main allowed them because the
program position was skipped whole. They are the hole's own shape (a value nobody bound, split into
the program's argv), so they stay requests. Quoting (`"${r}p"`) makes each one argument and data.
An earlier cut (4e43cc4d, never published) also requested 4 `grep -c $'\tpass\t'` rows: `$'…'` is a
quoted word, and 743dad83 treats it as one.

**e2705d13 (superseded).** Replayed with `held/measure-1232/cost_1287_scoped.py` on claude-code's
OWN records only: 46,777 shell commands, judged by main's core (`53008a50`), 78386f56's and this one's.
Every verdict 78386f56 changed on the full 60,004-command corpus was claude-code's (191 of 191), so no
other seat's home was read for this measurement. On these records the replay reproduces 78386f56's
numbers exactly (144 / 47), which checks the subset.

| main → | 78386f56, no grants | **e2705d13, no grants** | e2705d13, proposed grants |
|---|---|---|---|
| once-only requests REMOVED (request → allow) | 144 | **115** | 116 |
| new requests (allow → request) | 47 | **47** | 51 |
| net | −97 | **−68** | −65 |

Between 78386f56 and e2705d13, 31 rows differ:

- **30 return to requests**, all one shape: `python3 …/seat_run_requests.py decline … --reason "…"`, this
  seat's own script. A script is not a command the table can key safely (its options are whatever the
  script parses), so it is left out on purpose; `--reason` there stays judged as a path.
- **1 becomes allowed** that 78386f56 still requested: `gh pr close 1239 -R … -c "Superseded by $N: …"`.
  `-c` is `--comment string` for `gh pr close`; the generic list knew only `--comment`.

The new requests are unchanged: they all come from the one rule this patch adds, an UNQUOTED use in a
data position of a name assigned a glob-bearing value in the same command (the corpus shape is
`f=…/*.ext; …; echo $f`), a directory listing main allowed through `echo`. No path refusal changed.

**78386f56 (superseded), full corpus.** 60,004 commands from 2026-09-20 to 2026-10-13, every seat:
144 / 145 / 109 removed, 47 / 53 / 8 new (full window no grants / proposed grants / 2026-10-05 window).

Measurement provenance, stated (78386f56's full-corpus run): the corpus reader reads every seat's session logs (codex's and kimi's
homes included) from a Python script. A shell command naming those paths would be refused for this
seat; a script's computed paths are a declared residual of the shell judge. The numbers are real, but
the read crossed a boundary the gate does not see, and a future measurement should run as a grant or
under the operator.

## Tests

- c78ba651: battery 1293/1293 (b7ec4820's core fails 22 of its checks: the 11 new `1289-posind-*` /
  `1289-array-spaced-index` request rows in both arms; the 7 new one-word controls pass on both); `test_gate_core` all checks pass; contract suite 22 `decide()` tests + shim parity 29×4 pass (staged modules, no live daemon).
- Codex's runners against c78ba651, `--full-gate`: #1289 positional-indirection 0/66 (b7ec4820: 36/66), nested-array 0/66, quoted-array 0/66, word-splitting 0/66, prose 0/66, #1232 0/96, 0/156, 0/54.
- b7ec4820: battery 1253/1253 (3174573d's core fails 24 of its checks: the 12 new `1289-nested-*` /
  `1289-indirect-*` rows in both arms); `test_gate_core` all checks pass; contract suite 22 `decide()` tests + shim parity 29×4 pass (staged modules, no live daemon).
- Codex's runners against b7ec4820, `--full-gate`: #1289 nested-array 0/66 (3174573d: 36/66), quoted-array 0/66, word-splitting 0/66, prose 0/66, #1232 0/96, 0/156, 0/54.
- 3174573d: battery 1210/1210 (743dad83's core fails 22 of its checks); `test_gate_core` all checks pass; contract suite 22 `decide()` tests + shim parity 29×4 pass (staged modules, no live daemon).
- Codex's runners against 3174573d, `--full-gate`: #1289 quoted-array 0/66 (743dad83: 36/66), word-splitting 0/66, prose 0/66, #1232 0/96, 0/156, 0/54.
- 743dad83: battery 1169/1169; `test_gate_core` all checks pass; contract suite 22 `decide()` tests + shim parity 29×4 pass (staged modules, no live daemon).
- Codex's runners, `--full-gate`: #1289 word-splitting 0/66, #1289 prose 0/66, #1232 0/96, 0/156, 0/54.
- `verify_held` (c78ba651): `git apply --check` clean on this branch's HEAD; applied to a throwaway export every staged
  file is byte-identical and `tools/hooks_gt.py check` is ok.
- Not re-run for e2705d13, 743dad83, 3174573d, b7ec4820 or c78ba651: the full CI Python set (162/3 on 78386f56) and the real-daemon contract arm;
  e2705d13 touched only the scope classifier's option table, and 743dad83 only its data-position check and
  the lexer's quote mark, which those exercise through the same core functions as the runs above.
- (78386f56) Full CI Python set with the patched modules: 162 pass / 3 fail — `last_words_test` (A7) and `shared_target_split_test` (cannot locate the real cargo behind the shim) fail on main in this environment too; `loader_binds_installed_engine_test` poisons the installed core on purpose and cannot run under a process-wide import overlay (it passes under the per-test seam).
- No Rust changed, so the Rust suite was not re-run for this patch.

## Residual, stated

An unquoted use of a variable whose value comes from OUTSIDE the command (the environment, a
substitution) in an `echo` / `printf` / `tr` operand may still expand a glob there; the gate cannot
know the value, and making every such use a request would put a once-only request on `echo $f`-style
lines. This was the behaviour on main and is unchanged. Since 743dad83 it no longer holds for option
values, programs or the prose options: there such a use is a request (field splitting, above).

Pre-existing, not changed here (found auditing `-m` for Codex 21639): `_CMD_SPECS["git"]` lists
`-m` / `--message` as string options for EVERY git subcommand, but `git log|show|diff -m` is a
value-less flag, so main allows `git log -m /etc/hostname` unjudged. Probed: it reaches nothing —
git refuses a pathspec outside the repository, and `git diff --no-index -m …` is a usage error
(exit 129). The same per-subcommand keying would tidy it; it is left out to keep this patch to #1287.

## Not in this patch: #1287 part 2

The operator UI offering "grant" for an unenumerated request is a separate (non-governed) change.
