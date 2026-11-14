# held/: hestia#1595, the gate judges pgrep / pkill PATTERN operands as paths. NOT applied

| file | sha256 |
|---|---|
| `d4495ec4347394cfa0e8a506a9b1b2f7cc8ba8e5edf6d26841859c82b7cb65db.patch` | `d4495ec4347394cfa0e8a506a9b1b2f7cc8ba8e5edf6d26841859c82b7cb65db` (base main `d577bcf4`) |

## The defect

`pgrep -f PAT` and `pkill -f PAT` match a regex against running processes' command lines and never open
it. `mrh.command` judged that pattern as a filesystem path. A pattern spelled like an absolute path outside
the grant was refused, and a scope request opened for it.

**Live on McNugget (claude-code, 2026-11-14 01:39:40Z):**
- act: `pgrep -fl '/opt/homebrew/bin/hestia'`
- deny: chain pos 55835, rule `mrh.command`
- opened: scope-e658654729f0

The member was finding the daemon's PID by its command line, which is the normal way to do it. The grep
family already has this exemption (#1241 recut, `_PATTERN_HEADS`, `_CMD_SPECS`). pgrep and pkill weren't in it.

## The change (`hestia_gate_core.py` only; no logic outside the per-command grammar)

1. **Same grammar as grep.** `pgrep` and `pkill` get a `_CMD_SPECS` entry (`_PGREP_SPEC`) and join
   `_PATTERN_HEADS`. The first positional is the pattern: it is recorded and not judged.
2. **The one file operand is still judged.** `-F` / `--pidfile` is a `file_opts`. Its value is judged, and
   any later positional is too.
3. **Option values don't shift the pattern position.** `value_opts` lists the union of the BSD (macOS) and
   procps (Linux) value options: `-u root`, `-P 1`, `-t tty`, and so on.
4. **Signal words are flags (`signal_words`).** pkill's `-HUP`, `-9` and `-SIGTERM` are matched before the
   generic cluster scan. Without this, `-HUP` reads as `-H` followed by `-U` with the value `P`.
5. **Unchanged:**
   - an UNQUOTED glob in the pattern position is still a directory read and is judged;
   - a substitution in the pattern is still lifted out and judged.

## Tests: `tools/gate_pgrep_pattern_test.py` (new, 15 rows)

- **9 must-allow rows** (the pattern is text):
  - the #1595 act;
  - unquoted;
  - pkill;
  - an ungranted in-workspace dir;
  - an option value before the pattern;
  - `-HUP`, `-9`, `-SIGTERM`;
  - in a pipeline.

  All 9 **fail on main**.
- **6 must-deny rows:**
  - `-F <outside>`, `--pidfile=<outside>`, `-F<outside>` attached;
  - an unquoted glob;
  - `cat` after `;`;
  - `$(cat <outside>)` in the pattern.

  These pass on both cores.

| suite (McNugget, base `d577bcf4`) | patched core | main's core |
|---|---|---|
| `gate_pgrep_pattern_test` | **PASS 15/15** | FAIL 6/15 (the 9 rows above) |
| shell battery | 1431 / 3 | 1431 / 3 (the same 3 macOS `TMPDIR` rows) |
| the other 30 core-importing `tools/` and `plugins/_shared` tests | same result per test | same result per test |

The pre-existing failures on main, identical on both cores, are all on macOS:
- the battery's 3 `TMPDIR` rows;
- 2 rows of `gate_grep_patterns_and_toolchain_grant_test`;
- one row of `one_gate_decide_contract_test`.

## Apply

```
python3 held/build-1595/build.py <worktree at main> <out dir>     # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/gate_pgrep_pattern_test.py                           # PASS: 0 failing
```
The patch touches the gate core, its hooks-gt copy, and the hooks-gt manifests (`_shared` and the four
harnesses). All of these are governed paths. It also adds the test.
