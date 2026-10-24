#!/usr/bin/env python3
"""Build hestia#1327 held v3 over the worktree's HEAD, in memory, writing no governed path.

Re-runnable at apply time: if main moves under the window, run it again on the new main and the
patch is re-cut, not re-derived (cbp-to-hub-1327-apply-window-yes-2026-10-23.md).

  - The source hunks (gate core, decide contract test, shell battery) are v2's (b8c87abd), applied
    offset-tolerantly: each hunk's old block must occur in HEAD's file exactly once.
    The one hunk that drifted textually is the contract test's run list, which is re-done with
    an exact-once insertion after the same neighbour as v2's.
  - The hooks-gt copy and the five manifests are emitted by HEAD's own tools/hooks_gt.emit_patch
    with the core's source read served from the patched copy.
  - The patch is named by its sha256 and verified: applied in memory to HEAD's blobs it must
    reproduce the patched sources and hooks_gt.build()'s tree exactly.

argv: <hestia worktree at the base> <v2 patch path> <out dir>
Writes: <out>/core_rev.py, contract_rev.py, battery_rev.py (neutral names) and <out>/<sha256>.patch.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, V2, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
V2_SHA = "b8c87abd072e5d14ca73390833d714def735b6556a051f426a29726ff2fe1ace"
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_gate_core.py"
CONTRACT = "tools/one_gate_decide_contract_test.py"
BATTERY = "tools/shell_scope_reach_battery_test.py"
SOURCES = {CORE: "core_rev.py", CONTRACT: "contract_rev.py", BATTERY: "battery_rev.py"}
LIST_HUNK = "    test_an_unenumerated_reach_is_refused_with_rewrite_guidance,\n"
LIST_ADD = "    test_a_reach_that_names_nothing_opens_no_scope_request,\n"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT)


def sections(patch_text):
    out = {}
    for sec in patch_text.split("diff --git ")[1:]:
        path = sec.splitlines()[0].split(" b/", 1)[1]
        out[path] = sec
    return out


def hunks(section):
    """Every hunk of a section, fully read (a lazy yield would hand out half-filled hunks)."""
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
        if path == CONTRACT and LIST_ADD in new and LIST_ADD not in old:
            continue  # the drifted run-list hunk: re-done below, by anchor
        at = [i for i in range(pos, len(lines) - len(old) + 1) if lines[i:i + len(old)] == old]
        assert len(at) == 1, (path, h["start"], len(at))
        out.extend(lines[pos:at[0]])
        out.extend(new)
        pos = at[0] + len(old)
    out.extend(lines[pos:])
    result = "".join(out)
    if path == CONTRACT:
        assert result.count(LIST_HUNK) == 1 and LIST_ADD not in result
        result = result.replace(LIST_HUNK, LIST_HUNK + LIST_ADD)
    return result


def strict_apply(old_text, section):
    """Apply a section at its stated positions (the patch is cut against HEAD: zero offset)."""
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
    v2 = V2.read_bytes()
    assert hashlib.sha256(v2).hexdigest() == V2_SHA, "v2 patch is not b8c87abd"
    v2s = sections(v2.decode())
    OUT.mkdir(parents=True, exist_ok=True)
    patched = {}
    for path, name in SOURCES.items():
        patched[path] = apply_offset_tolerant(path, v2s[path], blob(path).decode())
        (OUT / name).write_text(patched[path], encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)  # the base GT holds before we touch it
    core_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        if self.resolve() == core_abs:
            return patched[CORE].encode()
        return real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    assert n == 6, f"expected GT core + 5 manifests, got {n} files"

    chunks = []
    for path in SOURCES:
        a = blob(path).decode().splitlines(True)
        b = patched[path].splitlines(True)
        chunks.append(f"diff --git a/{path} b/{path}\n" + "".join(
            difflib.unified_diff(a, b, f"a/{path}", f"b/{path}")))
    body = chunks[0] + gt_out.read_text(encoding="utf-8") + "".join(chunks[1:])
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    for old in OUT.glob("*.patch"):
        old.rename(OUT / (old.name + ".prev"))
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    # Verify: the patch, applied in memory to HEAD, reproduces every intended file exactly.
    for path, sec in sections(body).items():
        got = strict_apply(blob(path).decode(), sec)
        want = patched[path] if path in patched else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    gt_core = tree["hooks-gt/_shared/hestia_gate_core.py"]
    assert hooks_gt.strip_header(gt_core) == patched[CORE].encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
