"""Cut hestia #1330 second half (heredoc data and quote-aware literals; first half: prose is not a path: Gate 1a does not sweep a LITERAL gh title/body/comment or
git commit/tag message for secret-path words) over the worktree's HEAD, in memory, writing no
governed path. The change is `source-1330b.diff` beside this file: the gate core only. Hunks apply
offset-tolerantly (each old block exactly once, else this stops); hooks-gt is emitted by HEAD's own
tools/hooks_gt.emit_patch with the source served from the patched copy; the patch is named by its
sha256 and verified by re-applying it in memory. The recipe of held/build-1411.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/core_rev.py (neutral name) and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
HERE = pathlib.Path(__file__).resolve().parent
SOURCES = {
    "plugins/_shared/hestia_gate_core.py": "core_rev.py",
}
sys.dont_write_bytecode = True


def git(*args):
    return subprocess.check_output(["git", *args], cwd=WT)


def blob(path, ref="HEAD"):
    return git("show", f"{ref}:{path}")


def sections(patch_text):
    out = {}
    for sec in patch_text.split("diff --git ")[1:]:
        out[sec.splitlines()[0].split(" b/", 1)[1]] = sec
    return out


def hunks(section):
    out, cur = [], None
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            cur = {"start": int(re.match(r"@@ -(\d+)", line).group(1)) - 1, "old": [], "new": []}
            out.append(cur)
        elif cur is not None and line[:1] in " +-":
            if line.startswith(("--- a/", "+++ b/")):
                continue
            if line[0] in " -":
                cur["old"].append(line[1:])
            if line[0] in " +":
                cur["new"].append(line[1:])
    return out


def apply_offset_tolerant(path, section, text):
    lines = text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(section):
        old, new = h["old"], h["new"]
        at = [i for i in range(pos, len(lines) - len(old) + 1) if lines[i:i + len(old)] == old]
        assert len(at) == 1, (path, h["start"], len(at))
        out.extend(lines[pos:at[0]])
        out.extend(new)
        pos = at[0] + len(old)
    out.extend(lines[pos:])
    return "".join(out)


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True) if old_text is not None else []
    out, pos = [], 0
    for h in hunks(section):
        start = h["start"] if h["old"] else h["start"] + 1
        start = max(start, 0) if old_text is not None else 0
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def main():
    change = sections((HERE / "source-1330b.diff").read_text(encoding="utf-8"))
    assert set(change) <= set(SOURCES), set(change) - set(SOURCES)
    OUT.mkdir(parents=True, exist_ok=True)
    patched = {}
    for path, name in SOURCES.items():
        patched[path] = (apply_offset_tolerant(path, change[path], blob(path).decode())
                         if path in change else blob(path).decode())
        (OUT / name).write_text(patched[path], encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    served_abs = {(WT / p).resolve(): patched[p].encode() for p in SOURCES}
    real_read = pathlib.Path.read_bytes

    def served(self):
        return served_abs.get(self.resolve()) or real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks-gt emitted {n} files")

    chunks = []
    for path in SOURCES:
        a = blob(path).decode().splitlines(True)
        b = patched[path].splitlines(True)
        if a != b:
            chunks.append(f"diff --git a/{path} b/{path}\n" + "".join(
                difflib.unified_diff(a, b, f"a/{path}", f"b/{path}")))
    body = "".join(chunks) + gt_out.read_text(encoding="utf-8")
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    for old in OUT.glob("*.patch"):
        old.rename(OUT / (old.name + ".prev"))
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        got = strict_apply(blob(path).decode(), sec)
        want = patched[path] if path in patched else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    head = git("rev-parse", "HEAD").decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
