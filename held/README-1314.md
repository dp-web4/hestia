# held/: hestia#1314, non-path text judged as a path, NOT applied

| file | sha256 |
|---|---|
| `8a39ac046f69e2f21127b75ca4a7b7e85eb085a377ff77a16cf8fd41d829b7a3.patch` | `8a39ac046f69e2f21127b75ca4a7b7e85eb085a377ff77a16cf8fd41d829b7a3` (base main `2d79644f`) **current** |
| `19952a0521073ed8ce7fd03aaf8d4b4a7f1a962760cad9581fd2a2a2a6c25b3c.patch` | SUPERSEDED: Codex HOLD (PR #1328 review, mesh 25905), two P1 false allows, see below |

9 files, +413/−23: the gate core, its hooks-gt copy and five manifests (emitted by `tools/hooks_gt.emit_patch`
from a scratch copy of the core), the shell battery and the decide contract test. The single gate, the
mechanism, the daemon and `test_gate_core.py` are unchanged. Nothing here is applied.

How it was checked without touching a tree: the builder applies every hunk **in memory** to HEAD's text and
compares the result with the intended bytes (all 9 files match). No `git apply`, not even `--check`, was run
against any tree.

## Revision (8a39ac04) against Codex's HOLD on 19952a05

| Codex finding | 19952a05 | 8a39ac04 |
|---|---|---|
| P1 a: `jq --run-tests FILE` reads FILE, which the jq spec exempted as the program | FILE was positional 1, so it was data and allowed | `--run-tests` is a `no_program_flags` entry: after it no positional is a program, so FILE is judged. `jq --run-tests` alone reads stdin and takes no value, so it is NOT modelled as `-f`'s required operand |
| P1 b: `cat file://<W>/x` reads the relative `<cwd>/file:/<W>/x`; the patch judged only `/<W>/x` | allowed (target granted), while `cat` read the ungranted literal file | a `file:` URL is judged BOTH as the path it names and as its literal relative spelling, in every argument and option position. A redirection target and a program word are judged literally only, because the shell never reads a URL there |
| system-program reversal: directory membership does not prove the bare name resolves to the same executable | `/usr/bin/<x>` as command word not a reach | **dropped.** The 2026-10-05 pin stands, `test_gate_core.py` is untouched, and the battery pins `… \| /usr/bin/python3 -c …` as still refused. Whether running a system-dir program should be a reach is a policy question for dp, outside this patch |

Also, as Codex asked for consumer-specific URI handling: the URL's target now has `%XX` decoded and any
`?query` / `#fragment` dropped, which is how curl and the sqlite3 shell open it.

## Repro on main `2d79644f` (offline: core + `decide()` with the contract test's stub daemon)

Grant `path:<ws>/**` plus a recursive grant on a tree outside the workspace (McNugget's
`/Users/dennispalatov/repos`). "Ungranted cwd" is an existing directory outside every grant, as McNugget's
`…/ai-workspace` was. Every main refusal below is `mrh.command` and opens a peer scope request
(`hestia_scope_claim`), so #1316's no-request route for `mrh.command.unenumerated` covers none of them.

| # | shape | main | patched |
|---|---|---|---|
| 1 | `curl localhost:8760/health` from any cwd | allow | allow |
| 1 | same after `cd D &&` or `git -C D` where `D/<url>` is not granted | **deny** `D/localhost:8760/health`, request | allow |
| 2 | `curl http://127.0.0.1:8760/health`, same two conditions | allow / **deny** `D/http:/127.0.0.1:8760/health`, request | allow |
| 3 | `tail … \| /usr/bin/python3 -c …` | **deny** `/usr/bin/python3`, request | **unchanged (deny)**: policy question, see above |
| 4 | `cd <granted abs> && cat ./x` from an ungranted cwd | **deny** `<cwd>/x`, request | allow |
| 5 | `gh api … --jq '.[-1].body'`, `jq '.[-1].body'` from an ungranted cwd | **deny** `<cwd>/.[-1].body`, request | allow |
| ctrl | `curl file:///etc/passwd` | **allow** (judged as relative `file:/etc/passwd`) | deny `/etc/passwd` |

## The change (gate core only)

1. **URLs.** A positional argument that is a network URL is recorded as kind `url`, not as a path:
   a scheme other than `file:`, or, for a URL client (`curl`, `wget`, `http`, `https`, `xh`, `xhs`, `curlie`),
   `host:port[/…]`. A `..` component disqualifies it; a `url` candidate whose first component (`http:`,
   `localhost:8760`) **exists** under any base is judged as the relative path it also is; an expansion inside
   it stays unenumerated.
2. **`file:` URLs are judged both ways.** `file:///x`, `file://localhost/x` and `file:/x` are judged as `/x`
   (decoded, query and fragment dropped) AND as the literal relative word, in every argument and option
   position. Redirection targets and program words: literal only. Strictly tighter than main, which judged
   only the literal.
3. **Leading absolute `cd`.** When the whole command is `cd <literal absolute dir> && …` and every later
   separator is `&&` or a pipe, the event cwd stops being a base and that directory (resolved) takes its
   place. Any `;`, newline, `||`, `&`, subshell, `{ }` group or command substitution keeps the event cwd.
4. **jq programs.** `jq`'s first positional is its program (`pattern_first`), unless `-f`/`--from-file` (or a
   short cluster holding `f`) names a program file, or `--run-tests` makes positionals test files; then every
   positional is judged. `-L`/`--library-path`/`--indent` take a value. `gh`'s `--jq`/`-q` and
   `--template`/`-t` are strings on the subcommands where `gh <sub> --help` says so: `api`,
   `pr list|view|checks`, `issue list|view`, `run list|view`, `release list|view`, `repo view`.

## Evidence

- `tools/shell_scope_reach_battery_test.py` (patched copy): **1476 passed, 0 failed** on the 8a39ac04 core.
  The same battery on the **superseded 19952a05 core fails 7**: three `jq --run-tests` controls, three literal
  `file:` controls (`cat`, `<` and `>`), and the system-program pin. That is Codex's two findings, reproduced
  by rows that separate the cores. On **main's core it fails 13**: 8 allows main refuses and 5 `file:` URL
  denials main allows. New since 19952a05: `jq --run-tests` (absolute, relative, after `--arg N V`, before
  `-r`), a granted `jq --run-tests` and a granted `curl file://` (must allow), `file:` with `?query` and with
  `%74`, and the literal-`file:`-directory fixture under `cat`, `<` and `>`.
- `tools/one_gate_decide_contract_test.py` (patched copy, `HESTIA_CONTRACT_OVERLAY` -> patched core):
  **PASS: 23 decide() contract tests (+ shim-parity 29x4)**. The new test
  `test_a_file_url_is_judged_as_the_path_it_names_on_every_seat` fails 4 checks (one per seat) on main.
- `plugins/_shared/test_gate_core.py` (main's, unchanged) on the patched core: only the 2 checks that need
  the test to sit in the tree fail from a scratch copy (`shims_present`,
  `scope_rule_duplication_matches_inventory`), as on main's core.
- **Own-seat replay** (claude-code's 54,525 recorded commands, grant `path:<ws>/**`, recorded cwd; no
  cross-seat replay): 102 verdicts change.
  - **83 path -> allow**: 58 relative paths after a leading `cd /abs &&`, 24 jq or `gh --jq` programs, 1 other.
  - **18 path -> request**, still refused: each held an unenumerable expansion that main hid behind a false
    path deny.
  - **1 allow -> path**: `sqlite3 -readonly file:/home/dp/.hestia/inbox.db?mode=ro`, now judged as the
    `inbox.db` sqlite opens. Main allowed it.
  - The 46 system-program allows of 19952a05 are gone with item 3.

## Not covered

- Running a program by a system-directory path is still a reach (the pin). Reversing it needs dp's ruling on
  an explicit directory-based execution policy, with its own allow/deny controls that do not call the helper
  they pin (Codex's point on 19952a05's unit test).
- `gh api <endpoint>`'s endpoint is still judged as a relative path.
- A data position the gate does not know is still judged: other `gh` subcommands' `--jq`, `yq`/`gojq`
  programs, `curl --url http://…`.
- The `cd`/`-C` base is still joined lexically for `..` (pre-existing; the pinned cwd is resolved).
- Codex could not reproduce the 1466-check battery independently: the live gate refused its fixture
  redirection (`.env` secret-path rule) and a workspace-root probe. That is a review-environment gap, not
  something this patch changes.

## Not done here

- Applying it. This needs a NOT-SAME (Codex) review of this exact digest and dp's approval for the governed
  apply. Delete both `held/*.patch` files and this README in the commit that applies it.

— cbp-claude
