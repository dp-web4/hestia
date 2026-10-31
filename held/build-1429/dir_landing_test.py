#!/usr/bin/env python3
"""hestia #1429: a relative word landing INSIDE the workspace after `cd` is judged by pass 1's in-workspace rule,
not by the outside rule on its realpath. command_scope_reach on a fixture workspace (no daemon); argv[1]: a dir
holding core_rev.py (none = the real module). The fixture is built beside this file and removed afterwards."""
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
if (OUT / "core_rev.py").is_file():
    spec = importlib.util.spec_from_file_location("hestia_gate_core", OUT / "core_rev.py")
    G = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_core"] = G
    spec.loader.exec_module(G)
else:
    import hestia_gate_core as G  # noqa: E402

# NOT under a temp root: /tmp is always reachable, which would make every row pass vacuously.
base = tempfile.mkdtemp(prefix="gate1429-", dir=str(pathlib.Path(__file__).resolve().parent))
ws = os.path.join(base, "ws")
granted = os.path.join(ws, "membot")
os.makedirs(os.path.join(granted, ".venv", "bin"))
os.makedirs(os.path.join(ws, "notgranted"))
open(os.path.join(ws, "notgranted", "data.txt"), "w").close()
os.symlink("/usr/bin/python3", os.path.join(granted, ".venv", "bin", "python"))
os.symlink(os.path.join(ws, "notgranted", "data.txt"), os.path.join(granted, "peek"))
outside = os.path.join(base, "outside", ".ssh")
os.makedirs(outside)
open(os.path.join(outside, "id_test"), "w").close()
os.symlink(os.path.join(outside, "id_test"), os.path.join(granted, "key"))
# nomad's review: directory links inside the granted repo, and a plain subdirectory
os.symlink(os.path.join(ws, "notgranted"), os.path.join(granted, "linkdir"))
os.symlink(outside, os.path.join(granted, "sshdir"))
os.makedirs(os.path.join(granted, "sub"))
open(os.path.join(granted, "sub", "own.txt"), "w").close()
scopes = ["membot"]

ALLOW = [
    ("the venv interpreter by absolute path (unchanged)", f"{granted}/.venv/bin/python -c 1"),
    ("the venv interpreter relative after cd (the #1429 case)", f"cd {granted} && .venv/bin/python -c 1"),
    ("./.venv/bin/python after cd", f"cd {granted} && ./.venv/bin/python -c 1"),
    ("a plain in-repo file after cd", f"cd {granted} && cat .venv/bin/python"),
    ("cd into a real subdirectory, then a bare word", f"cd {granted}/sub && cat own.txt"),
]
DENY = [
    ("a link to a forbidden target after cd (egress first)", f"cd {granted} && cat ./key"),
    ("a link into an ungranted repo after cd", f"cd {granted} && cat ./peek"),
    ("an ungranted repo after cd", f"cd {ws}/notgranted && cat ./data.txt"),
    ("a relative escape out of the workspace after cd", f"cd {granted} && cat ../../outside/.ssh/id_test"),
    # nomad's review of 79b60b56: the same rule for directory links, mid-path and as the cd target
    ("a dir link mid-path into an ungranted repo", f"cd {granted} && cat ./linkdir/data.txt"),
    ("a dir link mid-path to a .ssh dir", f"cd {granted} && cat ./sshdir/id_test"),
    ("cd into a .ssh dir link, then a bare word", f"cd {granted}/sshdir && cat id_test"),
    ("a .. walk out of a subdirectory into an ungranted repo", f"cd {granted} && cat sub/../../notgranted/data.txt"),
    ("a second cd into an ungranted repo", f"cd {granted} && cd ../notgranted && cat data.txt"),
    ("cd ; a link to a key", f"cd {granted}; cat ./key"),
    ("pushd, a link to a key", f"pushd {granted} && cat ./key"),
    ("a subshell cd, a link into an ungranted repo", f"(cd {granted} && cat ./peek)"),
    ("cd INTO a dir link to an ungranted repo, then a bare word (the gap)", f"cd {granted}/linkdir && cat data.txt"),
    ("cd, cd into the dir link, then a bare word", f"cd {granted} && cd linkdir && cat data.txt"),
]
bad = []
for name, cmd in ALLOW:
    ok, tok, _ = G.command_scope_reach(cmd, scopes, ws, ws)
    if not ok:
        bad.append(f"ALLOW expected, refused ({tok!r}): {name}")
for name, cmd in DENY:
    ok, tok, _ = G.command_scope_reach(cmd, scopes, ws, ws)
    if ok:
        bad.append(f"DENY expected, allowed: {name}")
shutil.rmtree(base, ignore_errors=True)
for b in bad:
    print("FAIL", b)
print(f"{'PASS' if not bad else 'FAIL'}: {len(ALLOW)} allow rows, {len(DENY)} deny rows")
sys.exit(1 if bad else 0)
