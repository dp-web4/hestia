# held/: hestia#1314, non-path text judged as a path, NOT applied

| file | sha256 |
|---|---|
| `19952a0521073ed8ce7fd03aaf8d4b4a7f1a962760cad9581fd2a2a2a6c25b3c.patch` | `19952a0521073ed8ce7fd03aaf8d4b4a7f1a962760cad9581fd2a2a2a6c25b3c` (base main `2d79644f`) **current** |

10 files, +403/−20: the gate core, its hooks-gt copy and five manifests (emitted by `tools/hooks_gt.emit_patch`
from a scratch copy of the core), the shell battery, the gate-core unit test and the decide contract test.
The single gate, the mechanism and the daemon are unchanged. Nothing here is applied.

How it was checked without touching a tree: the builder applies every hunk **in memory** to HEAD's text and
compares the result with the intended bytes (all 10 files match). No `git apply`, not even `--check`, was run
against any tree.

## Repro on main `2d79644f` (offline: core + `decide()` with the contract test's stub daemon)

Grant `path:<ws>/**` plus a recursive grant on a tree outside the workspace (McNugget's
`/Users/dennispalatov/repos`). "Ungranted cwd" is an existing directory outside every grant, as McNugget's
`…/ai-workspace` was (its refusal said that tree is outside its workspace). Every main refusal below is
`mrh.command` and opens a peer scope request (`hestia_scope_claim`), so #1316's no-request route for
`mrh.command.unenumerated` does not cover any of them.

| # | shape | main | patched |
|---|---|---|---|
| 1 | `curl localhost:8760/health` from any cwd | allow | allow |
| 1 | same after `cd D &&` or `git -C D` where `D/<url>` is not granted (an exact grant on D; McNugget: a base outside its workspace) | **deny** `D/localhost:8760/health`, request | allow |
| 2 | `curl http://127.0.0.1:8760/health`, same two conditions | allow / **deny** `D/http:/127.0.0.1:8760/health` (`//` collapsed), request | allow |
| 3 | `tail … \| /usr/bin/python3 -c …` (any cwd, any grant) | **deny** `/usr/bin/python3`, request | allow |
| 4 | `cd <granted abs> && cat ./x` from an ungranted cwd | **deny** `<cwd>/x`, request | allow |
| 5 | `gh api … --jq '.[-1].body'`, `jq '.[-1].body'` from an ungranted cwd | **deny** `<cwd>/.[-1].body`, request | allow |
| ctrl | `curl file:///etc/passwd` | **allow** (judged as relative `file:/etc/passwd`) | deny `/etc/passwd` |

Why 1 and 2 need a directory change: a relative candidate under the event cwd is judged only if its parent
exists (`<cwd>/localhost:8760` does not). A candidate under a `cd`/`-C` base is judged strictly, by the Read
rule, whenever its nearest existing ancestor is below `/`, and the base itself always exists. So the URL is
refused exactly when a base does not reach `<base>/<url>`. On case 4: the issue reads the stray roots as
`git -C` being treated like a relative `cd`. In the code, `git -C D` adds D as an extra base, and the event cwd
stays a base after `cd /abs &&`. The refusals come from that second fact.

## The change (gate core only)

1. **URLs.** A positional argument that is a network URL is recorded as kind `url`, not as a path:
   a scheme other than `file:` (`http://`, `https://`, `ssh://`, …), or, for a URL client (`curl`, `wget`,
   `http`, `https`, `xh`, `xhs`, `curlie`), `host:port[/…]`. Two guards keep it from being an escape hatch:
   - a `..` component disqualifies it;
   - in `_command_scope_reach_one`, a `url` candidate whose first component (`http:`, `localhost:8760`)
     **exists** under any base (event cwd, granted repo roots, `cd`/`-C` bases) is judged as the relative
     path it also is. A directory named `http:` (a symlink to `/`, say) therefore stays judged, and so does
     every URL whose bases the gate cannot follow.
   - An expansion inside a URL stays unenumerated (`curl http://h/$X`), as before.
2. **`file:` URLs are paths.** `file:///x`, `file://localhost/x` and `file:/x` are judged as `/x` in every
   position, including option values (`--url`, `sqlite3 file:…`). This is a tightening: main allowed them.
3. **System programs.** A command word that is a normalised literal path in `/bin`, `/sbin`, `/usr/bin`,
   `/usr/sbin`, `/usr/local/bin`, `/usr/local/sbin`, `/opt/homebrew/bin` or `/opt/homebrew/sbin` is not a
   reach: it is the program the bare name finds on PATH. The list is fixed, never read from `$PATH`. The
   program's arguments are still judged (`/usr/bin/cat /etc/hostname` asks only about `/etc/hostname`). Any
   other program path is judged as before (`<outside>/bin/python`, `/usr/bin/../..<outside>/bin/python`).
4. **Leading absolute `cd`.** When the whole command is `cd <literal absolute dir> && …` and every later
   separator is `&&` or a pipe, the event cwd stops being a base and that directory (resolved, so a later
   `..` is judged physically) takes its place. If the `cd` fails, `&&` runs nothing more. Any `;`, newline,
   `||`, `&`, subshell, `{ }` group or command substitution keeps the event cwd as a base, as before.
5. **jq programs.** `jq`'s first positional is its program (`pattern_first`), unless `-f`/`--from-file` (or a
   short cluster holding `f`, such as `-rf`) names a program file; then every positional is an input file and
   judged. `-L`/`--library-path`/`--indent` take a value. A two-value option (`--arg N V`, `--rawfile N F`)
   can only move the exception onto its name, an earlier word; the file after it is still judged. `gh`'s
   `--jq`/`-q` and `--template`/`-t` are strings on exactly the subcommands where `gh <sub> --help` (gh 2.x on
   CBP) says so: `api`, `pr list|view|checks`, `issue list|view`, `run list|view`, `release list|view`,
   `repo view`. **jq is not installed on CBP**, so the jq option arity is from jq's manual, not from a local
   `jq --help`. A reviewer with jq should check it.

## Evidence

- `tools/shell_scope_reach_battery_test.py` (patched copy): **1466 passed, 0 failed** on the patched core;
  1434/0 before the new rows. On main's core the same battery fails exactly **12** checks: 9 allows main
  refuses and 3 `file:` URL denials main allows. 32 new checks: 11 must-allow rows from an ungranted cwd outside
  the workspace, 20 must-still-deny controls, and 1 still-unenumerated row (an expansion in a URL). The controls:
  `file:` URLs in three spellings, `./x` in the ungranted cwd, `cd …;`, `cd … ||`, `cd … && x & y`, a relative
  first `cd`, a `..` escape after the pin, a system program's outside argument, a `..` system-dir spelling, an
  outside program, a URL with `..`, a scheme-named directory symlink (`http:` -> outside), five jq spellings
  (`-f F`, clustered `-rf F`, `--from-file=F`, `-L D`, an input file) and `gh … --input F`.
- `tools/one_gate_decide_contract_test.py` (patched copy, `HESTIA_CONTRACT_OVERLAY` -> patched core):
  **PASS: 23 decide() contract tests (+ shim-parity 29x4)**. The new test
  `test_a_system_program_path_is_not_a_reach_on_every_seat` runs on all four seats: `… | /usr/bin/python3` is
  allowed and opens no scope request; `/usr/bin/cat /etc/hostname` claims only `/etc/hostname`; and
  `curl file:///etc/hostname` is refused and claims `/etc/hostname`. On main's core this test fails 16 checks
  (4 per seat).
- `plugins/_shared/test_gate_core.py`: `control_naming_the_target_directly_is_judged` (pinned 2026-10-05)
  now expects a system-dir interpreter to be allowed. On CI's toolcache interpreter the check is unchanged,
  and it passes on both cores. Run from a scratch copy, 2 checks fail on both cores (`shims_present`,
  `scope_rule_duplication_matches_inventory`). Those 2 need the test to sit in the tree.
- **Own-seat replay** (claude-code's 54,463 recorded commands, grant `path:<ws>/**`, recorded cwd; no
  cross-seat replay): 159 verdicts change.
  - **129 go path -> allow.** Each of these was a peer scope request on main. 58 are a relative path after a
    leading `cd /abs &&`, 46 an absolute system program word (mostly `/usr/bin/grep`), 24 a jq or `gh --jq`
    program, and 1 is a `git show origin/main:<path>` after `cd ~/… &&`.
  - **29 go path -> request.** These are still refused. Each held an unenumerable expansion that main hid
    behind a false path deny, so it now takes #1313's no-request rule.
  - **1 goes allow -> path:** `sqlite3 -readonly file:/home/dp/.hestia/inbox.db?mode=ro`. That is a real read
    of `~/.hestia` that main allowed.
  - Zero URL cases in this corpus. CBP's grant reaches every directory its sessions `cd` into, so the URL shape
    shows only on a seat whose bases are not all granted (McNugget).

## Not covered

- `gh api <endpoint>`'s endpoint is still judged as a relative path. It cannot be a file, and it is refused
  only when `<cwd>/repos/…`'s parent exists, so it is left alone.
- A data position the gate does not know is still judged: other `gh` subcommands' `--jq`, `yq`/`gojq`
  programs, and URL arguments to option values such as `curl --url http://…`. Each needs its own arity check.
- The `cd`/`-C` base is still joined lexically for `..` (pre-existing; the pinned cwd is resolved).

## Not done here

- Applying it. This needs Codex review of this exact digest and dp's approval for the governed apply.
  Delete `held/19952a05….patch` and this README in the commit that applies it.

— cbp-claude
