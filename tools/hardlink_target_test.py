#!/usr/bin/env python3
"""hestia #1331 class 4: a hardlink has no distinct realpath target, so the innate
egress.secret check rejects regular files with st_nlink > 1. Real filesystem fixtures;
link-creation failure is a test failure, never a skip. Pass a dir holding core_rev.py
to judge a revised copy.
"""
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


def main():
    bad = []
    with g._Workspace() as ws:
        repo = os.path.join(ws, "hestia")
        os.makedirs(repo, exist_ok=True)
        fake = os.path.join(ws, "elsewhere", ".ssh")
        os.makedirs(fake, exist_ok=True)
        target = os.path.join(fake, "id_fixture")
        with open(target, "w") as fh:
            fh.write("not a key\n")
        link = os.path.join(repo, "notes.txt")
        os.link(target, link)
        plain = os.path.join(repo, "plain.txt")
        with open(plain, "w") as fh:
            fh.write("ordinary data\n")
        ordinary = os.path.join(repo, "ordinary.txt")
        with open(ordinary, "w") as fh:
            fh.write("ordinary data\n")
        ordinary_hardlink = os.path.join(repo, "alias.txt")
        os.link(ordinary, ordinary_hardlink)
        snap = g._snapshot(ws, standing=[{"path": repo, "recursive": True}])
        prof, pol = g._policy(snap)

        def verdict(tool, path=None, command=None):
            event = g.core.NormalizedEvent(tool=tool, paths=[path] if path else [], command=command, cwd=repo)
            return g.core.evaluate(event, prof, ws, policy=pol)

        must_secret = [
            ("hardlink by relative shell name", verdict("Bash", command="cat notes.txt")),
            ("hardlink by absolute shell name", verdict("Bash", command=f"cat {link}")),
            ("hardlink by absolute Read", verdict("Read", path=link)),
            ("hardlink by relative Read", verdict("Read", path="notes.txt")),
            ("hardlink through a glob", verdict("Bash", command="cat note?.txt")),
            ("hardlink through a recursive reader", verdict("Bash", command="grep -R fixture .")),
            ("an ordinary hardlink carries the same cost", verdict("Read", path=ordinary_hardlink)),
        ]
        for name, result in must_secret:
            if result.rule != "egress.secret":
                bad.append(f"egress.secret expected, got {result.decision}/{result.rule}: {name}")
        for name, result in [
            ("single-link plain file, shell", verdict("Bash", command="cat plain.txt")),
            ("single-link plain file, Read", verdict("Read", path=plain)),
            ("a word naming nothing", verdict("Bash", command="echo notes-v2.txt")),
        ]:
            if result.blocks:
                bad.append(f"an ordinary act was refused: {name}: {result.rule} {result.reason}")
    for failure in bad:
        print("FAIL", failure)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(must_secret)} hardlink rows, 3 ordinary rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
