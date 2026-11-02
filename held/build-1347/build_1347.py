#!/usr/bin/env python3
"""Re-cut #1347's reviewed gate change over the worktree's HEAD, in memory, writing no governed path.

The reviewed change is what landed on #1347's branch under operator approval on 2026-10-19:
hestia_gate_core.py 28fcf12e (escalation d0f489cc9a2d2f8c) and hestia_gate_mechanism.py 5616d4a1
(escalation cbbdd0e325cd5fa6), as the diff <REVIEWED_BASE>..<REVIEWED_HEAD> of those two files.
Its hunks are applied to HEAD's blobs offset-tolerantly (each hunk's old block must occur in
HEAD's file exactly once), the hooks-gt copies and manifests are emitted by HEAD's own
tools/hooks_gt.emit_patch with the two sources served from the patched copies, and the patch is
named by its sha256 and verified by re-applying it in memory.

Re-runnable: if main moves under the window, run it again on the new main.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/core_rev.py, <out>/mech_rev.py (neutral names) and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
REVIEWED_BASE = "ee7f00d8b94584b0c43a0e0ed6b08668a2e5db7c"
REVIEWED_HEAD = "d6f4e0c2"
CORE = "plugins/_shared/hestia_gate_core.py"
MECH = "plugins/_shared/hestia_gate_mechanism.py"
SOURCES = {CORE: "core_rev.py", MECH: "mech_rev.py"}
REVIEWED_SHA = {CORE: "28fcf12ea46a6a82e0276497c0958802a75a9de43ffe3870de3646cb26d645cf",
                MECH: "5616d4a16b2c4e21d592b209bc8c10f3016c0076638cd3aac075ddf27d10acad"}
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
    for path, sha in REVIEWED_SHA.items():
        assert hashlib.sha256(blob(path, REVIEWED_HEAD)).hexdigest() == sha, f"{path} is not the reviewed copy"
    reviewed = sections(git("diff", "--no-color", "-U3", REVIEWED_BASE, REVIEWED_HEAD, "--",
                            CORE, MECH).decode())
    OUT.mkdir(parents=True, exist_ok=True)
    patched = {}
    for path, name in SOURCES.items():
        patched[path] = apply_offset_tolerant(path, reviewed[path], blob(path).decode())
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
