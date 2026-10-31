#!/usr/bin/env python3
"""Cut the hestia #944 endpoint patch over the worktree's HEAD, in memory, writing no governed path.

The change (change.py) is applied to HEAD's `plugins/_shared/hestia_gate_mechanism.py` by exact-once
text replacement, so re-running this on a newer main re-cuts the patch (the held stack moves the
manifests' digests; a stale patch costs a re-run, not a review cycle). The emitted patch carries the
mechanism diff plus every hooks-gt copy and manifest `tools/hooks_gt.emit_patch` produces, is named
by its sha256, and is verified by strict re-application in memory.

argv: <hestia worktree> <out dir>
Writes: <out>/mech_rev.py (the RESULT, a neutral name), <out>/base_mech_rev.py and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True
WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
HERE = pathlib.Path(__file__).resolve().parent
MECH = "plugins/_shared/hestia_gate_mechanism.py"
sys.path.insert(0, str(HERE))
import change  # noqa: E402


def git(*args):
    return subprocess.check_output(["git", *args], cwd=WT)


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


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(section):
        start = h["start"] if h["old"] else h["start"] + 1
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = git("show", f"HEAD:{MECH}").decode()
    patched = change.apply(base)
    (OUT / "mech_rev.py").write_text(patched, encoding="utf-8")
    (OUT / "base_mech_rev.py").write_text(base, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    real_read = pathlib.Path.read_bytes
    served = {(WT / MECH).resolve(): patched.encode()}

    def serve(self):
        return served.get(self.resolve()) or real_read(self)

    pathlib.Path.read_bytes = serve
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks-gt emitted {n} files")

    body = f"diff --git a/{MECH} b/{MECH}\n" + "".join(difflib.unified_diff(
        base.splitlines(True), patched.splitlines(True), f"a/{MECH}", f"b/{MECH}"))
    body += gt_out.read_text(encoding="utf-8")
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    for old in OUT.glob("*.patch"):
        old.rename(OUT / (old.name + ".prev"))
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        before = base if path == MECH else (WT / path).read_text(encoding="utf-8")
        want = patched if path == MECH else tree[path].decode()
        assert strict_apply(before, sec) == want, f"verify: {path}"
        print(f"  ok  {path}")
    print(f"base HEAD {git('rev-parse', 'HEAD').decode().strip()}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
