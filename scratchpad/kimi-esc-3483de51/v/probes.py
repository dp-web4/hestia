# Direct probes of the v2 _COMPOSED_READ_TOOLS branch, beyond the suite's cases.
import importlib.util
import pathlib
import sys
import tempfile

V = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hgc", V / "gclosure.py")
g = importlib.util.module_from_spec(spec)
sys.modules["hgc"] = g
spec.loader.exec_module(g)

GATE = "/w/hestia/plugins/_shared/hestia_single_gate.py"
CWD = tempfile.mkdtemp(prefix="hgc-probe-")

probes = [
    ("search notebook_path dest -> write",
     g.classify("search", {"pattern": "x", "path": "/tmp", "notebook_path": GATE}, cwd=CWD), "write"),
    ("git_read notebook_path dest -> write",
     g.classify("git_read", {"op": "log", "notebook_path": GATE}, cwd=CWD), "write"),
    ("search + unreadable git apply -> write (opaque fail-close)",
     g.classify("search", {"path": GATE, "command": "git apply nonexistent.patch"}, cwd=CWD), "write"),
    ("search, no path key, command writes gate -> write",
     g.classify("search", {"command": "tee " + GATE}, cwd=CWD), "write"),
    ("search reads gate, writes /tmp -> read",
     g.classify("search", {"path": GATE, "command": "grep x " + GATE + " > /tmp/out"}, cwd=CWD), "read"),
    ("git_read, substitution dest, gate path mention -> (Bash-consistent)",
     g.classify("git_read", {"op": "log", "path": GATE, "command": "cp /tmp/x $DEST"}, cwd=CWD), None),
    ("search, command=None, path only -> read",
     g.classify("search", {"pattern": "x", "path": GATE, "command": None}, cwd=CWD), "read"),
    ("uppercase SEARCH unknown -> write",
     g.classify("SEARCH", {"pattern": "x", "path": GATE}, cwd=CWD), "write"),
]

rc = 0
for name, verdict, want in probes:
    got = verdict.classification
    ok = "?" if want is None else ("OK " if got == want else "MISMATCH")
    if want is not None and got != want:
        rc = 1
    print(f"{ok} {name}: got={got} want={want} rule={getattr(verdict, 'rule', None)} marker={getattr(verdict, 'marker', None)}")
sys.exit(rc)
