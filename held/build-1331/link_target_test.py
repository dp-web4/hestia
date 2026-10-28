#!/usr/bin/env python3
"""hestia #1331 gaps (a)/(b): the innate egress.secret rule judges a link's resolved target. In-process,
through tools/grant_modes_gate_test's fixtures; the "secret" is a FAKE file in a temp workspace whose path
carries the innate token. Run: python3 held/build-1331/link_target_test.py <dir with core_rev.py | "">"""
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
        tgt = os.path.join(fake, "id_fixture")
        open(tgt, "w").write("not a key\n")
        link = os.path.join(repo, "notes.txt")
        os.symlink(tgt, link)
        plain = os.path.join(repo, "plain.txt")
        open(plain, "w").write("x\n")
        snap = g._snapshot(ws, standing=[{"path": repo, "recursive": True}])
        prof, pol = g._policy(snap)

        def v(tool, path=None, command=None):
            ev = g.core.NormalizedEvent(tool=tool, paths=[path] if path else [], command=command, cwd=repo)
            return g.core.evaluate(ev, prof, ws, policy=pol)

        must_secret = [
            ("control: the target by its real path", v("Bash", command=f"cat {tgt}")),
            ("(a) shell read of the link, relative", v("Bash", command="cat notes.txt")),
            ("(a') shell read of the link, absolute", v("Bash", command=f"cat {link}")),
            ("(b) Read of the link, absolute", v("Read", path=link)),
            ("(b') Read of the link, relative", v("Read", path="notes.txt")),
            ("a flag value naming the link", v("Bash", command="tool --input=notes.txt")),
        ]
        for name, r in must_secret:
            if r.rule != "egress.secret":
                bad.append(f"egress.secret expected, got {r.decision}/{r.rule}: {name}")
        # ordinary acts are untouched: a plain file, and a word that names nothing on disk
        for name, r in [("plain file, shell", v("Bash", command="cat plain.txt")),
                        ("plain file, Read", v("Read", path=plain)),
                        ("a word naming nothing", v("Bash", command="echo notes-v2.txt"))]:
            if r.blocks:
                bad.append(f"an ordinary act was refused: {name}: {r.rule} {r.reason}")
    for b in bad:
        print("FAIL", b)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(must_secret)} link rows, 3 ordinary rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
