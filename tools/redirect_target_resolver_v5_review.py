"""Reproduce PR #1082 v5 review failures without executing any file writes.

Run with python3 tools/redirect_target_resolver_v5_review.py. Historical review
probe, not a production fix or a claim that passing its examples proves safety.
Both Python implementations are loaded from immutable git objects. For Bash,
replace only the final write with a printf of its destination variable; all
binding/control-flow syntax remains intact. No proposed command is executed by
the classifier, and the Bash oracle never opens a destination.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
BASE = "40903d6"
CANDIDATE = "fb91fb78fcf1e98fac2d9560ff819f38f0b728b6"
MARK = "plugins/_shared/hestia_governance_closure.py"
WRITE = 'echo ' + MARK + ' > "$OUT"'
ORACLE = "builtin printf '__DEST__%s\\n' \"$OUT\""


def load(name, revision, path):
    source = subprocess.check_output(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, text=True)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, f"{revision}:{path}", "exec"), module.__dict__)
    return module


# name, prefix before final write, actual Bash destination, is unsafe
CASES = [
    ("newline after &&", 'false &&\nOUT=/tmp/review-safe; ', MARK, True),
    ("newline after ||", 'true ||\nOUT=/tmp/review-safe; ', MARK, True),
    ("newline after pipeline", 'echo ignored |\nOUT=/tmp/review-safe; ', MARK, True),
    ("background complete AND list", 'OUT=/tmp/review-safe && true & ', MARK, True),
    ("closer word as argument", 'if false; then echo fi; OUT=/tmp/review-safe; fi; ', MARK, True),
    ("array element rebinding", 'OUT=/tmp/review-safe; OUT[0]=' + MARK + '; ', MARK, True),
    ("append rebinding", 'OUT=plugins/; OUT+=_shared/hestia_governance_closure.py; ', MARK, True),
    ("quoted assignment is command", "'OUT=/tmp/review-safe'; ", MARK, True),
    ("comment after &&", 'false && # continuation\nOUT=/tmp/review-safe; ', MARK, True),
    ("for header as echo arguments", 'echo for OUT in /tmp/review-safe; ', MARK, True),
    ("control: plain assignment", 'OUT=/tmp/review-safe; ', '/tmp/review-safe', False),
    ("control: assignment before pipeline", 'OUT=/tmp/review-safe && echo ignored | cat; ', '/tmp/review-safe', False),
    ("control: governed assignment", 'OUT=' + MARK + '; ', MARK, False),
]


def main():
    sys.dont_write_bytecode = True
    g = load("review_governance", BASE, MARK)
    r = load("review_candidate", CANDIDATE, "tools/redirect_target_resolver.py")
    shipped = g._bash_write_targets
    candidate, _ = r.make(g)
    env = {"PATH": os.defpath, "LC_ALL": "C", "OUT": MARK}
    holes = 0
    for name, prefix, destination, unsafe in CASES:
        command = prefix + WRITE
        g._bash_write_targets = shipped
        before = g.classify("Bash", {"command": command}, cwd=str(ROOT))
        g._bash_write_targets = candidate
        after = g.classify("Bash", {"command": command}, cwd=str(ROOT))
        runtime = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", prefix + ORACLE],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=5,
            check=True)
        actual = [line.removeprefix("__DEST__") for line in runtime.stdout.splitlines()
                  if line.startswith("__DEST__")]
        assert actual == [destination], (name, actual, runtime.stderr)
        if unsafe:
            assert before.classification == "write", (name, before)
            assert after.classification == "read", (name, after)
            holes += 1
        else:
            expected = "write" if destination == MARK else "read"
            assert after.classification == expected, (name, after)
        print(json.dumps({"case": name, "command": command,
                          "before": before.classification,
                          "v5": after.classification,
                          "bash_destination": actual[0], "unsafe": unsafe}))
    print(f"CONFIRMED: {holes} unsafe write-to-read changes; 3 controls matched")


if __name__ == "__main__":
    main()
