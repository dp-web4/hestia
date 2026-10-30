#!/usr/bin/env python3
"""hestia #1331 follow-ups: Gate 1a judges the links an act REACHES without naming them (globs/braces, a cd inside
the line, readers that follow links). In-process through tools/grant_modes_gate_test's fixtures; the "secret" is a
FAKE file in a temp workspace whose path carries the innate token. A held overlay check, not test-shaped on purpose:
run against main's core it fails the REACH and OVERFLOW rows by design.
Run: python3 held/build-1331f/link_reach_check.py <dir with core_rev.py | "">   ("" = this worktree's own core)"""
import importlib.util
import os
import pathlib
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else ""
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
if OUT:
    spec = importlib.util.spec_from_file_location("hestia_gate_core", pathlib.Path(OUT) / "core_rev.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_core"] = mod
    sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
    spec.loader.exec_module(mod)
sys.path.insert(0, str(ROOT / "tools"))
import grant_modes_gate_test as g  # noqa: E402

REACH = [
    ("glob *", "cat *.txt"), ("glob ?", "cat note?.txt"), ("glob [..]", "cat [n]otes.txt"),
    ("glob into a dir link", "cat keys/*"), ("glob one level down", "cat sub/*"),
    ("brace", "cat {notes,plain}.txt"), ("cd && cat", "cd sub && cat key.txt"),
    ("cd ; cat", "cd sub; cat key.txt"), ("(cd && cat)", "(cd sub && cat key.txt)"),
    ("pushd && cat", "pushd sub && cat key.txt"), ("grep -R .", "grep -R key ."),
    ("rg -L", "rg -L key"), ("find -L -exec cat", "find -L . -name 'id_*' -exec cat {} +"),
    ("cp -rL", "cp -rL sub sub2"), ("tar -h", "tar -chf clean/out.tar ."),
    # nomad's #1435 review: find lists links and its -exec reader opens them; zip/7z follow by default; env -C is a cd
    ("find -exec without -L", "find sub -type l -exec cat {} \\;"),
    ("find . -name quoted -exec cat", "find . -name '*.txt' -exec cat {} +"),
    ("zip -r (follows by default)", "zip -r clean/out.zip ."),
    ("7z a (follows by default)", "7z a clean/out.7z sub"),
    ("env -C dir", "env -C sub cat key.txt"),
    ("env --chdir=dir", "env --chdir=sub cat key.txt"),
    ("cd .. then a relative path", "cd .. && cat hestia/notes.txt"),
]
ORDINARY = [
    ("plain file", "cat plain.txt"), ("glob on a clean dir", "cat clean/*.txt"),
    ("cd clean && cat", "cd clean && cat a.txt"), ("grep -R a clean dir", "grep -R key clean"),
    ("an in-repo link (not secret)", "cat clean/alias.txt"), ("rg without -L", "rg key"),
    ("grep -r on a clean dir", "grep -r key clean"), ("a glob naming nothing", "ls zz*"),
    ("a glob under the bound", "ls ../other/wide/f1*.txt"), ("named link (#1433)", "cat notes.txt"),
    # nomad's #1435 review: a quoted pattern is find's, not the shell's; zip -y stores links; git prints link text
    ("find a clean dir, quoted pattern", "find clean -name '*.txt' -exec cat {} +"),
    ("zip -ry stores links", "zip -ry clean/out.zip sub"),
    ("7z a -snl stores links", "7z a -snl clean/out.7z sub"),
    ("git -C sub show (link text, not target)", "git -C sub show HEAD:key.txt"),
    ("a quoted glob naming nothing", "grep -n 'no*such' clean/a.txt"),
]
OVERFLOW = [("glob of 300 files", "cat ../other/wide/*.txt")]
#: What main's core (#1433) says for the ordinary rows: the reach work must leave each exactly as it was.
ORDINARY_WANT = {"named link (#1433)": "deny/egress.secret"}


def main():
    bad = []
    with g._Workspace() as ws:
        repo = os.path.join(ws, "hestia")
        other = os.path.join(ws, "other")
        sub, clean = os.path.join(repo, "sub"), os.path.join(repo, "clean")
        wide, deep = os.path.join(other, "wide"), os.path.join(other, "deep")
        for d in (sub, clean, wide, deep):
            os.makedirs(d)
        fake = os.path.join(ws, "elsewhere", ".ssh")
        os.makedirs(fake)
        tgt = os.path.join(fake, "id_fixture")
        open(tgt, "w").write("not a key\n")
        os.symlink(tgt, os.path.join(repo, "notes.txt"))
        os.symlink(tgt, os.path.join(sub, "key.txt"))
        os.symlink(fake, os.path.join(repo, "keys"))
        open(os.path.join(repo, "plain.txt"), "w").write("x\n")
        for n in ("a.txt", "b.txt"):
            open(os.path.join(clean, n), "w").write("key\n")
        os.symlink(os.path.join(clean, "a.txt"), os.path.join(clean, "alias.txt"))
        for i in range(300):
            open(os.path.join(wide, f"f{i}.txt"), "w").close()
        for i in range(101):
            dd = os.path.join(deep, f"d{i}")
            os.makedirs(dd)
            for j in range(100):
                open(os.path.join(dd, f"f{j}"), "w").close()
        snap = g._snapshot(ws, standing=[{"path": repo, "recursive": True}, {"path": other, "recursive": True}])
        prof, pol = g._policy(snap)

        def v(cmd):
            ev = g.core.NormalizedEvent(tool="Bash", paths=[], command=cmd, cwd=repo)
            r = g.core.evaluate(ev, prof, ws, policy=pol)
            return f"{r.decision}/{r.rule or '-'}"

        for name, cmd in REACH:
            got = v(cmd)
            if got != "deny/egress.secret":
                bad.append(f"REACH {name}: egress.secret expected, got {got}")
        for name, cmd in ORDINARY:
            got, want = v(cmd), ORDINARY_WANT.get(name, "allow/-")
            if got != want:
                bad.append(f"ordinary {name}: {want} expected, got {got}")
        for name, cmd in OVERFLOW:
            got = v(cmd)
            if got != "deny/mrh.command.unenumerated":
                bad.append(f"OVERFLOW {name}: mrh.command.unenumerated expected, got {got}")

        # BOUNDED EXECUTION (Nova's #1435 review): the bound must stop the work, not only decide the verdict. Every
        # directory entry the gate reads is counted, by wrapping os.scandir around evaluate only.
        big = os.path.join(other, "big")
        os.makedirs(big)
        for i in range(12000):
            open(os.path.join(big, f"e{i}"), "w").close()
        locked = os.path.join(other, "locked")
        os.makedirs(os.path.join(locked, "inner"))
        os.chmod(os.path.join(locked, "inner"), 0)
        limit = getattr(g.core, "LINK_WALK_LIMIT", None)
        real_scandir, read = os.scandir, [0]

        class _Counting:
            def __init__(self, path):
                self._it = real_scandir(path)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._it.close()

            def __iter__(self):
                return self

            def __next__(self):
                e = next(self._it)
                read[0] += 1
                return e

            def close(self):
                self._it.close()

        def counted(cmd):
            read[0] = 0
            os.scandir = _Counting
            try:
                return v(cmd)
            finally:
                os.scandir = real_scandir

        # The glob scan budget, at its real value: a caller-written pattern over one 12,000-entry dir, and 300 matches.
        scan_cap = getattr(g.core, "LINK_GLOB_SCAN_LIMIT", None)
        for name, cmd in [("a glob over one 12,000-entry dir", "cat ../other/big/*"),
                          ("a glob of 300 matches", "cat ../other/wide/*.txt")]:
            got = counted(cmd)
            if got != "deny/mrh.command.unenumerated":
                bad.append(f"BOUNDED {name}: mrh.command.unenumerated expected, got {got}")
            if scan_cap is None or read[0] > scan_cap + 1:
                bad.append(f"BOUNDED {name}: read {read[0]} directory entries, the bound is {scan_cap}")
        # The walk budget's MECHANICS, at a small cap so the fixture stays small: lowered to 10,000 for this one row,
        # a walk over the 12,000-entry dir must stop by 10,001 entries read.
        if limit is not None:
            g.core.LINK_WALK_LIMIT = 10000
        try:
            got = counted("grep -R key ../other/big")
        finally:
            if limit is not None:
                g.core.LINK_WALK_LIMIT = limit
        if got != "deny/mrh.command.unenumerated" or read[0] > 10001:
            bad.append(f"BOUNDED a walk past a lowered 10,000 cap: {got}, read {read[0]} directory entries")
        # The walk budget's VALUE (nomad's #1435 review): walks the size of a real repo are allowed when they reach no
        # link, so a routine `find DIR -exec` or `grep -R` at a repo root is not refused for nothing.
        for name, cmd in [("a walk over 12,000 entries, no link", "grep -R key ../other/big"),
                          ("a walk over 10,100 entries, no link", "grep -R key ../other/deep"),
                          ("find over 12,000 entries -exec, no link", "find ../other/big -name nope -exec cat {} +")]:
            got = v(cmd)
            if got != "allow/-":
                bad.append(f"WALK-BUDGET {name}: allow expected, got {got}")
        got = v("grep -R key ../other/locked")
        os.chmod(os.path.join(locked, "inner"), 0o755)
        if got != "deny/mrh.command.unenumerated":
            bad.append(f"BOUNDED an unreadable dir under a walk: mrh.command.unenumerated expected, got {got}")
    for b in bad:
        print("FAIL", b)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(REACH)} reach rows, {len(ORDINARY)} ordinary rows, "
          f"{len(OVERFLOW)} overflow row, 4 bounded-execution rows, 3 walk-budget rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
