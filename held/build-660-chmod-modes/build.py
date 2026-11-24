#!/usr/bin/env python3
"""Build the held patch for hestia #660: short chmod modes keep their targets.

argv: <hestia worktree at the base> <out dir>
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_governance_closure.py"
TEST = "plugins/_shared/hestia_governance_closure_test.py"
GT = "hooks-gt/_shared/hestia_governance_closure.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    src = once(src, """def _command_write_targets(words: list, stdin_src=None, path_pinned: bool = False) -> list:
""", '''_CHMOD_MODE = re.compile(r"(?:[ugoa]*[-+=][rwxXstugo]*(?:,[ugoa]*[-+=][rwxXstugo]*)*|[0-7]{3,4})")
_CHMOD_FLAGS = frozenset({
    "-R", "--recursive", "-v", "--verbose", "-f", "--silent", "--quiet", "-c", "--changes",
    "--preserve-root", "--no-preserve-root",
})


def _chmod_write_targets(args: list) -> list:
    """Targets after chmod's mode, including symbolic modes that begin with `-` (#660).

    Known flags are consumed by name, `--reference` supplies the mode itself, and an unknown
    option is out of grammar. `chown`/`chgrp` keep the existing positional implementation.
    """
    i, reference = 0, False
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in ("--help", "--version"):
            return []
        if a == "--reference":
            if i + 1 >= len(args):
                raise _OutOfGrammar()
            reference, i = True, i + 2
            continue
        if a.startswith("--reference="):
            if a == "--reference=":
                raise _OutOfGrammar()
            reference, i = True, i + 1
            continue
        if a in _CHMOD_FLAGS or (
                a.startswith("-") and not a.startswith("--")
                and len(a) > 1 and all(c in "Rvfc" for c in a[1:])):
            i += 1
            continue
        if a.startswith("-") and not _CHMOD_MODE.fullmatch(a):
            raise _OutOfGrammar()
        break
    if reference:
        return args[i:]
    if i >= len(args):
        return []
    if not _CHMOD_MODE.fullmatch(args[i]):
        raise _OutOfGrammar()
    return args[i + 1:]


def _command_write_targets(words: list, stdin_src=None, path_pinned: bool = False) -> list:
''')
    return once(src, """    if name in ("chmod", "chown", "chgrp"):
        pos = _positionals(args, opts_with_value=("--reference",))
        return pos[1:]
""", """    if name == "chmod":
        return _chmod_write_targets(args)
    if name in ("chown", "chgrp"):
        pos = _positionals(args, opts_with_value=("--reference",))
        return pos[1:]
""")


def patch_test(src):
    src = once(src, """def test_fd_dup_is_not_a_file_target():
""", '''def test_chmod_short_modes_keep_their_targets():
    target = "/w/hestia/plugins/kimi/hooks/observe.sh"
    for command in (
            f"chmod -x {target}", f"chmod -w {target}", f"chmod -r {target}",
            f"chmod -rwx {target}", f"chmod -R -x {target}", f"chmod -- -x {target}",
            f"chmod +x {target}", f"chmod a-x {target}", f"chmod go-rwx {target}",
            f"chmod u-x,g+w {target}", f"chmod -R u-x,g+w {target}",
            f"chmod 000 {target}", f"chmod a=r {target}",
            f"chmod --reference=/tmp/reference {target}",
            f"chmod --reference /tmp/reference {target}"):
        v = cls("Bash", {"command": command}, cwd="/w/hestia")
        check(f"chmod-target-is-write: {command}", v.classification == "write", str(v))
    v = cls("Bash", {"command": f"chmod --help {target}"}, cwd="/w/hestia")
    check("chmod-help-is-not-a-write", v.classification != "write", str(v))
    v = cls("Bash", {"command": "chmod -R -x"}, cwd="/w/hestia")
    check("chmod-without-target-is-not-invented", v.classification != "write", str(v))
    v = cls("Bash", {"command": "chmod --reference"}, cwd="/w/hestia")
    check("chmod-missing-reference-value-invents-no-target", v.classification != "write", str(v))
    for command in (f"chmod --some-future-option {target}", f"chmod --reference= {target}"):
        v = cls("Bash", {"command": command}, cwd="/w/hestia")
        check(f"chmod-malformed-mode-or-option-fails-closed: {command}",
              v.classification == "write" and v.rule == g.RULE_OUT_OF_GRAMMAR, str(v))
    v = cls("Bash", {"command": f"chown -R member {target}"}, cwd="/w/hestia")
    check("chown-still-writes", v.classification == "write", str(v))


def test_fd_dup_is_not_a_file_target():
''')
    return once(src, """    test_chmod_truncate_ln_targets_are_write,
""", """    test_chmod_truncate_ln_targets_are_write,
    test_chmod_short_modes_keep_their_targets,
""")


def diff(path, old, new):
    hdr = f"diff --git a/{path} b/{path}\n"
    return hdr + "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def hunks(section):
    out, cur = [], None
    for line in section.splitlines(keepends=True)[1:]:
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


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(section):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0)
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core = patch_core(blob(CORE))
    test_new = patch_test(blob(TEST))
    (OUT / "hestia_governance_closure.py").write_text(core, encoding="utf-8")
    (OUT / "hestia_governance_closure_test.py").write_text(test_new, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return core.encode() if self.resolve() == src_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(CORE, blob(CORE), core) + gt_out.read_text(encoding="utf-8") + diff(TEST, blob(TEST), test_new)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = core if path == CORE else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT]) == core.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
