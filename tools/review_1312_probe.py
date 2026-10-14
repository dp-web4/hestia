#!/usr/bin/env python3
"""Read held #1312 as data; test it in memory without changing a gate on disk."""
import pathlib
import re
import subprocess
import sys
import tempfile
import types

BASE = "67b45517"
HEAD = "537fd9a012e4fb5042e22331a2cd16a5bb52ecdf"
PATCH = "39bd5bcfd1df5d648e826715738f432cd67b4131854c3963ab66074c2a4601b8"
CORE = "plugins/_shared/hestia_gate_core.py"


def git_show(ref):
    return subprocess.check_output(["git", "show", ref], text=True)


def load_pair():
    source = git_show(f"{BASE}:{CORE}")
    patch = git_show(f"{HEAD}:held/{PATCH}.patch")
    import hashlib
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
    # Under the checkout, not /tmp: the latter is unconditionally granted.
    with tempfile.TemporaryDirectory(prefix="review-1312-", dir=".") as root:
        root = pathlib.Path(root).resolve()
        ws, outside = root / "ws", root / "outside"
        ws.mkdir()
        outside.mkdir()
        granted, reached = outside / "granted-", outside / "granted-done"
        granted.write_text("granted\n")
        reached.write_text("ungranted\n")
        scopes = [f"path:{ws}/**", f"path:{granted}"]
        cmd = f"for f in a; do :; done; cat {reached}"
        # Only syntax-check the sample; do not execute its file access.
        subprocess.run(["bash", "-n", "-c", cmd], check=True)
        old = before.command_scope_reach(cmd, scopes, str(ws), str(ws))
        new = after.command_scope_reach(cmd, scopes, str(ws), str(ws))
        print("suffix rewrite:", after._literal_for_iterations(cmd))
        print("suffix before/after:", old, new)
        assert old[0] is False and old[2] == str(reached)
        assert new[0] is True

        # A directory change persists across iterations in a real shell.
        (ws / "sub").mkdir()
        (ws / "sub" / "sub").symlink_to(outside, target_is_directory=True)
        (ws / "secret.txt").write_text("allowed\n")
        (ws / "sub" / "secret.txt").write_text("allowed\n")
        (outside / "secret.txt").write_text("ungranted\n")
        cmd = "for f in secret.txt secret.txt secret.txt; do cat $f; cd sub; done"
        old = before.command_scope_reach(cmd, scopes, str(ws), str(ws))
        new = after.command_scope_reach(cmd, scopes, str(ws), str(ws))
        print("cwd before/after:", old, new)
        assert old[0] is False
        assert new[0] is True
        # Safe independent shell oracle: print cwd only, using the same cd pattern.
        oracle = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c",
             "for f in secret.txt secret.txt secret.txt; do pwd -P; cd sub || :; done"],
            cwd=ws, check=True, capture_output=True, text=True)
        assert oracle.stdout.splitlines()[2] == str(outside)
        print("cwd oracle: third iteration reaches the ungranted fixture directory")

        cmd = "for f in a.txt b.txt; do cat $f; done"
        assert after.command_scope_reach(cmd, scopes, str(ws), str(ws))[0] is True
        cmd = 'S=abc; curl -s http://example.invalid -H "id: $S"'
        assert before.command_scope_reach(cmd, scopes, str(ws), str(outside))[0] is False
        assert after.command_scope_reach(cmd, scopes, str(ws), str(outside))[0] is True
        print("PASS: two false-allows reproduced; two intended allows retained")


if __name__ == "__main__":
    main()
