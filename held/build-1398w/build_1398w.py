#!/usr/bin/env python3
"""Cut hestia #1398's WRITE HALF (a narrowed floor entry serves the modes it holds, where no grant
of the member's own reaches) over the worktree's HEAD, in memory, writing no governed path.

This patch is the FOURTH in the held stack and applies to the tree AFTER part C (#1394,
`source-1386.diff`) and the read half (#1406, `source-1398.diff`) have landed. So the BASE here is
HEAD with those two source diffs applied (offset-tolerantly, each hunk's old block occurring exactly
once), the change is `source-1398w.diff` applied on that base, and every section of the emitted
patch is a diff FROM the base TO the result: the gate core, the mechanism, the hooks-gt copies and
the manifests (the base's hooks-gt tree is built from the base sources and served as "the current
files" while HEAD's own tools/hooks_gt.emit_patch emits the change). The patch is named by its
sha256 and verified by strict re-application onto the base in memory.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/core_rev.py, <out>/mech_rev.py (the RESULT, neutral names), <out>/base_core_rev.py,
<out>/base_mech_rev.py (the base, for diffing) and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
HERE = pathlib.Path(__file__).resolve().parent
CORE = "plugins/_shared/hestia_gate_core.py"
MECH = "plugins/_shared/hestia_gate_mechanism.py"
SOURCES = {CORE: "core_rev.py", MECH: "mech_rev.py"}
UPSTREAM = ["source-1386.diff", "source-1398.diff"]   # part C, then the read half
CHANGE = "source-1398w.diff"
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


def apply_diff(texts, diff_name):
    change = sections((HERE / diff_name).read_text(encoding="utf-8"))
    return {p: (apply_offset_tolerant(p, change[p], t) if p in change else t) for p, t in texts.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    head_texts = {p: blob(p).decode() for p in SOURCES}
    base = head_texts
    for d in UPSTREAM:
        base = apply_diff(base, d)
    patched = apply_diff(base, CHANGE)
    for path, name in SOURCES.items():
        (OUT / name).write_text(patched[path], encoding="utf-8")
        (OUT / ("base_" + name)).write_text(base[path], encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    real_read = pathlib.Path.read_bytes

    def serve(mapping):
        def served(self):
            return mapping.get(self.resolve()) or real_read(self)
        pathlib.Path.read_bytes = served

    # 1. The base's hooks-gt tree: built from the base sources.
    serve({(WT / p).resolve(): base[p].encode() for p in SOURCES})
    try:
        base_tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    # 2. The result, emitted against the base: the base tree stands in for the worktree's files.
    served_abs = {(WT / p).resolve(): patched[p].encode() for p in SOURCES}
    served_abs.update({(WT / p).resolve(): data for p, data in base_tree.items()})
    serve(served_abs)
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks-gt emitted {n} files (against the base tree)")

    chunks = []
    for path in SOURCES:
        a = base[path].splitlines(True)
        b = patched[path].splitlines(True)
        chunks.append(f"diff --git a/{path} b/{path}\n" + "".join(
            difflib.unified_diff(a, b, f"a/{path}", f"b/{path}")))
    body = "".join(chunks) + gt_out.read_text(encoding="utf-8")
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    for old in OUT.glob("*.patch"):
        old.rename(OUT / (old.name + ".prev"))
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        before = base[path] if path in base else base_tree[path].decode()
        got = strict_apply(before, sec)
        want = patched[path] if path in patched else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    head = git("rev-parse", "HEAD").decode().strip()
    print(f"base HEAD {head} + {' + '.join(UPSTREAM)}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
