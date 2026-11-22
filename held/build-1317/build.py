#!/usr/bin/env python3
"""Build the held patch for hestia #1317 (glob variant) over the worktree's HEAD, in memory, writing no
governed path.

Re-runnable at apply time: the edit is an exact-once anchor in HEAD's gate core, so a moved main costs a
re-run, not a review cycle (the same build shape as held 1595 / 1560).

  1. Pass 3's relative vote judges a GLOB interpretation only where the glob's own directory exists. It
     took the dirname of the probe's directory instead, one level too high, so after `cd D &&` the
     event-cwd reading `<cwd>/tools/*` was refused although `<cwd>/tools` does not exist (#1317).
  2. tools/gate_glob_after_cd_test.py (new, 12 rows) is added.
The hooks-gt copy and the manifests are emitted by HEAD's own tools/hooks_gt.emit_patch with the core read
served from the patched copy. The patch is named by its sha256 and verified: applied in memory to HEAD's
blobs it must reproduce the patched core, the new test and hooks_gt.build()'s tree exactly.

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
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_gate_core.py"
TEST = "tools/gate_glob_after_cd_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    return once(src,
                '            if not os.path.lexists(os.path.dirname(probe.rstrip("*").rstrip("/")) or "/"):\n'
                '                continue\n',
                '            # WHERE IT COULD NAME SOMETHING (#1317): a plain path when its parent exists; a glob\n'
                '            # only when its OWN directory does, since a glob expands inside that directory and a\n'
                '            # missing one leaves the word literal. Taking the dirname of a glob probe\'s `<dir>`\n'
                '            # climbed a level, so after `cd D &&` the event-cwd reading `<cwd>/tools/*` was refused\n'
                '            # while `<cwd>/tools` did not exist (McNugget, 2026-11-13 and 2026-11-16).\n'
                '            anchor = (probe[:-2] if globbed and probe.endswith("/*")\n'
                '                      else os.path.dirname(probe.rstrip("*").rstrip("/")))\n'
                '            if not os.path.lexists(anchor or "/"):\n'
                '                continue\n')


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
    core_new = patch_core(blob(CORE))
    test_new = (HERE / "gate_glob_after_cd_test.py.held").read_text(encoding="utf-8")
    (OUT / "core_rev.py").write_text(core_new, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    core_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return core_new.encode() if self.resolve() == core_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(CORE, blob(CORE), core_new) + gt_out.read_text(encoding="utf-8") + diff(TEST, None, test_new)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    # No sweep of other *.patch in OUT: held/ on main tracks other seats' patches (the 1560 build's
    # rename-to-.prev sweep would rename all of them if OUT is held/).
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        old = None if path == TEST else blob(path)
        got = strict_apply(old, sec)
        want = core_new if path == CORE else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree["hooks-gt/_shared/hestia_gate_core.py"]) == core_new.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
