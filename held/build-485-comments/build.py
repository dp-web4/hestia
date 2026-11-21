#!/usr/bin/env python3
"""Build the held patch for hestia #485 comment/quote desynchronization.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/closure_rev.py and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SRC = "plugins/_shared/hestia_governance_closure.py"
GT = "hooks-gt/_shared/hestia_governance_closure.py"
TEST = "tools/closure_comment_quote_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_closure(src):
    src = once(src, """    a comment's words become an ordinary simple command whose head is `#`: harmless, and the
    following line is still seen. The residual cost is a comment containing a redirect
    (`# write with > here`) raising a phantom write target and refusing a benign command.
    That is a false POSITIVE, it fails closed, and it is the direction this module prefers.
    `a#b` is unaffected: shlex keeps a mid-word `#` attached, so it never opens anything.
""", """    a comment's words become an ordinary simple command whose head is `#`: harmless when no
    comment quote swallows the following line. The residual cost is a comment containing a
    redirect (`# write with > here`) raising a phantom write target and refusing a benign command.
    That is a false POSITIVE, it fails closed, and it is the direction this module prefers.
    `a#b` is unaffected: shlex keeps a mid-word `#` attached, so it never opens anything.

    A newline embedded in a token AFTER a #-led token is the different #485 case: a quote in
    comment text made shlex consume a command boundary that Bash honors. Refuse to resolve two
    different programs. A quoted hash followed by a multiline string can pay a false refusal for
    this conservative test; the differential names that cost rather than hiding it.
""")
    return once(src, """        out.extend(_split_operator_run(tok) if _is_punct(tok) else [tok])
    return out
""", """        out.extend(_split_operator_run(tok) if _is_punct(tok) else [tok])
    comment = False
    for tok in out:
        if tok == "\\n":
            comment = False
        elif tok.startswith("#"):
            comment = True
        elif comment and "\\n" in tok:
            raise _OutOfGrammar()
    return out
""")


def diff(path, old, new):
    a = old.splitlines(True) if old is not None else []
    b = new.splitlines(True)
    hdr = f"diff --git a/{path} b/{path}\n" + ("new file mode 100755\n" if old is None else "")
    return hdr + "".join(difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{path}", f"b/{path}"))


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
    lines = old_text.splitlines(keepends=True) if old_text is not None else []
    out, pos = [], 0
    for h in hunks(section):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0) if old_text is not None else 0
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
    new = patch_closure(blob(SRC))
    test_new = (HERE / "closure_comment_quote_test.py.held").read_text(encoding="utf-8")
    (OUT / "closure_rev.py").write_text(new, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = WT / SRC
    real_read = pathlib.Path.read_bytes

    def served(self):
        return new.encode() if self.resolve() == src_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(SRC, blob(SRC), new) + gt_out.read_text(encoding="utf-8") + diff(TEST, None, test_new)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        old = None if path == TEST else blob(path)
        got = strict_apply(old, sec)
        want = new if path == SRC else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT]) == new.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
