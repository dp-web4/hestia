#!/usr/bin/env python3
"""Make the off-limits paths that existing tests READ actually exist (hestia #1411, existence first).

Those tests assert the ordinary scope refusal (`mrh.path`) for an EXISTING path outside the grant;
their fixtures named paths that were never created, which existence-first now refuses as
`mrh.path.nonexistent` instead. Each edit creates the file just before the read, so the test keeps
testing what it says. argv: <hestia worktree> <out dir>. Writes neutral copies:
  <out>/tg_rev.py (plugins/_shared/test_gate_core.py). The tools/ harnesses are fixed in place
  instead, by a `materialize` step in their _verdict helpers (committed directly; not governed).
"""
import pathlib
import sys

WT, OUT = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
MARK = "  # exists: an off-limits path, not a missing one (hestia #1411)"


def edit(src, dst, pairs):
    text = (WT / src).read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (src, old, text.count(old))
        text = text.replace(old, new)
    (OUT / dst).write_text(text, encoding="utf-8")


edit("plugins/_shared/test_gate_core.py", "tg_rev.py", [
    ('    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/a.md"], cwd=ws)\n',
     f'    open(f"{{ws}}/notgranted/a.md", "w").close(){MARK}\n'
     '    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/a.md"], cwd=ws)\n'),
    ('    ev = G.NormalizedEvent(tool="Read", paths=[os.path.join(deep, "note.md")], cwd=ws)\n',
     f'    os.makedirs(deep, exist_ok=True)\n    open(os.path.join(deep, "note.md"), "a").close(){MARK}\n'
     '    ev = G.NormalizedEvent(tool="Read", paths=[os.path.join(deep, "note.md")], cwd=ws)\n'),
    ('    ev = G.NormalizedEvent(tool="Read", paths=[os.path.join(deep, "child.txt")], cwd=ws)\n',
     f'    open(os.path.join(deep, "child.txt"), "a").close(){MARK}\n'
     '    ev = G.NormalizedEvent(tool="Read", paths=[os.path.join(deep, "child.txt")], cwd=ws)\n'),
    ('    escape = f"{ws}/granted/../notgranted/secret"\n',
     '    escape = f"{ws}/granted/../notgranted/secret"\n'
     f'    os.makedirs(f"{{ws}}/notgranted", exist_ok=True)\n'
     f'    open(f"{{ws}}/notgranted/secret", "a").close(){MARK}\n'),
])
print("ok")
