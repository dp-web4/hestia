#!/usr/bin/env python3
import difflib
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

WT = pathlib.Path(sys.argv[1]).resolve()
BUILD = pathlib.Path(__file__).resolve().parent
CORE = "plugins/_shared/hestia_gate_core.py"
TEST = "plugins/_shared/test_gate_core.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new, count=1):
    assert text.count(old) == count, (old[:100], text.count(old), count)
    return text.replace(old, new)


def patch_core(src):
    return once(src, '''            if head is None:
                name, eq, _value = word.partition("=")
                if eq and name.isidentifier():
                    continue
                head = os.path.basename(word)
                continue
''', '''            if head is None:
                name, eq, _value = word.partition("=")
                if eq and name.isidentifier():
                    continue
                base = os.path.basename(word)
                if base in _HEREDOC_WRAPPERS or word.isdigit() or re.fullmatch(r"\\d+[smhd]?", word) \\
                        or (word.startswith("-") and len(word) > 1):
                    continue
                head = base
                continue
''')


def patch_test(src):
    src = once(src, '''    for name, command, target in grouped_cases:
        ok, offending, refused = reach(command)
''', '''    wrapped_cases = (
        ("exec_read", "exec cat notes.txt", "notes.txt"),
        ("exec_write", "exec rm -f remove.txt", "remove.txt"),
        ("command_read", "command cat notes.txt", "notes.txt"),
        ("command_write", "command rm -f remove.txt", "remove.txt"),
        ("nice_read", "nice cat notes.txt", "notes.txt"),
        ("nice_write", "nice rm -f remove.txt", "remove.txt"),
        ("env_read", "env cat notes.txt", "notes.txt"),
        ("env_write", "env rm -f remove.txt", "remove.txt"),
        ("timeout_read", "timeout 5 cat notes.txt", "notes.txt"),
        ("timeout_write", "timeout 5 rm -f remove.txt", "remove.txt"),
        ("nohup_write", "nohup rm -f remove.txt", "remove.txt"),
        ("sudo_read", "sudo -n cat notes.txt", "notes.txt"),
    )
    for name, command, target in grouped_cases + wrapped_cases:
        ok, offending, refused = reach(command)
''')
    src = once(src, '''    for name, command, _target in grouped_cases:
        check(name + "_allowed_by_explicit_cwd_grant",
''', '''    for name, command, _target in grouped_cases + wrapped_cases:
        check(name + "_allowed_by_explicit_cwd_grant",
''')
    return once(src, '''          v.blocks and v.rule == "mrh.command" and expected in v.reason, repr(v))
''', '''          v.blocks and v.rule == "mrh.command" and v.target == expected, repr(v))
''')


def diff(path, old, new):
    return f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for match in re.finditer(r"(?m)^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n", section):
        start = int(match.group(1)) - 1
        old, new = [], []
        tail = section[match.end():]
        for line in tail.splitlines(keepends=True):
            if line.startswith(("@@ ", "diff --git ")):
                break
            if line[:1] in " -":
                old.append(line[1:])
            if line[:1] in " +":
                new.append(line[1:])
        out.extend(lines[pos:start])
        assert lines[start:start + len(old)] == old, ("strict", start)
        out.extend(new)
        pos = start + len(old)
    out.extend(lines[pos:])
    return "".join(out)


def overlaid(root, core, test):
    shared = WT / "plugins/_shared"
    dest = root / "shared"
    dest.mkdir(parents=True)
    for child in shared.iterdir():
        if child.name not in ("hestia_gate_core.py", "test_gate_core.py"):
            os.symlink(child, dest / child.name, target_is_directory=child.is_dir())
    (dest / "hestia_gate_core.py").write_text(core, encoding="utf-8")
    (dest / "test_gate_core.py").write_text(test, encoding="utf-8")


def run_bare_test(root, home):
    home.mkdir()
    code = """import sys
sys.path.insert(0, sys.argv[1])
import test_gate_core as t
t.test_bare_name_file_operands_in_an_ungranted_cwd()
print('FAILURES', t.FAILURES)
raise SystemExit(bool(t.FAILURES))
"""
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-c", code, str(root / "shared")], cwd=WT, env=env)


def main():
    original_core, original_test = blob(CORE), blob(TEST)
    patched_core, patched_test = patch_core(original_core), patch_test(original_test)
    work = pathlib.Path(tempfile.mkdtemp(prefix="run-", dir=BUILD))
    try:
        base = work / "base"
        patched = work / "patched"
        overlaid(base, original_core, patched_test)
        overlaid(patched, patched_core, patched_test)
        before = run_bare_test(base, work / "base-home")
        assert before.returncode != 0, "the wrapper regressions do not fail on the base core"
        after = run_bare_test(patched, work / "patched-home")
        assert after.returncode == 0, "the patched core did not pass the bare-operand test"
    finally:
        shutil.rmtree(work)

    body = diff(CORE, original_core, patched_core) + diff(TEST, original_test, patched_test)
    sha = hashlib.sha256(body.encode()).hexdigest()
    target = WT / "held" / (sha + ".patch")
    target.write_text(body, encoding="utf-8")
    wanted = {CORE: patched_core, TEST: patched_test}
    for path, section in sections(body).items():
        assert strict_apply(blob(path), section) == wanted[path], path
        print("verified", path)
    print("base head", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip())
    print("patch", target)
    print("sha256", sha)


main()
