#!/usr/bin/env python3
"""While two copies of the shell classifier exist, they must answer identically.

This test is scaffolding with a scheduled death. `plugins/_shared/hestia_shell_classifier.py`
was lifted verbatim out of `plugins/claude-code/hooks/pre_tool_use.py`; the seat's copy is
deleted in the follow-on PR, once the shared module has propagated to `$HESTIA_HOME/shared`
(the seat imports from the INSTALLED path, so deleting local law in the same release would
leave installed hosts with neither until the next 4-hourly deploy).

Between those two merges the fleet carries a duplicate, which is the exact condition the
one-gate ruling exists to end. A duplicate nobody compares is how the seats diverged in the
first place, so for as long as it exists it is pinned here.

When the seat's copy is gone this test SKIPS, and it should then be deleted with it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEAT = ROOT / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"
SHARED = ROOT / "plugins" / "_shared" / "hestia_shell_classifier.py"

# Shapes chosen to exercise every helper that moved: heredoc bodies, sed programs, shell
# assignments, control-flow remainders, git stdin-as-data, live substitution, redirects.
CASES = [
    "grep -n pattern file.py",
    "wc -l file",
    "head -5 file",
    "ls | grep test",
    "git log --oneline | head",
    "git show HEAD:file | head",
    'sed -n "1,5p" file',
    "sed -i s/a/b/ file",
    "cat a.txt >> out.py",
    'for f in *.py; do grep -n x "$f"; done',
    "p=a/b.py; grep -c def \"$p\"",
    "D=d; echo x >> \"$D/f.py\"",
    "x=$(grep -c def file)",
    "git config --get user.name",
    "git config user.name bob",
    "python3 apply.py file.py",
    'echo "x" | tee file',
    "T=/tmp/x; : >\"$T/s\"; grep -n X file",
    "sort -o file file",
    'find . -name "*.tmp"',
    "diff a b",
    "stat file",
]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if not SHARED.exists():
        print("FAIL: the shared classifier is missing", file=sys.stderr)
        return 1
    shared = _load(SHARED, "shared_shell_classifier_under_test")
    seat = _load(SEAT, "seat_gate_under_test")
    if not hasattr(seat, "_is_read_only"):
        print("ok: the seat no longer carries its own classifier -- "
              "this test has done its job and should be deleted with it")
        return 0

    diverged = []
    for cmd in CASES:
        ti = {"command": cmd}
        try:
            a = seat._is_read_only("Bash", ti)
        except Exception as exc:  # noqa: BLE001
            a = f"ERR:{type(exc).__name__}"
        try:
            b = shared._is_read_only("Bash", ti)
        except Exception as exc:  # noqa: BLE001
            b = f"ERR:{type(exc).__name__}"
        if a != b:
            diverged.append((cmd, a, b))

    if diverged:
        for cmd, a, b in diverged:
            print(f"FAIL: seat={a} shared={b} :: {cmd}", file=sys.stderr)
        print(f"FAIL: {len(diverged)} of {len(CASES)} diverged -- the duplicate has drifted",
              file=sys.stderr)
        return 1
    print(f"ok: seat and shared classifier agree on all {len(CASES)} shapes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
