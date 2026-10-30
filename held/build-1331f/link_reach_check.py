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
]
ORDINARY = [
    ("plain file", "cat plain.txt"), ("glob on a clean dir", "cat clean/*.txt"),
    ("cd clean && cat", "cd clean && cat a.txt"), ("grep -R a clean dir", "grep -R key clean"),
    ("an in-repo link (not secret)", "cat clean/alias.txt"), ("rg without -L", "rg key"),
    ("grep -r on a clean dir", "grep -r key clean"), ("a glob naming nothing", "ls zz*"),
    ("a glob under the bound", "ls ../other/wide/f1*.txt"), ("named link (#1433)", "cat notes.txt"),
]
OVERFLOW = [("glob of 300 files", "cat ../other/wide/*.txt"),
            ("grep -R over 10,100 entries", "grep -R key ../other/deep")]
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
    for b in bad:
        print("FAIL", b)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(REACH)} reach rows, {len(ORDINARY)} ordinary rows, "
          f"{len(OVERFLOW)} overflow rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
