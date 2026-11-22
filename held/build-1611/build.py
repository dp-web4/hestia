#!/usr/bin/env python3
"""Build the held patch for hestia #1611 without writing the governed test.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/shell_grammar_test_rev.py and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
SRC = "plugins/_shared/shell_grammar_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_test(src):
    src = once(src, """# (name, command, expected_classifier_write?) — write-arm commands touch ONLY the sandbox.
_DIFF_CASES = [
""", """def _sed_bundled_in_place():
    \"\"\"Use GNU or BSD sed's no-backup spelling, as appropriate for this host.\"\"\"
    try:
        gnu = subprocess.run(
            ["sed", "--version"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except OSError:
        gnu = False
    empty_suffix = "" if gnu else " ''"
    return f"sed -Ei{empty_suffix} 's/orig/edited/' plugins/kimi/hooks/{HOOK}"


# (name, command, expected_classifier_write?) — write-arm commands touch ONLY the sandbox.
_DIFF_CASES = [
""")
    return once(src,
                """    ("sed_bundled_in_place", f"sed -Ei 's/orig/edited/' plugins/kimi/hooks/{HOOK}", True),""",
                """    ("sed_bundled_in_place", _sed_bundled_in_place(), True),""")


def diff(path, old, new):
    body = "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))
    return f"diff --git a/{path} b/{path}\n" + body


def hunks(text):
    out, cur = [], None
    for line in text.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))?", line)
            cur = {"start": int(m.group(1)) - 1, "old": [], "new": []}
            out.append(cur)
        elif cur is not None and line[:1] in " +-" and not line.startswith(("--- ", "+++ ")):
            if line[0] in " -":
                cur["old"].append(line[1:])
            if line[0] in " +":
                cur["new"].append(line[1:])
    return out


def strict_apply(old_text, text):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(text):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0)
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old = blob(SRC)
    new = patch_test(old)
    (OUT / "shell_grammar_test_rev.py").write_text(new, encoding="utf-8")
    body = diff(SRC, old, new)
    sha = hashlib.sha256(body.encode()).hexdigest()
    patch = OUT / f"{sha}.patch"
    patch.write_text(body, encoding="utf-8")
    assert strict_apply(old, body) == new
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {patch}\nsha256 {sha}")


main()
