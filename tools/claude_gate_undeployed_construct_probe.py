#!/usr/bin/env python3
"""WHICH constructs of the merged-but-undeployed commits are absent from the installed gate?

The payload probe counts lines. A line count cannot say whether the LAW TEXT
over-promises, because a promised carve-out is one named construct among hundreds
of churned lines, and a behavioural probe of that carve-out can pass for the wrong
reason (the marker never reached a checked position at all).

So: extract the identifiers each undeployed commit ADDED to the tracked path, then
ask whether each identifier appears in the installed bytes. An identifier present in
the merge target and absent from the installed file is enforcement the law text may
already be describing to members as if it were running.

Reports the CONVERSE too — identifiers added by those commits that ARE installed —
because a nonzero converse means the installed file is not simply the parent commit,
and a probe that only looks for absences would never notice.
"""
import hashlib
import re
import subprocess
import sys

REPO = "/mnt/c/exe/projects/ai-agents/hestia"
TRACKED = "plugins/claude-code/hooks/" + "pre_tool_use" + ".py"
INSTALLED = "/home/dp/.claude/hooks/hestia/" + "pre_tool_use" + ".py"
TARGET = "main"

DEF = re.compile(r"^\+\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
CONST = re.compile(r"^\+([A-Z_][A-Z0-9_]{4,})\s*[:=]")


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout


def gitb(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, check=True).stdout


installed_text = open(INSTALLED, "r", encoding="utf-8", errors="replace").read()
installed_sha = hashlib.sha256(open(INSTALLED, "rb").read()).hexdigest()

installed_commit = None
for c in git("rev-list", "--all", "--", TRACKED).split():
    try:
        if hashlib.sha256(gitb("show", f"{c}:{TRACKED}")).hexdigest() == installed_sha:
            installed_commit = c
            break
    except subprocess.CalledProcessError:
        continue

if installed_commit is None:
    print("FORK — installed bytes are in no commit.")
    sys.exit(2)

undeployed = git("rev-list", "--reverse", f"{installed_commit}..{TARGET}",
                 "--", TRACKED).split()
if not undeployed:
    print("Nothing merged-but-undeployed on this path.")
    sys.exit(0)

absent_total = present_total = 0
for c in undeployed:
    subj = git("show", "-s", "--format=%h %s", c).strip()
    diff = git("show", "--format=", c, "--", TRACKED)
    names = []
    for line in diff.splitlines():
        m = DEF.match(line) or CONST.match(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))

    absent = [n for n in names if n not in installed_text]
    present = [n for n in names if n in installed_text]
    absent_total += len(absent)
    present_total += len(present)

    print(f"\n{subj[:110]}")
    print(f"  added {len(names)} named construct(s) to the tracked path")
    if absent:
        print(f"  ABSENT from the installed gate ({len(absent)}):")
        for n in absent:
            print(f"    - {n}")
    if present:
        print(f"  already installed ({len(present)}): {', '.join(present[:8])}"
              + (" ..." if len(present) > 8 else ""))

print()
print(f"named constructs merged and NOT enforcing: {absent_total}")
print(f"named constructs merged and already enforcing: {present_total}")
if present_total:
    print("NOTE: a nonzero 'already enforcing' means the installed bytes are not the")
    print("      plain parent — treat per-construct presence, not the commit, as the unit.")
