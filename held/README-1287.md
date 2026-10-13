# held/: the governed half of the #1287 fix (part 1), NOT applied

| file | sha256 |
|---|---|
| `78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740.patch` | `78386f56e15593aab2f3695208052f935418c145c9fe85a4e723cae678c76740` (the proposal; base main `53008a50`) |

9 files, +174/−21: the gate core, its hooks-gt copy and manifests, the shell battery and the contract
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
- NEW: generic **prose options**, for any command whose spec does not claim them as file, value or code
  options: `--reason`, `--message`, `--body`, `--argument`, `--title`, `--description`, `--comment`,
  `--note(s)`, `--subject`, `--summary`, `--text`, `--msg` (also `--opt=value`), and `-m` for `hestia`,
  `gh`, `glab`, `hg`, `jj`, `svn`, `tea` only (elsewhere `-m` is a mode, a module or a count).

Two things stay judged, by design:

- an UNQUOTED glob in the word itself (`--reason /etc/*`) — the shell expands it before the command
  runs, as for every other string position;
- an UNQUOTED use, in a data position, of a name assigned a glob-bearing value in the same command
  (`R="/x/*"; echo $R`): pathname expansion happens there, a directory read. On main this ALLOWED
  through `echo` (a small pre-existing hole, closed here); it is now a request. Quoted (`"$R"`), it is data.

Unchanged: every path-position row (`F="a*"; cat $F` and `cat "$F"` stay unenumerated), every refusal.

## Battery and runners

- `tools/shell_scope_reach_battery_test.py`: 1073/1073. New rows (`1287-*`): eleven prose shapes that now
  ALLOW, including the exact #1287 shape, `--reason=`, `gh --body`, `--argument`, `--title/--description`,
  `hestia -m`, an unknown variable quoted in `--reason`; seven that must stay requests (glob-valued names in
  path positions quoted and unquoted, unquoted glob-valued names in `echo` and `--reason`, a prose variable
  ALSO used as a path, `-m` for `python3` and `mkdir`); two that must stay refused (a prose flag cannot hide
  a following `/etc/hostname`, or an unquoted `/etc/*` in its own value).
- Rows whose verdict changed from main's core: the seven prose ALLOW rows (were requests on main) and
  `1287-unquoted-glob-var-in-echo` (was ALLOWED on main, now a request). No existing row changed.
- Contract suite: 22 `decide()` tests (new: `test_prose_in_a_message_position_is_data_on_every_seat` — the
  exact shape allowed and asking society law on claude-code, codex, kimi and gemini; the path control and the
  unquoted-glob control are once-only requests on all four) + shim parity 29×4.
- Codex's three #1232 runners, `--full-gate`, against this patch: shell 0/96, literal 0/156, quote 0/54.

## What it changes on the real corpus

Replayed with the committed `held/measure-1232/` scripts, main's core (`53008a50`, #1232 applied)
against this patch's: 60,004 shell commands from 2026-09-20 to 2026-10-13 (the 2026-10-05 window is
the first 33,054).

| | full window, no grants | full window, proposed grants | 2026-10-05 window, no grants |
|---|---|---|---|
| once-only requests REMOVED (main: request → this patch: allow) | **144** | **145** | **109** |
| new requests (main: allow → this patch: request) | 47 | 53 | 8 |
| net | **−97** | **−92** | **−101** |

The new requests all come from the one rule this patch adds: an UNQUOTED use, in a data position, of a
name assigned a glob-bearing value in the same command (the corpus shape is `f=…/*.ext; …; echo $f`) —
a directory listing main allowed through `echo`. No path refusal changed.

Measurement provenance, stated: the corpus reader reads every seat's session logs (codex's and kimi's
homes included) from a Python script. A shell command naming those paths would be refused for this
seat; a script's computed paths are a declared residual of the shell judge. The numbers are real, but
the read crossed a boundary the gate does not see, and a future measurement should run as a grant or
under the operator.

## Tests

- Battery 1073/1073; contract 22 `decide()` tests + shim parity 29×4, with the real-daemon arm against an isolated daemon built from this branch (main's Rust; this patch changes no Rust); `test_gate_core` all checks pass.
- Codex's three #1232 runners, `--full-gate`, against this patch: 0/96, 0/156, 0/54.
- Full CI Python set with the patched modules: 162 pass / 3 fail — `last_words_test` (A7) and `shared_target_split_test` (cannot locate the real cargo behind the shim) fail on main in this environment too; `loader_binds_installed_engine_test` poisons the installed core on purpose and cannot run under a process-wide import overlay (it passes under the per-test seam).
- No Rust changed, so the Rust suite was not re-run for this patch.

## Residual, stated

An unquoted use of a variable whose value comes from OUTSIDE the command (the environment, a
substitution) in a data position may still expand a glob there; the gate cannot know the value, and
making every such use a request would put a once-only request on `echo $f`-style lines. This was the
behaviour on main for `echo` / `printf` and is unchanged; it now also holds for the prose options.

## Not in this patch: #1287 part 2

The operator UI offering "grant" for an unenumerated request is a separate (non-governed) change.
