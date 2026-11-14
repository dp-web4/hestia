# held/: hestia#1583, a one-positional cp/install/rsync/ln reads as no-write though one word can expand to SRC DEST. NOT applied

| file | sha256 |
|---|---|
| `34ff3b77795bdfc4a538aee9caf6db2e0cedee6c4c2301130b518871a381b0df.patch` | `34ff3b77795bdfc4a538aee9caf6db2e0cedee6c4c2301130b518871a381b0df` (base main `d577bcf4`) |

## The defect

`_command_write_targets` takes the destination of `cp` / `install` / `rsync` (and `ln`) as the last positional,
only when there are two or more: `return [pos[-1]] if len(pos) >= 2 else []`. A single word can become source
and destination at run time, and the destination can be a closure file:
- a glob: `cp G/x*`, `?`, `[..]`;
- a brace: `cp G/x{.py,_test.py}`;
- an unquoted `$X` (bash), `"$@"` after `set --`, `"${arr[@]}"`, `$( )`.

On main all of these classify as read.

`ln` has the identical line and the identical gap, which the issue doesn't name: `ln -f G/x*` replaces the last
match with a link to the first.

## The change (`hestia_governance_closure.py`)

- **New helper `_last_positional_dest(pos)`.** Both the cp/install/rsync branch and the ln branch now call it.
- **The inverted test, as suggested on the issue.** A single positional names no destination only when it is
  made entirely of plain path characters (`[A-Za-z0-9_./~+@%,:= -]`). Anything else is out of grammar, which
  is a write iff closure vocabulary appears in the line. No expansion form needs listing.
- **Unchanged:**
  - `mv` (every operand was already a write);
  - `-t DIR`;
  - two or more positionals;
  - a plain single word;
  - `cp --help`;
  - a one-word glob that names nothing in the closure (out of grammar, no vocabulary, so not a write).

## Tests: `tools/closure_one_positional_cp_test.py` (new, 27 rows)

| suite (McNugget, base `d577bcf4`) | patched | main |
|---|---|---|
| `closure_one_positional_cp_test` | **PASS 27/27** | FAIL 16/27 |
| the other 18 closure-importing tests (`tools/`, `plugins/_shared`), base vs staged | same result per test | same result per test |

On main, all 17 must-write rows are read except the backtick row, which was already write. The 10 controls
pass on both. Of the 18, two fail identically on main and on the patched classifier on this Mac:
`shell_grammar_test`'s real-shell differential and `one_gate_decide_contract_test`'s kimi row.

## Not covered: zsh-only glob forms

`cp G/f<1-2>` (numeric range) and `cp G/(a|b)` (alternation) overwrite under zsh 5.9, the shell Claude Code runs
on macOS seats. They still read after this patch. The tokenizer splits them the way bash would, as a `<`
redirect and as a subshell, so the cp branch never sees the word. That is a dialect gap in the shell model
(see the McNugget comment on #1583), not in this branch. `${=X}` is covered (it contains `$`).

## Apply

```
python3 held/build-1583/build.py <worktree at main> <EMPTY out dir>   # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/closure_one_positional_cp_test.py                       # PASS: 0 failing
```

The patch touches the closure classifier, its hooks-gt copy, and the hooks-gt manifests (`_shared` and the four
harnesses). All of these are governed paths. It also adds the test. It edits the same file as #1599 (#1598), in a
different branch of `_command_write_targets`. Both rewrite the hooks-gt manifests, as do #1597 and #1600, so
re-cut whichever lands later.
