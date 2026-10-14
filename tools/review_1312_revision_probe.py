#!/usr/bin/env python3
"""Evaluate held dcc1ba10 in memory; never install or edit a gate file."""
import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
import types

BASE = "67b45517"
HEAD = "3889856ff1fcdd8fad49bd1470a0a97d853b2749"
PATCH = "dcc1ba10f584c179def43133dee060b4c8de0fd1df7665c30c189ea679887c56"
CORE = "plugins/_shared/hestia_gate_core.py"


def git_show(ref):
    return subprocess.check_output(["git", "show", ref], text=True)


def load_pair():
    source = git_show(f"{BASE}:{CORE}")
    patch = git_show(f"{HEAD}:held/{PATCH}.patch")
    assert hashlib.sha256(patch.encode()).hexdigest() == PATCH
    section = patch.split(f"diff --git a/{CORE} b/{CORE}\n", 1)[1].split("diff --git ", 1)[0]
    lines, result, pos = source.splitlines(keepends=True), [], 0
    for hunk in re.split(r"(?m)^@@ ", section)[1:]:
        header, body = hunk.split("\n", 1)
        start = int(re.match(r"-(\d+)", header).group(1)) - 1
        result.extend(lines[pos:start])
        pos = start
        for line in body.splitlines(keepends=True):
            if line.startswith((" ", "-")):
                assert lines[pos] == line[1:]
                if line.startswith(" "):
                    result.append(lines[pos])
                pos += 1
            elif line.startswith("+"):
                result.append(line[1:])
    result.extend(lines[pos:])
    modules = []
    for name, text in (("review_before", source), ("review_after", "".join(result))):
        mod = types.ModuleType(name)
        mod.__file__ = str(pathlib.Path(CORE).resolve())
        sys.modules[name] = mod
        exec(compile(text, mod.__file__, "exec"), mod.__dict__)
        modules.append(mod)
    return modules


def main():
    before, after = load_pair()
    # /tmp is implicitly granted; use temporary fixtures beneath the checkout.
    with tempfile.TemporaryDirectory(prefix="review-1312-revision-", dir=".") as root:
        root = pathlib.Path(root).resolve()
        ws, outside = root / "ws", root / "outside"
        (ws / "sub").mkdir(parents=True)
        outside.mkdir()
        (ws / "sub" / "sub").symlink_to(outside, target_is_directory=True)
        for directory in (ws, ws / "sub", outside):
            (directory / "secret.txt").write_text("fixture only\n")
        scopes = [f"path:{ws}/**"]

        for head in ["cd", "'cd'", "c''d", 'c"d"', "c\\d", "c\\\nd"]:
            cmd = "for f in secret.txt secret.txt secret.txt; do cat $f; " + head + " sub; done"
            subprocess.run(["bash", "-n", "-c", cmd], check=True)
            old = before.command_scope_reach(cmd, scopes, str(ws), str(ws))
            new = after.command_scope_reach(cmd, scopes, str(ws), str(ws))
            assert old[0] is False
            if head in ("cd", "'cd'"):
                assert new[0] is False
                assert after._literal_for_iterations(cmd) is None
                print(f"PASS: direct spelling {head!r} is excluded")
            else:
                assert new[0] is True
                assert after._literal_for_iterations(cmd) is not None
                print(f"REPRODUCED false allow: {head!r}")
            # Execute only directory changes and pwd, never the sample file read.
            oracle = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c",
                 "for f in a a a; do pwd -P; " + head + " sub || :; done"],
                cwd=ws, check=True, capture_output=True, text=True)
            assert oracle.stdout.splitlines()[2] == str(outside)

        granted, reached = outside / "granted-", outside / "granted-done"
        granted.write_text("granted\n")
        reached.write_text("ungranted\n")
        cmd = f"for f in a; do :; done; cat {reached}"
        subprocess.run(["bash", "-n", "-c", cmd], check=True)
        assert after._literal_for_iterations(cmd) is None
        verdict = after.command_scope_reach(cmd, scopes + [f"path:{granted}"], str(ws), str(ws))
        assert verdict[0] is False and verdict[2] == str(reached)
        print("PASS: earlier closing-done filename case is refused")

        cmd = "for f in a.txt b.txt; do cat $f; done"
        assert after.command_scope_reach(cmd, scopes, str(ws), str(ws))[0] is True
        cmd = 'S=abc; curl -s http://example.invalid -H "id: $S"'
        assert before.command_scope_reach(cmd, scopes, str(ws), str(outside))[0] is False
        assert after.command_scope_reach(cmd, scopes, str(ws), str(outside))[0] is True
        print("PASS: plain literal loop and header fix retain their intended allows")
    print("PASS: four false allows reproduced; controls passed; fixtures cleaned up")


if __name__ == "__main__":
    main()
