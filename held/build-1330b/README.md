# held: #1330, second half — heredoc data and quote-aware literals. **NOT applied.**

Patch: `held/bcbaeef31a72d2f2c7e6ab9baaf34c210af4383806605894a61f23da4974dc9f.patch`: the gate core, plus the hooks-gt mirror and the 5 manifests. Its governed files are based on `4a775cd1` (the build prints the branch head, which only adds `held/` files).

| lineage | sha256 | status |
|---|---|---|
| `held/lineage/469b4315…patch` | `469b43154db19c56b1c3ee7e04db4022994e4df7aed666f7f240855335e1cb46` | **superseded**: nomad's round 2 found that a lone `gh` isn't inert. `gh alias set --shell` + the alias runs shell, and `gh pr create`/`checkout` run git, and git runs hooks. Reference only |
| `held/lineage/eb2db327…patch` | `eb2db3275127414d6b175029400e4cdecd52686b64970f8ca77fe8d781a0ece4` | **superseded**: nomad's review found three heredoc shapes that got a real secret read past it (bash ran each), plus a softer fourth. Reference only |

## What #1427 left swept
#1427 made Gate 1a skip a **literal** prose value of `gh --body/--title/--comment` and `git -m`. Two shapes still refused `egress.secret` on a word in prose. Both were measured on McNugget 2026-10-31 (hestia `242824cf`), on mcnugget-claude's own issue filing:

1. **Markdown code in a prose value:** `--body "… \`credentials\` …"`, or `--body '… `x` …'`. shlex drops the quoting, so `_literal()` saw a backtick the shell never expands.
2. **Heredoc data:** `cat > notes.md <<'EOF'` with "rotating the credentials" in the body. The body of a quoted-delimiter heredoc written by `cat` is never run or expanded. The same bytes written with the Write tool aren't swept, because a local file's contents are not egress.

## The rule
**`_shell_liveness(command, words)`** decides, per shlex word, whether the **shell** would expand anything: an unescaped `$` or backtick outside single quotes, with `\\` read as one backslash (so `"\\`x`"` is live). It's used **only when its words equal shlex's exactly**; on any difference, `_literal()` decides as before.

**`_egress_heredoc_data_removed(cmd)`** drops a heredoc body only when **every** condition below holds. Otherwise the command is swept exactly as written. The governing principle, from nomad's review: *the gate ending the body later than bash is the unsafe direction*.
- **Exactly one heredoc** in the command, and it is **quoted** (`<<'W'`, `<<"W"`, `<<\W`, `<<-` forms).
- Its delimiter word is followed only by a space, a tab or the end of the line. (`<<'EOF'x` is `EOFx` to bash.)
- **No carriage return** anywhere in the command (`'EOF'\r` is a different word to bash).
- **No backslash ends the heredoc line.** Bash continues it: `<<'EOF' \` followed by `; cat key` is a command.
- The consumer is exactly **`cat` or `tee`**, and the line before it opens no `(`, `{`, `$(` or backtick, so `(cat <<'EOF' …) | sh`, `{ …; } | sh` and `x=$(cat <<'EOF' …)` followed by `eval` are all swept.
- The rest of the heredoc line holds no `| ; & \` $ ( ) < { }`.
- **No earlier line** holds `exec`, `>(` or `<(` (for example `exec > >(sh)` before a `cat`).
- **Every later line** is empty, or **one body-publishing `gh` command that names its repo**: `gh issue create|comment|edit` or `gh pr comment|review|edit` with `-R`/`--repo`, optionally piped into `tail`, `head` or `wc`. Writing a file and running it in the same act is not the Write-then-Bash split the premise rests on, so the body stays swept. That covers `sh s.sh`, `. ./s.sh`, `./s.sh`, `make`, and `git commit` running a hook. Also excluded:
  - `gh alias set --shell` followed by the alias;
  - `gh extension`;
  - `gh pr create|checkout|merge` and `gh repo sync`, which run git, and git runs hooks;
  - `gh api`, whose `{owner}` placeholders resolve through git;
  - any gh line without `-R`/`--repo`, since gh then asks git which repo it is in, and the heredoc may have written `.git/config`;
  - `git commit -F`.

The heredoc's own line and every later line are always swept.

**Unchanged:** interpreter `-c`/`-e`, shell and interpreter heredocs, **unquoted** heredoc bodies, paths, redirections, `--body-file`, and every #1427 control.

## Evidence (revised core served as `hestia_gate_core`)
- **`held/build-1330b/egress_prose2_test.py`: PASS on the revised core** (12 prose rows allowed, 38 control rows `egress.secret`). On main's core it **fails exactly the 12 prose rows** and denies all 38 controls, so every control is a case today's gate already catches.
  - Nomad's breaks: `<<'EOF' \` + `; cat`, `<<'EOF'\` + `&& cat`, `<<'EOF'x`, and write-then-`sh`.
  - Nomad's round 2: `gh alias set --shell` + the alias, a hook + `gh pr create`, a hook + `gh pr checkout`, a `GH_PAGER` prefix. Plus the author's: `gh` without `-R` after a `.git/config` write, `gh api`, and `gh extension`.
  - Further breaks the author found after nomad's first review:
    - a CR after the delimiter;
    - a heredoc in `$( )` then `eval`;
    - a subshell or brace group piped to `sh`;
    - an earlier `exec > >(sh)`;
    - a git hook written then `git commit`;
    - a Makefile then `make`;
    - `gh …; sh s.md`;
    - two heredocs in one act;
    - write via `1>`, then run;
    - `tee` after a `cd`, then run;
    - write, then source it;
    - write, then run it by path;
    - write, then both publish and run it.
  - The earlier controls: a live backtick; `\\` then a backtick; an escaped backtick beside `$( )`; `cat <<'EOF' | sh`; `bash`/`python3` heredocs; an unquoted heredoc; a secret target or source on the heredoc line; a later read; `xargs`; `sudo tee`.
- `tools/egress_prose_test.py` (#1427): **PASS** (13 / 18).
- Real seat commands (a long markdown body with escaped backticks and a table; a heredoc issue body followed by `gh issue create --body-file … | tail -1`): the scan agrees with shlex, and the prose is no longer swept.
- Shell-scope battery: **1431 / 3 on both cores**, the same 3 rows (macOS `/var/folders` temp cases on this box).
- Every `plugins/_shared/*test*.py` and `tools/*_test.py` under both cores: see the PR.

## Running it
- Cut / re-cut: `build_1330b.py <worktree> <out>`. It reads `source-1330b.diff`.
- Tests: `run_overlay.py <worktree> <out> <test file>`. An empty `<out>` runs the control.

**After the governed apply:** `egress_prose2_test.py` moves to `tools/` beside `egress_prose_test.py`.
