"""Build the #1330 change: read main's gate core from git (never the working file), write the revised
copy under a NEUTRAL name, and emit a unified diff. argv: <hestia worktree> <out dir>"""
import difflib, pathlib, subprocess, sys

wt, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()

old = '''    return (list(event.paths) + list(event.repos)
            + (egress_items(getattr(event, "egress", None)) or [])
            + ([event.command] if event.command else []))
'''
new = '''    return (list(event.paths) + list(event.repos)
            + (egress_items(getattr(event, "egress", None)) or [])
            + ([egress_command_text(event.command)] if event.command else []))


#: A value a program's own contract makes TEXT, never a path it opens (hestia #1330): a gh title,
#: body or comment, a git commit or tag message. Only these flag values are left out of Gate 1a's
#: sweep; every other word of the command, including an interpreter's `-c`/`-e` code and a quoted
#: path, is swept exactly as before.
_PROSE_FLAGS = {
    "gh": {"--body", "-b", "--title", "-t", "--comment"},
    "git": {"-m", "--message"},
}
_SEGMENT_BREAKS = {";", "&&", "||", "|", "&", "(", ")", "\\n"}


def egress_command_text(command: str) -> str:
    """The command as Gate 1a sweeps it: every word, except a LITERAL prose value of a flag in
    `_PROSE_FLAGS` (hestia #1330). Measured on Legion 2026-10-15/10-27: `gh issue create --body
    "...the workspace credentials file..."` was refused `egress.secret` on a word in the issue's
    text, so every security write-up went through `--body-file`, the pattern the law discourages
    elsewhere. A value holding `$` or a backtick is not literal (it could expand to a secret's
    contents) and stays swept; so does the whole raw command when it cannot be tokenized."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return command
    kept, prog, skip_next = [], None, False
    for w in words:
        if w in _SEGMENT_BREAKS:
            prog, skip_next = None, False
            kept.append(w)
            continue
        if skip_next:
            skip_next = False
            if "$" not in w and "`" not in w:
                continue                    # the literal prose value: not a path, not swept
            kept.append(w)
            continue
        if prog is None:
            if "=" in w and not w.startswith("-") and w.split("=", 1)[0].isidentifier():
                kept.append(w)              # an env assignment before the program: still swept
                continue
            prog = os.path.basename(w)
            kept.append(w)
            continue
        flags = _PROSE_FLAGS.get(prog, ())
        name, eq, val = w.partition("=")
        if w in flags:
            kept.append(w)
            skip_next = True
            continue
        if eq and name in flags and name.startswith("--") and "$" not in val and "`" not in val:
            kept.append(name + "=")
            continue
        kept.append(w)
    return " ".join(kept)
'''
assert src.count(old) == 1
rev = src.replace(old, new)
(out / "core_rev.py").write_text(rev)
diff = "".join(difflib.unified_diff(src.splitlines(True), rev.splitlines(True), f"a/{rel}", f"b/{rel}"))
(out / "source-1330.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("ok", len(diff.splitlines()), "diff lines")
