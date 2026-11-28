#!/usr/bin/env python3
"""Build the held patch for hestia #661: ancestors of the closure are writes too.

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
    src = once(src, r'''    def match(self, target: str, *, cwd: Optional[str] = None,
              position: str = "write") -> Optional[str]:
        """The matched closure element, or None, over every form in `forms`."""
        for c in self.forms(target, cwd=cwd):
            hit = self._match_segments(_segments(c), position)
            if hit:
                return hit
        return None
''', r'''    def _match_ancestor(self, candidate: str) -> Optional[str]:
        """A proper marker prefix in normalized, case-folded absolute or relative form."""
        expanded = os.path.expanduser(candidate)
        absolute = os.path.isabs(expanded)
        real = (os.path.realpath(expanded) if absolute
                else os.path.normpath(expanded)).replace("\\", "/")
        segs = tuple(segment.casefold() for segment in _segments(real))
        for pat in self.dir_markers:
            folded = tuple(segment.casefold() for segment in pat)
            for width in range(1, len(folded)):
                if width <= len(segs) and all(
                        folded[i] == "*" or folded[i] == segs[len(segs) - width + i]
                        for i in range(width)):
                    return "/".join(pat)
            if absolute:
                literal = []
                for segment in pat:
                    if segment == "*":
                        break
                    literal.append(segment)
                if literal and os.path.isdir(os.path.join(real, *literal)):
                    return "/".join(pat)
        return None

    def match(self, target: str, *, cwd: Optional[str] = None,
              position: str = "write") -> Optional[str]:
        """The matched closure element, or None, over every form in `forms`."""
        for c in self.forms(target, cwd=cwd):
            hit = self._match_segments(_segments(c), position)
            if hit:
                return hit
            if position == "write":
                hit = self._match_ancestor(c)
                if hit:
                    return hit
        return None
''')
    src = once(src, """        sub, rest = args[i], args[i + 1:]
""", """        sub, rest = args[i], args[i + 1:]
        git_c = args[args.index("-C") + 1] if "-C" in args[:i] else None
""")
    return once(src, """        if sub == "checkout":
            # Only explicit pathspec overwrite (`checkout [-|tree-ish] -- paths`); a branch
            # switch is not a targeted closure write.
            if "--" in rest:
                return rest[rest.index("--") + 1:]
            return []
""", """        if sub == "checkout":
            # Only explicit pathspec overwrite (`checkout [-|tree-ish] -- paths`); a branch
            # switch is not a targeted closure write. `git -C` roots relative pathspecs there,
            # not at the shell's cwd.
            if "--" in rest:
                targets = rest[rest.index("--") + 1:]
                if git_c:
                    return [t if os.path.isabs(t) else os.path.join(git_c, t) for t in targets]
                return targets
            return []
""")


def patch_test(src):
    src = once(src, """def test_fd_dup_is_not_a_file_target():
""", '''def test_ancestor_moves_are_closure_writes():
    for command in (
            "mv plugins/kimi /tmp/k",
            "mv plugins/kimi plugins/kimi.bak",
            "mv plugins plugins.bak",
            "cp -r plugins/kimi plugins/kimi2",
            "mv plugins/kimi/hooks /tmp/h"):
        v = cls("Bash", {"command": command}, cwd="/w/hestia")
        check(f"ancestor-write: {command}", v.classification == "write", str(v))

    root = tempfile.mkdtemp(prefix="hgc-ancestor-repo-")
    os.makedirs(os.path.join(root, "plugins"))
    v = cls("Bash", {"command": "git checkout -q origin/main -- ."}, cwd=root)
    check("repo-root-checkout-is-write", v.classification == "write", str(v))
    v = cls("Bash", {"command": "ls"}, cwd=root)
    check("repo-root-read-is-not-write", v.classification != "write", str(v))

    for label, command in (
            ("absolute", f"mv {root}/plugins /tmp/x"),
            ("absolute-rm", f"rm -rf {root}/plugins"),
            ("case-fold", f"mv {root}/PLUGINS /tmp/x"),
            ("normalized-dotdot", f"mv {root}/plugins/kimi/../kimi /tmp/x"),
            ("git-C-root", f"git -C {root} checkout -- ."),
            ("git-C-case-fold", f"git -C {root} checkout -- PLUGINS")):
        v = cls("Bash", {"command": command}, cwd="/")
        check(f"absolute-ancestor-{label}-is-write", v.classification == "write", str(v))

    linked = tempfile.mkdtemp(prefix="hgc-ancestor-links-")
    root_link = os.path.join(linked, "root-link")
    plugins_link = os.path.join(linked, "plugins-link")
    os.symlink(root, root_link)
    os.symlink(os.path.join(root, "plugins"), plugins_link)
    for label, command in (
            ("root-link", f"mv {root_link}/plugins /tmp/x"),
            ("through-link", f"mv {plugins_link}/kimi /tmp/x")):
        v = cls("Bash", {"command": command}, cwd="/")
        check(f"symlinked-ancestor-{label}-is-write", v.classification == "write", str(v))

    v = cls("Bash", {"command": "mv /tmp/ordinary-a /tmp/ordinary-b"}, cwd="/")
    check("ordinary-absolute-move-is-not-invented", v.classification != "write", str(v))
    empty = tempfile.mkdtemp(prefix="hgc-ancestor-empty-")
    v = cls("Bash", {"command": "git checkout -q origin/main -- ."}, cwd=empty)
    check("unrelated-root-is-not-invented", v.classification != "write", str(v))


def test_fd_dup_is_not_a_file_target():
''')
    return once(src, """    test_fd_dup_is_not_a_file_target,
""", """    test_ancestor_moves_are_closure_writes,
    test_fd_dup_is_not_a_file_target,
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
        elif cur is not None and not line.strip():
            cur["old"].append(line)
            cur["new"].append(line)
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
    body = re.sub(r"(?m)^ $", "", body)
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
