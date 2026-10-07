#!/usr/bin/env python3
"""Review held 29ae13a6 in memory; never install or execute a classified command."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655"
sys.dont_write_bytecode = True


def blob(path):
    return subprocess.check_output(["git", "show", "18f91db:" + path], cwd=ROOT)


def reconstructed():
    patch = (ROOT / "held" / (DIGEST + ".patch")).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == DIGEST
    result = {}
    for section in patch.decode().split("diff --git ")[1:]:
        path = section.splitlines()[0].split(" b/", 1)[1]
        old = blob(path).decode().splitlines(keepends=True)
        out, pos, active = [], 0, False
        for line in section.splitlines(keepends=True)[1:]:
            if line.startswith("@@ "):
                start = int(re.match(r"@@ -(\d+)", line).group(1)) - 1
                out.extend(old[pos:start])
                pos, active = start, True
            elif active and line[:1] in " +-":
                if line[0] in " -":
                    assert old[pos] == line[1:], (path, pos)
                    pos += 1
                if line[0] in " +":
                    out.append(line[1:])
        out.extend(old[pos:])
        result[path] = "".join(out)
    return result


def module(name, path, source):
    loaded = types.ModuleType(name)
    loaded.__file__ = str(ROOT / path)
    sys.modules[name] = loaded
    exec(compile(source, loaded.__file__, "exec"), loaded.__dict__)
    return loaded


def main():
    sources = reconstructed()
    shared = "plugins/_shared/"
    for name in ("hestia_gate_core", "hestia_gate_mechanism", "hestia_governance_closure"):
        path = shared + name + ".py"
        assert (ROOT / path).read_bytes() == blob(path), path
    sys.path.insert(0, str(ROOT / shared))
    gate = module("hestia_single_gate", shared + "hestia_single_gate.py",
                  sources[shared + "hestia_single_gate.py"])
    suite = module("held_registered_surface_test", shared + "registered_surface_test.py",
                   sources[shared + "registered_surface_test.py"])
    for test in suite.ALL:
        test()
    print("Exact held registered-surface suite:", len(suite.ALL), "passed")

    # The supplied differential uses ordinary names. Pin an escaped literal opening
    # bracket followed by a real wildcard as an additional matcher-level case.
    with tempfile.TemporaryDirectory(prefix="held-matcher-review-") as directory:
        cases = [(r"x\[ab]y*", "x[ab]yes"),
                 (r"x\[ab]efore_*", "x[ab]efore_tool.py")]
        for _, name in cases:
            Path(directory, name).touch()
        for pattern, expected in cases:
            output = subprocess.check_output([
                "bash", "--noprofile", "--norc", "-c",
                'shopt -s nullglob; cd "$1" && for f in $2; do printf "%s\\0" "$f"; done',
                "_", directory, pattern], text=True)
            names = list(filter(None, output.split("\0")))
            assert expected in names, (pattern, names)
            matched = gate._reaches_registered_entry(
                os.path.join(directory, pattern), [os.path.join(directory, expected)])
            assert not matched, (pattern, expected, "counterexample no longer reproduces")
            print("Conservative-match counterexample:", repr(pattern), "->", repr(expected))
    print("Scope: matcher and supplied producer tests only; no daemon approval claim.")


if __name__ == "__main__":
    main()
