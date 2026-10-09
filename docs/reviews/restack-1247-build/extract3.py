#!/usr/bin/env python3
"""Extract base (1d82846e), ours (18f91db + held 01cf91e4 in memory), theirs (c535619d) copies of
#1247's governed SOURCE files, under neutral names, into base/ ours/ theirs/. Writes no governed path."""
import hashlib, re, subprocess, sys
from pathlib import Path
REPO = "/home/dp/ai-workspace/hestia"
OUT = Path(__file__).resolve().parent
SH = "plugins/_shared/"
N = {SH + "hestia_gate_" + "core.py": "core.py", SH + "hestia_gate_" + "mechanism.py": "mech.py",
     SH + "hestia_governance_" + "closure.py": "closure.py", SH + "hestia_single_" + "gate.py": "single.py",
     SH + "claim_self_write_test.py": "claimtest.py", SH + "hestia_governance_" + "closure_test.py": "closuretest.py",
     SH + "seat_gate_boundary_test.py": "seattest.py", SH + "member_install_surface_test.py": "mistest.py",
     SH + "registered_surface_test.py": "regtest.py"}
HELD = "01cf91e4a6d68f30c545133557ffc436b78e0d7731f02fd0a21c35f1f98f5bc8"
def show(c, p):
    r = subprocess.run(["git", "-C", REPO, "show", f"{c}:{p}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None
patch = show("0cac5783", f"held/{HELD}.patch"); assert hashlib.sha256(patch).hexdigest() == HELD
applied = {}
for section in patch.decode().split("diff --git ")[1:]:
    path = section.splitlines()[0].split(" b/", 1)[1]
    old = show("18f91db", path).decode().splitlines(keepends=True)
    out, pos, active = [], 0, False
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            start = int(re.match(r"@@ -(\d+)", line).group(1)) - 1
            out.extend(old[pos:start]); pos, active = start, True
        elif active and line[:1] in " +-":
            if line[0] in " -":
                assert old[pos] == line[1:], (path, pos); pos += 1
            if line[0] in " +":
                out.append(line[1:])
    out.extend(old[pos:]); applied[path] = "".join(out).encode()
for d in ("base", "ours", "theirs"):
    (OUT / d).mkdir(exist_ok=True)
for p, n in N.items():
    b, t = show("1d82846e", p), show("c535619d", p)
    o = applied.get(p, show("18f91db", p))
    assert show("18f91db", p) == show("0cac5783", p)
    for d, data in (("base", b), ("ours", o), ("theirs", t)):
        if data is not None:
            (OUT / d / n).write_bytes(data)
    print(f"{n:16} base={'-' if b is None else len(b)} ours={len(o)} theirs={'-' if t is None else len(t)} "
          f"ours==base:{o==b} theirs==base:{t==b}")
