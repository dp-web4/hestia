# held/: hestia#1594, gate passes 1 and 2 judge quoted data heredoc bodies that pass 3 strips. NOT applied

| file | sha256 |
|---|---|
| `8e5b526c102c9cc861b4ae9b5ff821bdc50e9e096d04204929319c9c9fb211a4.patch` | `8e5b526c102c9cc861b4ae9b5ff821bdc50e9e096d04204929319c9c9fb211a4` (base main `d577bcf4`) |

## The defect

`command_scope_reach` reads two different texts:
- **Pass 1** (the workspace-prefix scan) and **pass 2** (relative tokens) scan the RAW command.
- **Pass 3** judges `_strip_data_heredocs(cmd)`.

So a quoted data heredoc body was text to pass 3 and paths to passes 1 and 2. In the live case, prose quoting
`~/repos/..` in a `cat > notes.md <<'EOF'` body was refused as `mrh.command`. That opened **scope-577f201a0fce for
the home directory** (McNugget, 2026-11-13).

## The change (`hestia_gate_core.py`, `_command_scope_reach_one`)

- **One text for all three passes.** Passes 1 and 2 scan `scan = _strip_data_heredocs(cmd)`, the text pass 3
  judges.
- **What stays judged.** That function keeps a shell-run body, an interpreter's path literals, and every `$( )` in an
  unquoted-delimiter body, so these are still judged.
- **Unreadable heredocs.** If the function cannot read a heredoc, passes 1 and 2 keep the raw text, as before.
  Pass 3 refuses that act as unenumerated anyway.
- **Unchanged.** `_grammar_patterns` still reads the full command.

## Tests: `tools/gate_heredoc_inside_passes_test.py` (new, 13 rows)

- **6 must-allow rows**, all refused on main:
  - `<ws>/..` in a body;
  - an ungranted `<ws>` path in a body (pass 1);
  - an ungranted relative path in a body (pass 2);
  - `"EOF"` and `\EOF` delimiters;
  - `tee` as the consumer.
- **7 must-deny rows**:
  - `sh <<EOF` runs it;
  - a `python3 <<EOF` path literal;
  - `$( )` in an unquoted body;
  - a command chained on the heredoc line;
  - an operand on the heredoc line;
  - a command after the terminator;
  - `<ws>/..` outside any heredoc.

| suite (McNugget, base `d577bcf4`) | patched | main |
|---|---|---|
| `gate_heredoc_inside_passes_test` | **PASS 13/13** | FAIL 7/13 (the 6 rows above) |
| the other 30 core-importing tests (`tools/`, `plugins/_shared`) | same result per test | same result per test |

On this Mac, 5 of those 30 tests fail on main and fail identically on the patched core:
- the shell battery's 3 macOS `TMPDIR` rows;
- 2 rows of `gate_grep_patterns_and_toolchain_grant_test`;
- `one_gate_decide_contract_test`'s kimi row;
- `public_boundary_test`'s codex identity row.

## Apply

```
python3 held/build-1594/build.py <worktree at main> <EMPTY out dir>   # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/gate_heredoc_inside_passes_test.py                      # PASS: 0 failing
```
The patch touches the gate core, its hooks-gt copy, and the hooks-gt manifests (`_shared` and the four harnesses).
All of these are governed paths. It also adds the test. It edits the same core as #1597 (#1595), in a different
function, but both rewrite the hooks-gt manifests: re-cut whichever lands second.
