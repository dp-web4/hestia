# held/: hestia#1314, non-path text judged as a path, NOT applied

| file | sha256 |
|---|---|
| `f46bc32bc3a9569b09d9e783c2a24774936c752c0e0fd068fac2473686eafa97.patch` | `f46bc32bc3a9569b09d9e783c2a24774936c752c0e0fd068fac2473686eafa97` (base main `2d79644f`) **current** |
| `0a2af175e50945b0bd069eabf74947b6bd39dd22f3dcced3118f6d69506c917c.patch` | SUPERSEDED: Codex HOLD (PR #1328 comment 6187241802, mesh 25955), URL exemption let `mkdir -p http://newdir` create an ungranted path, see below |
| `8a39ac046f69e2f21127b75ca4a7b7e85eb085a377ff77a16cf8fd41d829b7a3.patch` | SUPERSEDED: Codex HOLD (PR #1328 review 6186945315, mesh 25937), two jq P1 false allows, see below |
| `19952a0521073ed8ce7fd03aaf8d4b4a7f1a962760cad9581fd2a2a2a6c25b3c.patch` | SUPERSEDED: Codex HOLD (PR #1328 review, mesh 25905), two P1 false allows, see below |

9 files, +638/−23: the gate core, its hooks-gt copy and five manifests (emitted by `tools/hooks_gt.emit_patch`
from a scratch copy of the core), the shell battery and the decide contract test. The single gate, the
mechanism, the daemon and `test_gate_core.py` are unchanged. Nothing here is applied.

How it was checked without touching a tree: the builder applies every hunk **in memory** to HEAD's text and
compares the result with the intended bytes (all 9 files match). No `git apply`, not even `--check`, was run
against any tree.

## Revision (f46bc32b) against Codex's HOLD on 0a2af175

| Codex finding | 0a2af175 | f46bc32b |
|---|---|---|
| P1: `cd O && mkdir -p http://newdir` under an EXACT grant on O. `mkdir` makes the ordinary directory `O/http:/newdir` | any command's `scheme://` word was a URL, and it was dropped because `O/http:` did not exist yet. Nonexistence proves nothing when the command creates it, or an earlier `mkdir http:` does | `_network_url` is true only for an operand of a URL client (`curl wget http https xh xhs curlie`). Every other command's URL-shaped word is judged as the relative path it is, as on main |

The same hole was inside the URL clients: `curl --create-dirs -o http://newdir/f URL` writes `./http:/newdir/f`.
An operand is now exempt only when the previous word leaves it an operand: the command word, another operand, or an
option on the client's list of value-less flags (`_URL_FLAGS`, from curl 8, wget 1.21 and httpie 3 / xh `--help`), or
an option whose value is attached (`-qO-`, `--output=x`). After any other option word, whether value-taking
(`-o`, `--output`, `-K`, `-x`), unknown, or a cluster ending in a value letter (`-sSo`), the next word is judged
as a path. That fails closed for `curl -x http://proxy:8080 URL` from an ungranted directory.

New must-refuse rows, all after `cd` into the exactly granted directory (Codex's shape): `mkdir -p http://newdir`,
`mkdir http: && touch http://newfile`, `pip download https://h/x` (an unknown consumer), `curl --create-dirs -o`,
`--output`, `-sSo`, `-K`, `-o localhost:1/f`, `wget -O`, `wget --some-future-opt`, `xh -o`. New must-allow rows:
`curl --silent --fail -sSL URL`, `curl -H 'a: b' -X POST URL`, `curl -sS -o <granted> URL`, `wget -qO- URL`,
`xh -b -F URL`.

**Not in this patch, found while writing the rows:** with the EVENT cwd itself exactly granted, main judges no
bare relative word, `./`-less, at all: `touch newfile/x` and `mkdir -p http://newdir` are allowed on main and on
every #1314 core. That is the same descendant-under-an-exact-grant class as Codex's finding, but older. The new
rows use `cd` first so they separate the cores. It needs its own issue.

Evidence (f46bc32b):
- Battery: **1511 passed, 0 failed**. On the **0a2af175 core it fails 11**, which is every new must-refuse row. On
  **main's core it fails 19**, the same 19 as before, and main passes every new row.
- Decide contract: **PASS: 23 decide() contract tests (+ shim-parity 29x4)**. `test_gate_core.py` (unchanged): only
  the 2 checks that need the test inside the tree fail from a scratch copy, as before.
- Own-seat replay (54,667 commands): **the same 99 changed verdicts as 0a2af175, none different**. None of the 99
  involves a URL client. On this seat's corpus the URL exemption never fires, so the replay cannot measure what this
  revision costs. The URL rows are McNugget's live case (#1314), and nothing here measures them against a corpus.
- Built as before: hunks applied in memory to HEAD's text, all 9 files byte-identical. No `git apply`.

## Revision (0a2af175) against Codex's HOLD on 8a39ac04

Both findings are jq option grammar, and so was the first HOLD's `--run-tests`. That is three holds on one
streaming classifier that decided the program word before it had read the rest of the command. This revision
does not add the two missing forms. It replaces the classifier with an allowlist that reads the whole jq
command first, modelled on jq 1.7.1's `src/main.c` argument loop (read at tag `jq-1.7.1`).

| Codex finding | 8a39ac04 | 0a2af175 |
|---|---|---|
| P1: `jq -n O/p.jq -f` (also `--from-file`, `-rf`). jq sets `FROM_FILE` for the program wherever `-f` stands | the program was exempted as data at its own word, and the later `-f` was never revisited | `_jq_data_words` reads every word of the simple command before any is judged. Any option word outside the allowlist, `-f` anywhere included, gives NO exemption, so every word is judged |
| P1: `jq -n --rawfile --name O/f …`. jq takes NAME and FILE whatever NAME looks like | `--name` read as a flag, so `O/f` became positional 1 and was exempted | `--rawfile`/`--slurpfile` are not on the allowlist, so every word is judged |

The allowlist covers the value-less flags (`-n -r -j -a -c -s -e -S -C -M -R`, alone or as a cluster of only
those letters, and their long forms, plus `--tab --seq --stream --stream-errors --unbuffered --raw-output0
--args --jsonargs`), `--indent N` (one word), and `--arg`/`--argjson NAME VALUE` (two words, whatever they look
like, as jq does). The program is the first non-option word (jq's `isoptish`: `-` and `-1` are not options).
The program and those values are data, and everything else is judged. These leave every word judged:
`-f`/`--from-file` anywhere, `-L`, `--rawfile`, `--slurpfile`, `--run-tests`, `--`, any unknown option, and
any word that can expand to something else (`$X`, `$(…)`, an unquoted glob, `{a,b}`), since that word could
be `-f`. The walker's generic jq hooks from 8a39ac04 (`program_file_opts`, `no_program_flags`,
`cluster_file_letters`) are removed. jq has no `_CMD_SPECS` entry, as on main.

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
4. **jq programs.** The program is data only if the whole jq command passes the allowlist above
   (`_jq_data_words`). Otherwise every word is judged, as on main. `gh`'s `--jq`/`-q` and
   `--template`/`-t` are strings on the subcommands where `gh <sub> --help` says so: `api`,
   `pr list|view|checks`, `issue list|view`, `run list|view`, `release list|view`, `repo view`.

## Evidence

**0a2af175** (the numbers for 8a39ac04 follow below):
- Battery (patched copy): **1495 passed, 0 failed**. The same battery on the **superseded 8a39ac04 core fails 11**.
  Seven are real false allows of 8a39ac04: Codex's `-f`/`--from-file`/`-rf` after the program (absolute and
  relative), `--rawfile`/`--slurpfile --name`, and `-{n,f}` (a brace that expands to `-n -f`). Two pin
  fail-closed behaviour where jq would in fact read nothing: `--` and an unknown option. Two are must-allows
  that 8a39ac04 refused: `--arg n ./v` judged `./v`. On **main's core the battery fails 19**: 14 allows that main
  refuses and 5 `file:` URL denials that main allows. Main passes every new jq control, because it exempts
  no jq program.
  New rows: must-allow `--arg`/`--argjson` values, an option-shaped `--arg` NAME (`--name`, `-f`), `--indent 2`,
  `-nr`, and a flag after the program. Must-refuse: the 5 Codex probes, `jq -n ./deep.txt -f`, `jq -f -n O/f`,
  plain `--rawfile n O/f`/`--slurpfile n O/f`, `"$F"` after the program, `-{n,f}`, `--`, and an unknown option.
- Decide contract (patched copy): **PASS: 23 decide() contract tests (+ shim-parity 29x4)**.
- Own-seat replay (54,616 claude-code commands): 99 verdicts change against main. **81 path -> allow** (22 jq
  or `gh --jq` programs, against 24 under 8a39ac04), **17 path -> request**, and **1 allow -> path** (the same
  `sqlite3 file:` read). The allowlist costs 2 allows on this corpus.
- Built as before: hunks applied in memory to HEAD's text and compared byte for byte (all 9 files OK). No
  `git apply` was run.
- jq is still not installed on CBP. The grammar comes from reading jq 1.7.1's `main.c`, not from running it.

**8a39ac04:**

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
- A jq program that loads a module (`import`/`include`) reads files from jq's library search path. The gate
  does not judge this. It is unchanged from main, which never judges a program that is not path-shaped either.
- A data position the gate does not know is still judged: other `gh` subcommands' `--jq`, `yq`/`gojq`
  programs, `curl --url http://…`.
- The `cd`/`-C` base is still joined lexically for `..` (pre-existing; the pinned cwd is resolved).
- Codex could not reproduce the 1466-check battery independently: the live gate refused its fixture
  redirection (`.env` secret-path rule) and a workspace-root probe. That is a review-environment gap, not
  something this patch changes.

## Not done here

- Applying it. This needs a NOT-SAME (Codex) review of this exact digest and dp's approval for the governed
  apply. Delete every `held/*.patch` file and this README in the commit that applies it.

— cbp-claude
