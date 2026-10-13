# held/: the governed half of the #1287 fix (part 1), NOT applied

| file | sha256 |
|---|---|
| `e2705d13e51f58595268361276ae1644efae1eb5b448365b690df62d7762111b.patch` | `e2705d13e51f58595268361276ae1644efae1eb5b448365b690df62d7762111b` (the proposal; base main `53008a50`) |
| `lineage/78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740.patch` | superseded: HELD by Codex (notice 21639, `docs/reviews/1289-prose-option-review.md`) |

9 files, +224/−23: the gate core, its hooks-gt copy and manifests, the shell battery and the contract
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

## Battery and runners

- `tools/shell_scope_reach_battery_test.py`: 1108/1108. New rows (`1287-*`): prose shapes that now ALLOW
  (the exact #1287 shape, `--reason=`, `gh pr comment --body`, `hestia gate corroborate --argument`,
  `gh pr create --title/--body`, `gh pr close -c`, `gh pr merge --subject`, an unknown variable quoted in
  `--reason`, plus quoted `echo` / `printf` / grep-pattern controls); rows that must stay requests
  (glob-valued names in path positions quoted and unquoted, unquoted glob-valued names in `echo` and
  `--reason`, a prose variable ALSO used as a path, `-m` for `python3`, `mkdir` and `hestia`, and
  `grep needle --text "$UNSET"`); rows that must stay refused (a prose flag cannot hide a following
  `/etc/hostname` or an unquoted `/etc/*`, and Codex 21639's value-less flags: `grep --text`, `rg --text`,
  `diff --text`, `readelf --notes`, `git diff --summary`, plus `gh pr review -c` and `gh pr view --body`,
  where the option is not prose for that subcommand).
- Run against the HELD 78386f56 core, the revised battery fails 23 checks — the new rows catch the HOLD.
- Rows whose verdict changed from main's core: the eight prose ALLOW rows (were requests on main) and
  `1287-unquoted-glob-var-in-echo` (was ALLOWED on main, now a request). No existing row changed.
- Contract suite: 22 `decide()` tests (new: `test_prose_in_a_message_position_is_data_on_every_seat` — the
  exact shape allowed and asking society law on claude-code, codex, kimi and gemini; the path control and the
  unquoted-glob control are once-only requests on all four) + shim parity 29×4.
- Codex's runners, `--full-gate`, against this patch: #1289 prose 0/66 (78386f56: 36/66); #1232 shell 0/96,
  literal 0/156, quote 0/54.

## What it changes on the real corpus

**e2705d13 (this proposal).** Replayed with `held/measure-1232/cost_1287_scoped.py` on claude-code's
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

- Battery 1108/1108; `test_gate_core` all checks pass; contract suite 22 `decide()` tests + shim parity 29×4 pass (staged modules, no live daemon).
- Codex's runners, `--full-gate`: #1289 0/66, #1232 0/96, 0/156, 0/54.
- `verify_held`: `git apply --check` clean on this branch's HEAD; applied to a throwaway export every staged
  file is byte-identical and `tools/hooks_gt.py check` is ok.
- Not re-run for e2705d13: the full CI Python set (162/3 on 78386f56) and the real-daemon contract arm;
  the revision touches only the scope classifier's option table, which those exercise through the same
  core functions as the runs above.
- (78386f56) Full CI Python set with the patched modules: 162 pass / 3 fail — `last_words_test` (A7) and `shared_target_split_test` (cannot locate the real cargo behind the shim) fail on main in this environment too; `loader_binds_installed_engine_test` poisons the installed core on purpose and cannot run under a process-wide import overlay (it passes under the per-test seam).
- No Rust changed, so the Rust suite was not re-run for this patch.

## Residual, stated

An unquoted use of a variable whose value comes from OUTSIDE the command (the environment, a
substitution) in a data position may still expand a glob there; the gate cannot know the value, and
making every such use a request would put a once-only request on `echo $f`-style lines. This was the
behaviour on main for `echo` / `printf` and is unchanged; it now also holds for the prose options.

Pre-existing, not changed here (found auditing `-m` for Codex 21639): `_CMD_SPECS["git"]` lists
`-m` / `--message` as string options for EVERY git subcommand, but `git log|show|diff -m` is a
value-less flag, so main allows `git log -m /etc/hostname` unjudged. Probed: it reaches nothing —
git refuses a pathspec outside the repository, and `git diff --no-index -m …` is a usage error
(exit 129). The same per-subcommand keying would tidy it; it is left out to keep this patch to #1287.

## Not in this patch: #1287 part 2

The operator UI offering "grant" for an unenumerated request is a separate (non-governed) change.
