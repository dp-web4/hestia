#!/usr/bin/env python3
"""Build the held patch for hestia #1595 over the worktree's HEAD, in memory, writing no governed path.

Re-runnable at apply time: every edit is an exact-once anchor in HEAD's gate core, so a moved main costs a
re-run, not a review cycle (the #1327 v3 lesson; the same build shape as held 1560).

  1. pgrep / pkill join the grep family's grammar: the first positional is a PATTERN (text), `-F` /
     `--pidfile` is a file, and pkill's signal words (`-HUP`, `-9`, `-SIGTERM`) are flags (#1595).
  2. tools/gate_pgrep_pattern_test.py (new, 15 rows) is added.
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
TEST = "tools/gate_pgrep_pattern_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    src = once(src, '_PATTERN_HEADS = frozenset(("grep", "egrep", "fgrep", "rg", "git-grep"))\n',
               '_PATTERN_HEADS = frozenset(("grep", "egrep", "fgrep", "rg", "git-grep", "pgrep", "pkill"))\n'
               '#: `pgrep` / `pkill` (#1595): the first positional is a regex matched against process names or\n'
               '#: (`-f`) command lines; neither tool opens it. Their one FILE operand is `-F` / `--pidfile`.\n'
               '#: `signal_words`: pkill\'s `-HUP` / `-9` / `-SIGTERM` is a flag, not a cluster that hands `-U` or\n'
               '#: `-P` a value. Options are the union of the BSD (macOS) and procps (Linux) spellings.\n'
               '_PGREP_SPEC = {"pattern_first": True, "signal_words": True,\n'
               '               "file_opts": {"-F", "--pidfile"},\n'
               '               "value_opts": {"-G", "-g", "-P", "-s", "-t", "-U", "-u", "-d", "-c", "-O", "-r",\n'
               '                              "--delimiter", "--group", "--pgroup", "--parent", "--session",\n'
               '                              "--terminal", "--euid", "--uid", "--ns", "--nslist", "--signal",\n'
               '                              "--older", "--runstates", "--cgroup", "--env"}}\n')
    src = once(src, '    "grep": _GREP_SPEC, "egrep": _GREP_SPEC, "fgrep": _GREP_SPEC, "zgrep": _GREP_SPEC,\n',
               '    "grep": _GREP_SPEC, "egrep": _GREP_SPEC, "fgrep": _GREP_SPEC, "zgrep": _GREP_SPEC,\n'
               '    "pgrep": _PGREP_SPEC, "pkill": _PGREP_SPEC,\n')
    return once(src, '                     | spec.get("value_opts", set()) | spec.get("code_opts", set()))\n'
                     '            if eq:\n',
                '                     | spec.get("value_opts", set()) | spec.get("code_opts", set()))\n'
                '            if spec.get("signal_words") and w not in takes \\\n'
                '                    and re.fullmatch(r"-(?:SIG)?[A-Z][A-Z0-9+-]*|-[0-9]+", w):\n'
                '                continue                                   # `pkill -HUP`, `-9`, `-SIGTERM` (#1595)\n'
                '            if eq:\n')


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
    test_new = (HERE / "gate_pgrep_pattern_test.py").read_text(encoding="utf-8")
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
