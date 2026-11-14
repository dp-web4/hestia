#!/usr/bin/env python3
"""Build the held patch for hestia #1598 over the worktree's HEAD, in memory, writing no governed path.

Re-runnable at apply time: the edit is an exact-once anchor in HEAD's closure classifier, so a moved main
costs a re-run, not a review cycle (same build shape as held 1560 / 1595).

  1. The closure's sed parse reads BSD `sed -i '' SCRIPT FILE` (and `-i .bak`): on its unambiguous shape
     the second positional is the script and the rest are the in-place operands (#1598).
  2. tools/closure_bsd_sed_test.py (new, 13 rows) is added.
The hooks-gt copy and the manifests are emitted by HEAD's own tools/hooks_gt.emit_patch with the closure
read served from the patched copy. The patch is named by its sha256 and verified: applied in memory to
HEAD's blobs it must reproduce the patched classifier, the new test and hooks_gt.build()'s tree exactly.

argv: <hestia worktree at the base> <out dir>   (use an EMPTY out dir, not held/)
Writes: <out>/closure_rev.py (neutral name) and <out>/<sha256>.patch.
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
TEST = "tools/closure_bsd_sed_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_closure(src):
    return once(src, """        scripts = vals.get("-e", []) + vals.get("--expression", [])
        operands = pos if scripts else pos[1:]
        if not scripts:
            scripts = pos[:1]
""", """        scripts = vals.get("-e", []) + vals.get("--expression", [])
        operands = pos if scripts else pos[1:]
        bsd_suffix = (not scripts and not vals.get("-f") and not vals.get("--file")
                      and vals.get("-i") and all(v is None for v in vals["-i"])
                      and "--in-place" not in seen and len(pos) >= 3
                      and (pos[0] == "" or pos[0].startswith(".")))
        if bsd_suffix:
            # BSD sed (macOS): a BARE `-i` takes the backup suffix as the NEXT argument
            # (`sed -i '' SCRIPT FILE`, `sed -i .bak SCRIPT FILE`), so the script is the second
            # positional, not an operand (#1598: a script naming a closure path was refused as a
            # closure write). Taken only on this shape: as a GNU script, `''` edits nothing and a
            # dot-led one is a syntax error, so no GNU act that writes content reads this way.
            scripts, operands = pos[1:2], pos[2:]
        if not scripts:
            scripts = pos[:1]
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
    test_new = (HERE / "closure_bsd_sed_test.py").read_text(encoding="utf-8")
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
