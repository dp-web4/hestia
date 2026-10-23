# held/: #1241 recut — grep-family patterns judged INSIDE the shell grammar, and declared toolchain roots, NOT applied

| file | sha256 |
|---|---|
| `2a6c9ed0b428119b175d0cc1105db5522d410c6fb71288149fde356d582e3be1.patch` | `2a6c9ed0b428119b175d0cc1105db5522d410c6fb71288149fde356d582e3be1` (base main `3b7690d2`) |

**Files:** `plugins/_shared/hestia_gate_core.py` and its hooks-gt copy and manifests, the new
`tools/gate_tool_roots_and_patterns_test.py`, and one repinned cell in `tools/mrh_scope_differential.py`.
9 files, +382 −20. It supersedes #1241.

## Why

SAGE #368 / #441 hands the one gate the being's **composed** command, so what is judged is what
runs, and dp ruled that a being is judged under its **seat's** workspace (the home). Replayed on
2,187 legion-being calls (2026-10-05), that denied:
- **every sandboxed `check` and every `game`** with "'miniforge3' is not granted": the sandbox's
  `--ro-bind <home>/miniforge3`, its `PATH`, and the interpreter itself;
- **a `search`** with "'[^' is not granted": a fragment of the being's own regex,
  `-e '<home>[^ ]*ft09\.py'`.

Neither is a reach. SAGE #441 is on HOLD for this.

## Why a recut and not #1241 (cbp-claude's review, 2026-10-14)

#1241 rewrote the WHOLE command line to mask pattern operands before the shell-grammar judge (#1232)
ran, and re-quoted `"$(...)"` as an inert `'$(...)'`. On main that admitted acts main refuses:
`grep -n x "$(cat /etc/shadow)"`, `grep x f; echo "$(cat /root/secret)"`, and backticks in a grep
operand. This recut never rewrites the text.

## The change (`hestia_gate_core` only)

1. **The grammar records patterns.** `_outside_candidates` already knows, through `_CMD_SPECS`, which
   word is a grep/rg pattern: the first positional, `-e X`, `-eX`, `--regexp=X`. It now also records
   their **literal values** on `_Found.patterns`.
   - Only for grep-family heads (`_PATTERN_HEADS`: grep, egrep, fgrep, rg, and `git grep`). sed and awk
     share the pattern-first grammar, but their programs read and write files.
   - Only for a word with **no expansion**. A substitution inside a pattern is still lifted out and
     judged like any other command.
   - The judgment of every word is unchanged; `-eX` still calls nothing new.
2. **`git grep` gets grep's grammar after the subcommand** (`_GIT_GREP_SPEC`), so its `-C 3` is context
   lines, while git's own `-C DIR` before the subcommand is still a judged directory.
3. **Passes 1 and 2 (inside the workspace) skip a mention only when it lies inside a recorded pattern
   AND inside no word the grammar judges as a path** (`_only_pattern_text`). `grep '<ws>/x' <ws>/x`
   still judges `<ws>/x`. A line the grammar cannot read skips nothing.
4. **Pass 3 (outside the workspace) is not touched**, so every must-deny row above still denies there.
5. **`HESTIA_TOOL_ROOTS`**, ported from #1241 unchanged:
   - operator-declared toolchain roots, colon- or comma-separated absolute paths;
   - a reach under one is not MRH-scoped in pass 1, and it is judged **after** egress, so a symlink to
     a forbidden target still denies;
   - `/`, a relative path, the workspace, or an ancestor of it is ignored;
   - declared, never inferred.

## Evidence (scratch core through `HESTIA_SCOPE_BATTERY_CORE` / `HESTIA_CONTRACT_OVERLAY`, base `3b7690d2`)

| check | result |
|---|---|
| `tools/gate_tool_roots_and_patterns_test.py` | 38/38 pass |
| the same test on main's core (control) | 7 fail, exactly the positive cells (tool roots, git grep, grep/rg patterns, `-eX`); every must-deny row passes on main too |
| `tools/mrh_scope_differential.py` | one cell off its pin: `744.grep-pattern-compound` (wrong root) deny `'python'` → allow, as cbp predicted. False positives 7 → 6, false negatives 0. Repinned here. |
| `tools/shell_scope_reach_battery_test.py` | 1434 passed, 0 failed |
| `plugins/_shared/test_gate_core.py` | all checks pass |
| `tools/one_gate_decide_contract_test.py` | PASS (24 + shim parity 29x4) |
| `tools/scope_fork_differential_test.py --max-divergences 0` | 0 divergences |
| `tools/closure_read_tool_names_test.py`, `closure_output_writes_test.py`, `shell_grammar_test.py` | OK |
| `tools/hooks_gt.py check` on the post-patch tree (in memory) | clean |
| `git apply --check` on main `3b7690d2` | clean |

**Mutations:**

| mutation | red |
|---|---|
| M1: a pattern covers text an operand also names | 2 |
| M3: `git grep` keeps git's grammar | 2 |
| M4: the tool root is judged before egress | 1 |
| M5: every pattern-first head is exempt (sed, awk too) | 3, the sed `w`/`r` and awk `print >` rows |
| M2: a word with an expansion is recorded as a pattern | 0 |
| M6: an unreadable line skips everything | 0 |

M2 and M6 survive for a stated reason, not a missing test. **Pass 3 refuses both lines independently**:
an unquoted expansion where field splitting can add arguments, and an unreadable line, are unenumerated
there. The rows `grep $X<ws>/other/x …` and the unbalanced quote are in the test, so they stay red if
either layer holds.

**Not run here:** the 2,187-call SAGE replay of 10-05. SAGE #441 reruns it once this is applied.

## After applying

- Set `HESTIA_TOOL_ROOTS` in each being seat's environment (the conda root on Legion).
- Re-measure SAGE #441's replay, then lift its HOLD.
- Close #1241.
- Delete `held/2a6c9ed0…patch` and this README in the commit that applies it.

— legion-claude
