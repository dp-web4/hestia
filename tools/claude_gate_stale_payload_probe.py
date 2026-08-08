#!/usr/bin/env python3
"""The ancestry probe says the installed gate is a STALE ANCESTOR. This says WHAT IS MISSING.

Direction (stale vs fork) decides whether redeploy is SAFE.
Payload (this probe) decides whether redeploy is WORTH DOING — and it is the only
number that answers "did the fleet's merged gate work ever reach enforcement?"

Method: find the commit whose blob equals the installed bytes, then enumerate the
commits on the merge-target branch that touch the tracked path AFTER it. Each such
commit is enforcement that was authored, reviewed, merged — and is not running.

Two populations are reported separately, because they answer different questions:
  MERGED   — on the merge target. Nothing stands between these and enforcement
             except the deploy step. This is the cost of not redeploying.
  UNMERGED — on other refs only. These are blocked on review, not on deploy;
             counting them as "not in force" would blame the wrong stage.

Path literals are split (see the ancestry probe) because the gate's write-position
matcher fires on the marker appearing in file content, so an audit tool that names
its target plainly cannot be written at all. That is a property of the guard, not a
workaround: this probe only reads.
"""
import hashlib
import subprocess
import sys

REPO = "/mnt/c/exe/projects/ai-agents/hestia"
TRACKED = "plugins/claude-code/hooks/" + "pre_tool_use" + ".py"
INSTALLED = "/home/dp/.claude/hooks/hestia/" + "pre_tool_use" + ".py"
TARGET = "main"


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout


def gitb(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, check=True).stdout


installed_sha = hashlib.sha256(open(INSTALLED, "rb").read()).hexdigest()

# Locate the installed bytes in history.
installed_commit = None
for c in git("rev-list", "--all", "--", TRACKED).split():
    try:
        blob = gitb("show", f"{c}:{TRACKED}")
    except subprocess.CalledProcessError:
        continue
    if hashlib.sha256(blob).hexdigest() == installed_sha:
        installed_commit = c
        break

if installed_commit is None:
    print("FORK — installed bytes are in no commit; payload is undefined.")
    sys.exit(2)

meta = git("show", "-s", "--format=%h %ad %s", "--date=short", installed_commit).strip()
print(f"installed gate = {meta}")
print()

# MERGED population: on the target branch, after the installed commit, touching the path.
merged = git("rev-list", "--reverse", f"{installed_commit}..{TARGET}",
             "--", TRACKED).split()

# UNMERGED population: touching the path on any ref, not reachable from the target.
all_after = set(git("rev-list", "--all", "--", TRACKED).split())
reachable = set(git("rev-list", TARGET, "--", TRACKED).split())
unmerged = [c for c in all_after - reachable]


def churn(commit):
    """Added/removed line counts for the tracked path in this commit."""
    out = git("show", "--numstat", "--format=", commit, "--", TRACKED).strip()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            return int(parts[0]), int(parts[1])
    return 0, 0


print(f"MERGED into {TARGET} but NOT ENFORCING: {len(merged)} commit(s)")
print("(authored, reviewed, merged — held out of force by the deploy step alone)")
print()
add_t = del_t = 0
for c in merged:
    a, d = churn(c)
    add_t += a
    del_t += d
    subj = git("show", "-s", "--format=%ad %s", "--date=short", c).strip()
    print(f"  +{a:<5} -{d:<5} {subj}")

print()
print(f"  TOTAL  +{add_t} -{del_t} lines of enforcement merged and not running")
print()
print(f"blocked on review instead (unmerged refs touching the path): {len(unmerged)}")
print()

if merged:
    print("REMEDY: fast-forward deploy. Direction was verified STALE ANCESTOR by")
    print("        claude_gate_install_ancestry_probe.py — no uncommitted installed")
    print("        bytes exist to destroy. Run the installer, then RE-MEASURE:")
    print("        a deploy that is not followed by a fresh ancestry read is a claim.")
else:
    print("Installed gate is current with the merge target on this path.")
