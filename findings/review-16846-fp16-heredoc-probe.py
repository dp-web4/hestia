#!/usr/bin/env python3
"""Review FP16 v3 without installing it. Usage: python3 THIS_FILE PATCH_FILE.

Applies the two source diffs in memory, runs their tests, and checks a quoted
case pattern against a real shell using only a disposable neutral marker.
"""
import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "23ea932439e322c4078e2737a4093a6d2461072e"
DIGEST = "0a22e5f7653dbfc01cd0ceb4fa8a952052a51367fcc637dc070d44aa5cbf895d"
SOURCE = "plugins/_shared/hestia_governance_closure.py"
TEST = "plugins/_shared/hestia_governance_closure_test.py"


def base_source(name):
    return subprocess.check_output(
        ["git", "show", f"{BASE}:{name}"], cwd=ROOT, text=True)


def patched_sources(patch):
    result = {}
    for section in patch.split("diff --git ")[1:]:
        lines = section.splitlines(keepends=True)
        name = lines[0].split()[0][2:]
        if name not in (SOURCE, TEST):
            continue
        original = base_source(name).splitlines(keepends=True)
        out, pos, i = [], 0, 3
        while i < len(lines):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[i])
            assert match, (name, lines[i])
            start = int(match[1]) - 1
            out.extend(original[pos:start])
            pos, i = start, i + 1
            while i < len(lines) and not lines[i].startswith("@@"):
                line = lines[i]
                if line.startswith((" ", "-")):
                    assert original[pos] == line[1:], (name, pos)
                    pos += 1
                if line.startswith((" ", "+")):
                    out.append(line[1:])
                i += 1
        out.extend(original[pos:])
        result[name] = "".join(out)
    return result


def load(name, source, path):
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def main():
    patch = pathlib.Path(sys.argv[1]).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == DIGEST
    sources = patched_sources(patch.decode())
    sys.path.insert(0, str(ROOT / "plugins/_shared"))
    baseline = load("fp16_baseline", base_source(SOURCE), SOURCE)
    candidate = load("hestia_governance_closure", sources[SOURCE], SOURCE)
    suite = load("fp16_review_tests", sources[TEST], TEST)
    tests = [getattr(suite, name) for name in sorted(vars(suite))
             if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Candidate regression tests: {len(tests)} passed")

    with tempfile.TemporaryDirectory(prefix="fp16-review-") as directory:
        marker = pathlib.Path(directory) / "neutral-marker"
        command = "case x in '<<EOF') :;;\nesac\nprintf x > " + str(marker) + "\n"
        assert candidate._case_header_rule_applies(command)
        assert candidate._bash_write_targets(command) == []
        try:
            baseline._bash_write_targets(command)
        except baseline._OutOfGrammar:
            print("Baseline: out of grammar; candidate: zero write targets")
        else:
            raise AssertionError("Baseline unexpectedly accepted the command")
        subprocess.run(["bash", "-n", "-c", command], check=True)
        subprocess.run(["bash", "--noprofile", "--norc", "-c", command], check=True)
        assert marker.read_text() == "x"
        print("Bash: syntax valid; neutral marker created")

        # Classifier-only check: this command is never passed to a shell.
        governed = str(pathlib.Path(directory) / "plugins/_shared/review-marker.txt")
        classified = command.replace(str(marker), governed)
        before = baseline.classify("Bash", {"command": classified},
                                   cwd=directory, closure=baseline.LITERAL_FLOOR)
        after = candidate.classify("Bash", {"command": classified},
                                   cwd=directory, closure=candidate.LITERAL_FLOOR)
        print("Governed-path classification:", before.classification, before.rule,
              "->", after.classification, after.rule)
        assert before.classification == "write"
        assert after.classification != "write"


if __name__ == "__main__":
    main()
