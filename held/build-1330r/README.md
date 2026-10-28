# held: #1330 revision, prose keyed on the parsed command. **NOT applied.**

Patch: `held/6b4c2636415fdc62e7ceba4153d2293f994c435edea95987698c7fbd800dc2a8.patch`. Its base is `4659aba6`, the applied #1330 core on this branch. It covers the gate core, plus the hooks-gt mirror and the 5 manifests.

## The defect (Nova's exact-head review of `4659aba6`)
`_PROSE_FLAGS` was keyed on the **program** alone, so `-m` counted as prose under every `git` subcommand. `git checkout -m` is `--merge`, so in `git checkout -m ~/.ssh/id_ed25519` the key path was dropped from the innate `egress.secret` sweep. The same class covers:
- `gh pr checkout -b` (a branch);
- `gh repo create -t` (`--team`);
- `gh pr review --comment` (a boolean).

A second hole has the same root: a prose flag that is **itself an option's value**. In `git commit --author -m ~/.ssh/x`, git reads `-m` as the author and the key as a pathspec.

On the applied core, `tools/egress_prose_test.py` with the new rows shows:
- 6 red rows are `allow`ed outright;
- 5 more are caught only by the later scope check (`mrh.command`), not by the innate rule;
- 1 real prose form is still refused (`gh issue close -c`).

## The rule
- **Keyed on the command.** `_PROSE_FLAGS[(prog, *subcommand)] = (prose flags, the options of that command that take no value)`. That's 9 `gh` subcommands plus `git commit` and `git tag`. The flags were read from `gh <cmd> --help` and `git <cmd> -h` on 10-28.
- **Resolving the subcommand.** Words after the program are read as the subcommand. Before it, git's own `-C <v>`, `-c <v>`, `--no-pager`, `-P` and `--no-optional-locks` are allowed. Any other option there leaves the command unresolved, and nothing in the segment is exempt.
- **When a prose flag counts.** Only when the word before it cannot be an option waiting for its value:
  - a non-option word;
  - a `--x=y` word;
  - an option on that command's no-value list.

  Anything else (an unknown option, `--author`, `-R`) means the segment is swept as written.
- **`--` ends the exemptions** for the rest of its segment.
- **Unchanged:** segment breaks, the literal-only rule (`$` or a backtick is swept), the unparseable-line fallback, env assignments, and the `--flag=` form (now under the same command and prev-word rules).

## Evidence (revised core served as `hestia_gate_core`)
- `tools/egress_prose_test.py` (31 rows; lands with the apply): **PASS** on the revised core with 13 prose and 18 control rows. On the applied core, the 12 rows above fail.
- `plugins/_shared/test_gate_core.py` via `run_overlay.py`: all checks pass.
- Shell-scope battery (`HESTIA_SCOPE_BATTERY_CORE`): **1434 / 0**.

## Rebuild
```
python3 held/build-1330r/transform_1330r.py <worktree>        # source-1330r.diff from HEAD's core + new_block.py.txt
python3 held/build-1330r/build_1330r.py <worktree> <out dir>  # core_rev.py + <sha256>.patch, verified
```
