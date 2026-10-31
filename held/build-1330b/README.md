# held: #1330, second half — heredoc data and quote-aware literals. **NOT applied.**

Patch: `held/eb2db3275127414d6b175029400e4cdecd52686b64970f8ca77fe8d781a0ece4.patch` (base `4a775cd1`): the gate core, plus the hooks-gt mirror and the 5 manifests.

## What #1427 left swept
#1427 made Gate 1a skip a **literal** prose value of `gh --body/--title/--comment` and `git -m`. Two shapes still refused `egress.secret` on a word in prose. Both were measured on McNugget 2026-10-31 (hestia `242824cf`), on mcnugget-claude's own issue filing:

1. **Markdown code in a prose value.** `gh issue comment … --body "… \`credentials\` …"` and `--body '… `x` …'`. `egress_command_text` tokenizes with shlex, which drops the quoting, so `_literal()` saw a backtick and kept the whole value swept. The shell expands nothing there: inside single quotes nothing is live, and inside double quotes `` \` `` and `\$` are literal.
2. **Heredoc data.** `cat > notes.md <<'EOF' … rotating the credentials … EOF`. The body of a quoted-delimiter heredoc written by `cat` is text the shell neither runs nor expands. Gate 1a swept the raw command, body included. The same bytes written with the Write tool are not swept, because a local file's contents are not egress.

## The rule
- **`_shell_liveness(command, words)`:** a raw-command scan that mirrors shlex's word values (posix, punctuation_chars, whitespace_split, `#` comments) and records, per word, whether the **shell** would expand anything: an unescaped `$` or backtick outside single quotes. `\\` is one backslash, so `"\\`x`"` is live. It's used only when its words equal shlex's **exactly**; on any difference, `_literal()` decides as before. A form the scan doesn't model can only be judged as strictly as today.
- **`_egress_heredoc_data_removed(cmd)`:** drops the body of a heredoc only when **all** of these hold:
  - the delimiter is **quoted** (`<<'EOF'`, `<<"EOF"`, `<<\EOF`, `<<-'EOF'`);
  - the consumer's first word is exactly `cat` or `tee` (no env prefix, no `sudo`, no `xargs`);
  - the rest of the heredoc's line holds no `|` `;` `&` `` ` `` `$` `(` `)` `<`.

  The heredoc's own line stays swept, as does every later line. More than one heredoc on a line, or an unterminated one, sweeps the whole command as written.
- **Unchanged:** interpreter `-c`/`-e` code; a shell or interpreter heredoc; an **unquoted** heredoc body (the shell expands it); paths, redirections and `--body-file`; and every control row of #1427.

## Evidence (revised core served as `hestia_gate_core`)
- `held/build-1330b/egress_prose2_test.py`: **PASS** on the revised core (10 prose rows allowed, 13 control rows still `egress.secret`). On main's core it **fails exactly the 10 prose rows**. The controls:
  - a live backtick;
  - `\\` followed by a live backtick;
  - an escaped backtick beside a live `$(…)`;
  - an unquoted backtick word;
  - `cat <<'EOF' | sh`;
  - `bash <<'EOF'`;
  - `python3 <<'EOF'`;
  - an unquoted heredoc holding `$(cat key)`;
  - `cat > ~/.ssh/authorized_keys <<'EOF'`;
  - `cat <key> - <<'EOF'`;
  - a read on a later line;
  - `xargs cat <<'EOF'`;
  - `sudo tee <<'EOF'`.
- `tools/egress_prose_test.py` (#1427's rows): **PASS** on the revised core (13 / 18).
- Real seat commands (a long markdown body with escaped backticks and a table; a heredoc issue body): the liveness scan agrees with shlex, and the prose words are no longer swept.
- Shell-scope battery: **1431 / 3 on both cores**, with the same 3 rows (`cd-temp-then-relative-inside`, `data-heredoc`, `tmp-under-`). Those are macOS `/var/folders` temp-path cases on this box, unrelated.
- Every `plugins/_shared/*test*.py` and `tools/*_test.py` under both cores: see the PR (exit codes compared file by file).

## Running it
- Cut / re-cut: `build_1330b.py <worktree> <out>`. It reads `source-1330b.diff`.
- Tests: `run_overlay.py <worktree> <out> <test file>`. An empty `<out>` runs the control.

**After the governed apply:** `egress_prose2_test.py` moves to `tools/` beside `egress_prose_test.py`.
