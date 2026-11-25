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
TEST = "plugins/claude-code/tests/python_ambient_import_test.py"


def show(spec):
    return subprocess.check_output(["git", "show", spec], cwd=WT).decode()


def once(text, old, new, count=1):
    assert text.count(old) == count, (old[:100], text.count(old), count)
    return text.replace(old, new)


def patch_core(src):
    src = once(src, '''def _python_invocations(command: Optional[str], cwd: str) -> list[tuple]:
''', '''def _shell_without_comments(text: str) -> str:
    out = []
    quote = None
    escaped = False
    comment = False
    word_start = True
    for char in text:
        if comment:
            if char == "\\n":
                comment = False
                word_start = True
                out.append(char)
            else:
                out.append(" ")
            continue
        if escaped:
            out.append(char)
            escaped = False
            word_start = False
            continue
        if quote is not None:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char == "\\\\":
            out.append(char)
            escaped = True
            word_start = False
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
            word_start = False
            continue
        if char == "#" and word_start:
            comment = True
            out.append(" ")
            continue
        out.append(char)
        word_start = char.isspace() or char in ";|&()"
    return "".join(out)


def _python_invocations(command: Optional[str], cwd: str) -> list[tuple]:
''')
    src = once(src, '''        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;")
        lexer.whitespace_split = True
''', '''        command = _shell_without_comments(command)
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;\\n")
        lexer.whitespace = " \\t\\r\\f\\v"
        lexer.commenters = ""
        lexer.whitespace_split = True
''')
    src = once(src, '''        if re.fullmatch(r"[&|;]+", word):
''', '''        if re.fullmatch(r"(?:[&|;]|\\n)+", word):
''')
    src = once(src, '''    invocations = []
    current_cwd = os.path.realpath(cwd)
    for segment_index, segment in enumerate(segments):
        if not segment:
            continue
        i = 0
        pythonpath = None
''', '''    invocations = []
    current_cwd = os.path.realpath(cwd)
    alternate_cwds = []
    current_pythonpath = None
    skip_next = False
    for segment_index, segment in enumerate(segments):
        if skip_next:
            if not segment:
                continue
            skip_next = False
            continue
        if not segment:
            continue
        previous_separator = separators[segment_index - 1] if segment_index else None
        i = 0
        pythonpath = current_pythonpath
''')
    src = once(src, '''        if i >= len(segment):
            continue
        if segment[i] == "cd":
            if (len(segment) == i + 2 and segment_index < len(separators)
                    and separators[segment_index] in ("&&", ";")):
                current_cwd = os.path.realpath(os.path.join(
                    current_cwd, os.path.expanduser(segment[i + 1])))
            continue
        if not re.fullmatch(r"python(?:[0-9]+(?:\\.[0-9]+)*)?", os.path.basename(segment[i])):
            continue
''', '''        if i >= len(segment):
            if segment[0] != "env":
                current_pythonpath = pythonpath
            continue
        if segment[i] in ("export", "local", "declare", "typeset", "readonly"):
            for arg in segment[i + 1:]:
                name, eq, value = arg.partition("=")
                if eq and name == "PYTHONPATH":
                    current_pythonpath = value
            continue
        if segment[i] == "unset":
            if any(arg == "PYTHONPATH" for arg in segment[i + 1:]):
                current_pythonpath = None
            continue
        if segment[i] == "cd":
            next_separator = (separators[segment_index]
                              if segment_index < len(separators) else None)
            if len(segment) == i + 2 and next_separator in ("&&", "||", ";", "\\n"):
                possible = list(dict.fromkeys([current_cwd] + alternate_cwds))
                targets = [os.path.realpath(os.path.join(c, os.path.expanduser(segment[i + 1])))
                           for c in possible]
                if previous_separator in ("&&", "||") or next_separator == "||":
                    keep = possible + targets
                else:
                    keep = [target if os.path.isdir(target) else original
                            for original, target in zip(possible, targets)]
                    if (not any(os.path.isdir(target) for target in targets)
                            and next_separator == "&&" and segment_index == 0):
                        skip_next = True
                keep = list(dict.fromkeys(keep))
                current_cwd, alternate_cwds = keep[0], keep[1:]
            continue
        program = (os.path.basename(os.path.realpath(os.path.join(current_cwd, segment[i])))
                   if "/" in segment[i] else segment[i])
        if not re.fullmatch(r"(?:python|pypy)(?:[0-9]+(?:\\.[0-9]+)*)?(?:-dbg)?", program):
            continue
''')
    src = once(src, '''        script_dir = None
        if script and not stop_at_cwd:
            script_dir = os.path.dirname(os.path.realpath(os.path.join(current_cwd, script)))
        invocations.append((isolated, script_dir, current_cwd, pythonpath))
''', '''        for invocation_cwd in dict.fromkeys([current_cwd] + alternate_cwds):
            script_dir = None
            if script and not stop_at_cwd:
                script_dir = os.path.dirname(os.path.realpath(os.path.join(invocation_cwd, script)))
            invocations.append((isolated, script_dir, invocation_cwd, pythonpath))
''')
    src = once(src, '''    current = os.path.realpath(cwd)
    workspace = os.path.realpath(workspace)
''', '''    current = os.path.realpath(cwd)
    evidence_dir = current
    workspace = os.path.realpath(workspace)
''')
    src = once(src, '''            return current if _within_path_grant(current, scopes, workspace) else None
''', '''            return current if _within_path_grant(evidence_dir, scopes, workspace) else None
''')
    return once(src, '''    Trust requires an explicit `path:` grant AND package evidence, never a marker alone.
    Existing denies keep precedence: this is called only after scope has admitted the act.
''', '''    Trust requires an explicit `path:` grant that reaches the actual script/import directory
    AND package evidence, never a marker or an exact grant on an ancestor alone. Existing denies
    keep precedence: this is called only after scope has admitted the act. Only direct interpreter
    commands are parsed; `sh -c`, `uv run`, command substitution, `if`/`while` bodies, subshells,
    `pushd`, and heredoc-fed interpreters are outside this advisory, so no warning is not proof
    of import safety.
''')


def patch_test(src):
    src = once(src, '''        nested_command = f"cd /tmp && python3 {root / 'nested' / 'helper.py'}"
        check("file execution uses the script directory, not the invocation cwd",
              signal(nested_command, "/tmp", workspace=tmp, scopes=grants) is None,
              repr(signal(nested_command, "/tmp", workspace=tmp, scopes=grants)))
''', '''        nested_command = f"cd /tmp && python3 {root / 'nested' / 'helper.py'}"
        nested_grants = [f"path:{tmp}{gate.RECURSIVE_SUFFIX}"]
        check("file execution uses the script directory, not the invocation cwd",
              signal(nested_command, "/tmp", workspace=tmp, scopes=nested_grants) is None,
              repr(signal(nested_command, "/tmp", workspace=tmp, scopes=nested_grants)))
''')
    src = once(src, '''        conditional = f"false && cd {shlex.quote(str(root / 'granted'))}; python3 probe.py"
''', '''        untrusted_newline = "echo hi\\npython3 probe.py"
        verdict = signal(untrusted_newline, tmp)
        check("a newline does not hide a later interpreter invocation",
              verdict is not None and verdict.target == str(root), repr(verdict))
        conditional = f"false && cd {shlex.quote(str(root / 'granted'))}; python3 probe.py"
''')
    src = once(src, '''        nested = root / "granted" / "downloads" / "untrusted"
''', '''        (root / "granted" / ".git").mkdir()
        nested = root / "granted" / "downloads" / "untrusted"
''')
    src = once(src, '''        with tempfile.TemporaryDirectory() as ambient:
            exported = f"export PYTHONPATH={shlex.quote(ambient)}; python3 -c 'import x'"
''', '''        unmarked = root / "granted" / "downloads" / "no-marker"
        unmarked.mkdir()
        (unmarked / "probe.py").write_text("print('unmarked')\\n")
        unmarked_command = f"cd {shlex.quote(str(unmarked))} && python3 probe.py"
        verdict = signal(unmarked_command, tmp, scopes=[f"path:{root / 'granted'}"])
        check("an exact grant does not bless an unmarked nested directory",
              verdict is not None and verdict.target == str(unmarked), repr(verdict))
        recursive = [f"path:{root / 'granted'}{gate.RECURSIVE_SUFFIX}"]
        check("a recursive grant still reaches a nested package directory",
              signal(unmarked_command, tmp, scopes=recursive) is None,
              repr(signal(unmarked_command, tmp, scopes=recursive)))
        untrusted = root / "untrusted"
        untrusted.mkdir()
        (untrusted / "probe.py").write_text("print('untrusted')\\n")
        conditional_untrusted = f"true && cd {shlex.quote(str(untrusted))} && python3 probe.py"
        verdict = signal(conditional_untrusted, root / "granted", workspace=tmp,
                         scopes=[f"path:{root / 'granted'}"])
        check("a conditional cd adds an untrusted possible cwd",
              verdict is not None and verdict.target == str(untrusted), repr(verdict))
        for label, prefix in (("cloned", "git clone example"), ("created", "mkdir -p")):
            created = root / "granted" / (label + "-package")
            command = f"{prefix} {created} && cd {created} && python3 setup.py install"
            verdict = signal(command, root / "granted", workspace=tmp,
                             scopes=[f"path:{root / 'granted'}"])
            check(f"a {label} directory remains a possible cwd",
                  verdict is not None and verdict.target == str(created), repr(verdict))
        or_branch = f"cd {shlex.quote(str(untrusted))} || exit; python3 probe.py"
        verdict = signal(or_branch, root / "granted", workspace=tmp,
                         scopes=[f"path:{root / 'granted'}"])
        check("an or-branch does not discard the cd target",
              verdict is not None and verdict.target == str(untrusted), repr(verdict))
        (root / "granted" / "sub").mkdir()
        conditional_sequence = (
            f"true && cd {shlex.quote(str(untrusted))}; cd sub; python3 probe.py")
        verdict = signal(conditional_sequence, root / "granted", workspace=tmp, scopes=recursive)
        check("a later cd preserves conditional cwd alternatives",
              verdict is not None and verdict.target == str(untrusted), repr(verdict))
        other_second = root / "other" / "second"
        other_second.mkdir(parents=True)
        (other_second / "pyproject.toml").write_text("[project]\\n")
        other_granted = root / "other" / "granted"
        other_granted.mkdir()
        (other_granted / "probe.py").write_text("print('other')\\n")
        other_grants = [f"path:{root / 'granted'}", f"path:{other_second}"]
        relative_sequence = (
            f"true && cd {shlex.quote(str(other_second))} && cd ../granted && python3 probe.py")
        verdict = signal(relative_sequence, root / "granted", workspace=tmp, scopes=other_grants)
        check("a relative cd composes over every possible cwd",
              verdict is not None and verdict.target == str(other_granted), repr(verdict))
        commented_cd = f"# note; cd {shlex.quote(str(root / 'granted'))}\\npython3 probe.py"
        verdict = signal(commented_cd, tmp)
        check("a comment cannot manufacture a trusted cwd",
              verdict is not None and verdict.target == str(root), repr(verdict))
        quoted_hash = "echo '#'; python3 probe.py"
        verdict = signal(quoted_hash, tmp)
        check("a quoted hash does not start a comment",
              verdict is not None and verdict.target == str(root), repr(verdict))
        planted = root / "python3"
        planted.symlink_to("/bin/true")
        check("a planted bare-name symlink cannot silence the advisory",
              signal("python3 probe.py", tmp) is not None)
        comment_newline = "echo hi # comment\\npython3 probe.py"
        verdict = signal(comment_newline, tmp)
        check("a comment does not swallow the newline before Python",
              verdict is not None and verdict.target == str(root), repr(verdict))
        with tempfile.TemporaryDirectory() as ambient:
            exported = f"export PYTHONPATH={shlex.quote(ambient)}; python3 -c 'import x'"
''')
    return src


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
        for line in section[match.end():].splitlines(keepends=True):
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
    dest = root / "plugins/_shared"
    tests = root / "plugins/claude-code/tests"
    tests.mkdir(parents=True)
    dest.mkdir(parents=True)
    for child in shared.iterdir():
        if child.name != "hestia_gate_core.py":
            os.symlink(child, dest / child.name, target_is_directory=child.is_dir())
    (dest / "hestia_gate_core.py").write_text(core, encoding="utf-8")
    (tests / "python_ambient_import_test.py").write_text(test, encoding="utf-8")


def run_acx(root, tmp):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(root / "plugins/claude-code/tests/python_ambient_import_test.py")],
        cwd=WT, env=env, text=True, capture_output=True)


def main():
    original_core = show("HEAD:" + CORE)
    original_test = show(":" + TEST)
    previous_body = (WT / "held/a7a4d9b7752645fc726f3bae0b2709d120d7e27944f8f22c16f67886f293bc93.patch").read_text()
    previous_core = strict_apply(original_core, sections(previous_body)[CORE])
    patched_core, patched_test = patch_core(original_core), patch_test(original_test)
    work = pathlib.Path(tempfile.mkdtemp(prefix="run-", dir=BUILD))
    try:
        base, previous, patched = work / "base", work / "previous", work / "patched"
        overlaid(base, original_core, patched_test)
        overlaid(previous, previous_core, patched_test)
        overlaid(patched, patched_core, patched_test)
        before = run_acx(base, work / "base-tmp")
        print(before.stdout, end="")
        print(before.stderr, end="", file=sys.stderr)
        assert before.returncode != 0, "the ACX corrections do not fail on the base core"
        required_names = (
            "a newline does not hide a later interpreter invocation",
            "a failed conditional cd cannot manufacture package trust",
            "a failed cd stops the dependent interpreter invocation",
            "an exact grant does not bless an unmarked nested directory",
            "an exported untrusted PYTHONPATH is not lost between segments",
            "pypy is an interpreter alias, not an unobserved Python runtime",
            "a symlinked interpreter alias is resolved before matching",
        )
        missing = [name for name in required_names if name not in before.stdout]
        assert not missing, ("non-discriminating controls", missing)
        withdrawn = run_acx(previous, work / "previous-tmp")
        print(withdrawn.stdout, end="")
        print(withdrawn.stderr, end="", file=sys.stderr)
        assert withdrawn.returncode != 0, "the new controls do not fail on the withdrawn candidate"
        withdrawn_names = (
            "a later cd preserves conditional cwd alternatives",
            "a relative cd composes over every possible cwd",
            "a comment cannot manufacture a trusted cwd",
        )
        missing = [name for name in withdrawn_names if name not in withdrawn.stdout]
        assert not missing, ("controls that pass on the withdrawn candidate", missing)
        after = run_acx(patched, work / "patched-tmp")
        print(after.stdout, end="")
        print(after.stderr, end="", file=sys.stderr)
        assert after.returncode == 0, "the patched core did not pass ACX"
    finally:
        shutil.rmtree(work)

    body = diff(CORE, original_core, patched_core) + diff(TEST, original_test, patched_test)
    sha = hashlib.sha256(body.encode()).hexdigest()
    target = WT / "held" / (sha + ".patch")
    target.write_text(body, encoding="utf-8")
    wanted = {CORE: patched_core, TEST: patched_test}
    originals = {CORE: original_core, TEST: original_test}
    for path, section in sections(body).items():
        assert strict_apply(originals[path], section) == wanted[path], path
        print("verified", path)
    print("patch", target)
    print("sha256", sha)


main()
