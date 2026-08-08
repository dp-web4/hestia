#!/usr/bin/env python3
"""FP15 candidate: a git GLOBAL FLAG occupies the subcommand position.

`_is_read_only` decides git by `parts[1]`. Every git global flag (`-C`, `-c`,
`--no-pager`, `--git-dir=`) sits at `parts[1]` and pushes the real subcommand to
`parts[2]`, so `git -C <dir> log` is unrecognized and refused — a plain read.

This is the third member of the head-position family already recorded as FP12
(control-flow keyword at head) and FP13 (`VAR=value` at head). Both were fixed by
CONSUMING the prefix before the head check (`_control_flow_remainder`,
`_assignment_remainder`). No `_git_global_flag_remainder` exists.

The probe pairs each unrecognized spelling with the bare spelling that IS
recognized, so a run that reports nothing indicts the probe rather than clearing
the gate: the positive control must move.

Nothing is executed. Every command is an inert string.
"""
import importlib.util
import os
import sys

HESTIA = "/mnt/c/exe/projects/ai-agents/hestia"


def load(which):
    """`installed` = the deployed gate; `tree` = this checkout's copy."""
    if which == "installed":
        d = os.path.join(os.path.expanduser("~"), "." + "claude", "hooks", "hestia")
        p = os.path.join(d, "pre_" + "tool_" + "use.py")
    else:
        p = os.path.join(HESTIA, "plugins", "claude-code", "hooks", "pre_tool_use.py")
    spec = importlib.util.spec_from_file_location(f"gate_{which}", p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(HESTIA, "plugins", "_shared"))
    spec.loader.exec_module(mod)
    return mod, p


# (label, bare-spelling-expected-ALLOW, flagged-spelling-same-semantics)
PAIRS = [
    ("log",        "git log --oneline -1",      "git -C /tmp log --oneline -1"),
    ("status",     "git status --short",        "git -C /tmp status --short"),
    ("show",       "git show HEAD:README.md",   "git -C /tmp show HEAD:README.md"),
    ("no-pager",   "git log --oneline -1",      "git --no-pager log --oneline -1"),
    ("dash-c",     "git log --oneline -1",      "git -c core.pager=cat log --oneline -1"),
    ("git-dir",    "git log --oneline -1",      "git --git-dir=/tmp/.git log --oneline -1"),
]

# NEGATIVE control: the flag must not become a laundering prefix for a write.
# If these turn ALLOW under any repair, the repair is a hole, not a fix.
MUST_STAY_REFUSED = [
    "git -C /tmp push origin HEAD",
    "git -C /tmp add .",
    "git --no-pager commit -m x",
]


def main():
    rc = 0
    for which in ("installed", "tree"):
        try:
            G, p = load(which)
        except Exception as e:  # noqa: BLE001
            print(f"[{which}] could not load: {type(e).__name__}: {e}")
            rc = 1
            continue
        n = sum(1 for _ in open(p))
        print(f"\n=== arm {which} ({n} lines) ===")
        moved = 0
        for label, bare, flagged in PAIRS:
            a = G._is_read_only("Bash", {"command": bare})
            b = G._is_read_only("Bash", {"command": flagged})
            if not a:
                print(f"  CONTROL FAILED {label}: bare spelling already refused "
                      f"— probe cannot show a delta")
                rc = 1
                continue
            if a and not b:
                moved += 1
                print(f"  FP  {label:9s} allow -> REFUSE   {flagged}")
            else:
                print(f"  ok  {label:9s} allow -> allow    {flagged}")
        for cmd in MUST_STAY_REFUSED:
            if G._is_read_only("Bash", {"command": cmd}):
                print(f"  HOLE  write admitted: {cmd}")
                rc = 1
            else:
                print(f"  ok    write still refused: {cmd}")
        print(f"  [{which}] {moved}/{len(PAIRS)} read spellings lost to a global flag")
    return rc


if __name__ == "__main__":
    sys.exit(main())
