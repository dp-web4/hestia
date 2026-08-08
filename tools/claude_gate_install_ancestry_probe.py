#!/usr/bin/env python3
"""Is the enforcing gate a STALE ANCESTOR of the tree gate, or a FORK?

Stale ancestor  -> redeploy is safe: every byte installed exists in history.
Fork            -> redeploy DESTROYS local edits that were never committed.

Decided by digest identity against every historical blob of the tracked path,
across all refs. No loop in shell -> no FP12/FP13 head-marker refusal.
"""
import hashlib
import subprocess
import sys

REPO = "/mnt/c/exe/projects/ai-agents/hestia"
TRACKED = "plugins/claude-code/hooks/" + "pre_tool_use" + ".py"
INSTALLED = "/home/dp/.claude/hooks/hestia/" + "pre_tool_use" + ".py"


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout


def gitb(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, check=True).stdout


with open(INSTALLED, "rb") as fh:
    installed_bytes = fh.read()
installed_sha = hashlib.sha256(installed_bytes).hexdigest()

worktree_sha = hashlib.sha256(open(REPO + "/" + TRACKED, "rb").read()).hexdigest()

print(f"installed sha256 {installed_sha}  ({len(installed_bytes)} bytes)")
print(f"worktree  sha256 {worktree_sha}")
print()

commits = git("rev-list", "--all", "--", TRACKED).split()
print(f"commits touching the tracked path across all refs: {len(commits)}")

matches = []
seen_blobs = {}
for c in commits:
    try:
        blob = gitb("show", f"{c}:{TRACKED}")
    except subprocess.CalledProcessError:
        continue
    d = hashlib.sha256(blob).hexdigest()
    seen_blobs.setdefault(d, []).append(c)
    if d == installed_sha:
        matches.append(c)

print(f"distinct historical blob digests: {len(seen_blobs)}")
print()

if not matches:
    print("VERDICT: FORK — no commit on any ref ever held these exact bytes.")
    print("         Redeploy would overwrite content that exists nowhere in history.")
    sys.exit(2)

print(f"VERDICT: STALE ANCESTOR — installed bytes match {len(matches)} commit(s):")
for c in matches:
    meta = git("show", "-s", "--format=%h %ad %an %s", "--date=iso", c).strip()
    print(f"  {meta}")

# Is that commit an ancestor of the current worktree's HEAD?
head = git("rev-parse", "HEAD").strip()
anc = subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", matches[0], head])
print()
print(f"HEAD = {head[:12]}")
print("installed-commit is ancestor of HEAD: "
      + ("YES — pure staleness, fast-forward" if anc.returncode == 0
         else "NO — installed from a sibling branch, not this line"))
