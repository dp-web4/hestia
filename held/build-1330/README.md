# held: #1330, prose is not a path. **NOT applied.**

Patch: `held/2e68383c4be733feaa987235790766e0ec2c8e8385c441faf35601858b1fad2d.patch` (base `2b3d0ca2`). It covers the gate core, plus the hooks-gt mirror and the 5 manifests.

## The defect
Gate 1a (`egress_blobs`) sweeps the **whole command string** for the innate forbidden tokens by substring. So `gh issue create --body "...the workspace credentials file..."` is refused `egress.secret` on a word in the issue's text. That was measured on Legion on 10-15 and still happens on `2b3d0ca2` (10-27). Every security write-up therefore goes through `--body-file`, the pattern the law discourages everywhere else.

## The rule
`egress_command_text(command)` is what Gate 1a sweeps now. It's every word of the command except a **literal** value of a flag whose program's own contract makes it text:

| program | flags |
|---|---|
| `gh` | `--body`/`-b`, `--title`/`-t`, `--comment` (also the `--flag=value` form) |
| `git` | `-m`, `--message` (commit, tag) |

- **Not literal:** a value holding `$` or a backtick could expand to a secret's contents, so it stays swept.
- **Not tokenizable** (an unbalanced quote): the raw command is swept whole, as before.
- **Segments:** the line is split at `;` `&&` `||` `|` `&` `(` `)`, so a read chained after a prose segment is still swept.
- **Everything else is unchanged:**
  - interpreter `-c`/`-e` code;
  - quoted paths;
  - `--body-file <path>`;
  - redirections;
  - env assignments.

An earlier draft, "a quoted argument with whitespace is prose", was **rejected**. `sh -c "cat <key>"` and `python3 -c "open(...)"` would have passed under it. See the issue thread.

## Evidence (revised core served as `hestia_gate_core`, `run_overlay.py`)
- `egress_prose_test.py`: **PASS** on the revised core (5 prose rows allowed, 7 control rows still `egress.secret`). On main's core it **fails exactly the 5 prose rows**.
- The controls:
  - a real read of a key path;
  - `sh -c`;
  - `python3 -c`;
  - `--body "$(cat …)"`;
  - a read chained after prose;
  - `--body-file <key>`;
  - an unbalanced line.
- Same exit code under both cores:
  - `test_gate_core` (all checks)
  - `shell_grammar` (4 suites)
  - mechanism 34
  - `seat_gate_boundary` 17×4
  - sprintD 91
  - sprintE 9
  - sprintF 10
  - `governance_closure` 39
  - `cross_harness` 4/4
  - `grant_modes` 17
  - `floor_read_only` 8
  - `nonexistent_path` 8
  - `gate_verdict`
- Shell-scope battery: **1434 / 0** on the revised core (`HESTIA_SCOPE_BATTERY_CORE`; it loads the core by path, so the overlay alone doesn't reach it).
- `one_gate_decide_contract_test` fails identically under both cores: two scope-sink rows, an artifact of the worktree living under `/tmp`. Unrelated.

## Running it
- Cut / re-cut after main moves: `build_1330.py <worktree> <out>`. It reads the change from `source-1330.diff`, which `transform_1330.py` produces from HEAD's blob.
- Tests: `run_overlay.py <worktree> <out> <test file>`. Pass an empty `<out>` to run the control against the worktree's own core.

**After the governed apply:** `egress_prose_test.py` moves to `tools/` and loads the real module, as #1411's test did.
