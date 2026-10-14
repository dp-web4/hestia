#!/usr/bin/env python3
"""Check held 04b57d91 without installing a gate.

Run from the shared checkout, not a checkout under /tmp: fixture grants must
remain discriminating. Includes the amended battery and Bash fixture oracles.
"""
import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
import types

BASE = "67b45517"
HEAD = "386c6094"
PATCH = "04b57d9195c74ae52b35275ff789d9f4d8504c2a7e0ab9ea862e628d1791a556"
CORE = "plugins/_shared/hestia_gate_core.py"


def git_show(ref):
    return subprocess.check_output(["git", "show", ref], text=True)


def patched_source(source, patch, path):
    section = patch.split(f"diff --git a/{path} b/{path}\n", 1)[1].split("diff --git ", 1)[0]
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
    return "".join(result)


def load_pair():
    source = git_show(f"{BASE}:{CORE}")
    patch = git_show(f"{HEAD}:held/{PATCH}.patch")
    assert hashlib.sha256(patch.encode()).hexdigest() == PATCH
    modules = []
    for name, text in (("review_before", source), ("review_after", patched_source(source, patch, CORE))):
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
                assert new[0] is False
                assert after._literal_for_iterations(cmd) is None
                print(f"PASS revised refusal: {head!r}")
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
        for directory in (ws, ws / "sub", outside):
            (directory / "cd").write_text("")
            (directory / "move").write_text("cd sub\n")
        glob_heads = ["c[[:alpha:]]", "[[:lower:]]d", "c[[:alnum:]]", "c[^x]", "[[:alpha:]][[:alpha:]]"]
        source_heads = ["! . ./move", "if . ./move; then :; fi", "time . ./move",
                        ">/dev/null . ./move", "if true; then . ./move; fi",
                        "if false; then :; else . ./move; fi", "time -p . ./move"]
        for body in [g + " sub" for g in glob_heads] + source_heads:
            cmd = "for f in secret.txt secret.txt secret.txt; do cat $f; " + body + "; done"
            assert after._literal_for_iterations(cmd) is None, body
            assert after.command_scope_reach(cmd, scopes, str(ws), str(ws))[0] is False, body
            oracle = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c",
                 "for f in a a a; do pwd -P; " + body + "; done"],
                cwd=ws, capture_output=True, text=True)
            assert oracle.stdout.splitlines()[2] == str(outside), (body, oracle)
        print("PASS: 5 bracket forms and 7 source positions excluded; Bash confirms persistent cwd")
    print("PASS: four former false allows refused; controls passed; fixtures cleaned up")
    patch = git_show(f"{HEAD}:held/{PATCH}.patch")
    path = "tools/shell_scope_reach_battery_test.py"
    battery = patched_source(git_show(f"{BASE}:{path}"), patch, path)
    loader = ('_spec = importlib.util.spec_from_file_location("hestia_gate_core", CORE_PATH)\n'
              'G = importlib.util.module_from_spec(_spec)\n'
              'sys.modules["hestia_gate_core"] = G\n'
              '_spec.loader.exec_module(G)')
    assert battery.count(loader) == 1
    battery = battery.replace(loader, '# G supplied by the in-memory review harness')
    fixture_root = 'os.path.expanduser("~/.cache/hestia-shell-scope-battery")'
    assert battery.count(fixture_root) == 1
    # Preserve non-/tmp discrimination without requiring writes outside the checkout.
    with tempfile.TemporaryDirectory(prefix="review-1312-battery-", dir=".") as root:
        battery = battery.replace(fixture_root, repr(str(pathlib.Path(root).resolve())))
        scope = {"__name__": "review_battery", "__file__": str(pathlib.Path(path).resolve()), "G": after}
        exec(compile(battery, path, "exec"), scope)
        scope["CORE_PATH"] = "in-memory held " + PATCH[:8]
        assert scope["main"]() == 0


if __name__ == "__main__":
    main()
