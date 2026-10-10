#!/usr/bin/env python3
"""Compose the re-stack merge commit with git plumbing in a SCRATCH index (never a working tree).

Tree = `git merge-tree` of 0cac5783 and 716ae2d1 (#1274: c535619d + main), except: the governed subtrees (plugins/,
hooks-gt/) are 716ae2d1's exactly (#1247's governed delta lives only in the held patch), and
held/ gains the new digest-named patch, moves #1247's superseded patches to held/lineage/, and
takes README-1247.md from argv[2]. Parents: 0cac5783, 716ae2d1. Prints the commit sha.
argv: <held patch path> <README-1247.md path> <commit message file>"""
import os
import subprocess
import sys
from pathlib import Path

REPO = "/home/dp/ai-workspace/hestia"
OURS, THEIRS = "0cac578316ff999420324f3f3daa2fa16205c75d", "716ae2d155e2e8625fb5b8e7c208871e659609c9"
patch, readme, msg = (Path(a).resolve() for a in sys.argv[1:4])
idx = Path(__file__).resolve().parent / "restack.index"
ENV = dict(os.environ, GIT_INDEX_FILE=str(idx))


def git(*a, inp=None):
    return subprocess.run(["git", "-C", REPO, *a], check=True, capture_output=True, env=ENV,
                          input=inp).stdout.decode().strip()


mt = subprocess.run(["git", "-C", REPO, "merge-tree", "--write-tree", "--name-only", OURS, THEIRS],
                    capture_output=True, text=True)
merged_tree = mt.stdout.splitlines()[0]
conflicted = [ln for ln in mt.stdout.split("\n\n")[0].splitlines()[1:] if ln]
GOV = ("plugins/", "hooks-gt/")
bad = [c for c in conflicted if not c.startswith(GOV)]
assert not bad, f"non-governed conflicts need hand resolution: {bad}"
if idx.exists():
    idx.unlink()
git("read-tree", merged_tree)
# governed subtrees := 716ae2d1's
gov_now = [f for f in git("ls-files", "-z").split("\0") if f.startswith(GOV)]
git("update-index", "--force-remove", "-z", "--stdin", inp=("\0".join(gov_now) + "\0").encode())
info = git("ls-tree", "-r", "--full-tree", THEIRS, "--", "plugins", "hooks-gt")
git("update-index", "--index-info", inp=(info + "\n").encode())
# held/: superseded #1247 patches move to lineage/, as #1239 did with its own
for old in ("01cf91e4a6d68f30c545133557ffc436b78e0d7731f02fd0a21c35f1f98f5bc8",
            "29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655",
            "e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32",
            "fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6"):
    line = git("ls-files", "-s", f"held/{old}.patch")
    mode, sha = line.split()[0], line.split()[1]
    git("update-index", "--force-remove", f"held/{old}.patch")
    git("update-index", "--add", "--cacheinfo", f"{mode},{sha},held/lineage/{old}.patch")
pb = git("hash-object", "-w", str(patch))
git("update-index", "--add", "--cacheinfo", f"100644,{pb},held/{patch.name}")
rb = git("hash-object", "-w", str(readme))
git("update-index", "--cacheinfo", f"100644,{rb},held/README-1247.md")
HERE = Path(__file__).resolve().parent
for script in ("extract3.py", "resolve.py", "build_held.py", "make_merge.py", "run_one.py",
               "run_all.py", "probe_codex.py", "drift_probe.py", "real_daemon.sh", "fix_readme.py"):
    sb = git("hash-object", "-w", str(HERE / script))
    git("update-index", "--add", "--cacheinfo", f"100644,{sb},docs/reviews/restack-1247-build/{script}")
tree = git("write-tree")
for sub in ("plugins", "hooks-gt"):
    assert git("rev-parse", f"{tree}:{sub}") == git("rev-parse", f"{THEIRS}:{sub}"), sub
commit = git("commit-tree", tree, "-p", OURS, "-p", THEIRS, "-F", str(msg))
print(commit)
