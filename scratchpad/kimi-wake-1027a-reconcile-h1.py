#!/usr/bin/env python3
"""Follow-up: reconcile H1. Reconstruct the held patch's post-image from
HEAD-bytes + patch hunks (all in memory; git objects read via `git show`),
and compare three hashes against the manifest's c05eefac...:
  post-image (HEAD + patch), current worktree bytes, and HEAD bytes.
Also reconstruct the post-image _shared manifest and compare with the tree's.
Distinguishes 'held patch not self-consistent' from 'tree moved after apply'.
"""
import hashlib, json, os, re, subprocess

REPO = "/home/dp/ai-workspace/hestia"
W = os.path.join(REPO, "scratchpad/s1411w")
PATCH = os.path.join(W, "held/e1b2dba5c17d7f9b8dde378734f9c39629c6bdab164abf952711a1485477d357.patch")
EXPECTED = "c05eefac928759cb0f3a3d41d63754ab2480fd35d7fae52747b6232a23b44f3d"


def parse_patch(text):
    files, cur = {}, None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            cur = None
        elif line.startswith("+++ b/"):
            cur = line[len("+++ b/"):]
            files[cur] = []
        elif line.startswith("@@ ") and cur is not None:
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
            files[cur].append([int(m.group(1)), []])
        elif cur is not None and files[cur] and line[:1] in (" ", "+", "-"):
            files[cur][-1][1].append(line)
    return files


def apply_file(src, hunks, path):
    lines = src.split("\n")
    out, pos = [], 0
    for old_start, hlines in hunks:
        idx = old_start - 1
        out.extend(lines[pos:idx])
        pos = idx
        for hl in hlines:
            tag, body = hl[0], hl[1:]
            if tag == " ":
                assert lines[pos] == body, f"{path}: context mismatch at line {pos+1}"
                out.append(lines[pos]); pos += 1
            elif tag == "-":
                assert lines[pos] == body, f"{path}: delete mismatch at line {pos+1}"
                pos += 1
            else:
                out.append(body)
    out.extend(lines[pos:])
    return "\n".join(out)


patch_text = open(PATCH, encoding="utf-8").read()
hunks_by_file = parse_patch(patch_text)

CORE = "plugins/_shared/hestia_gate_core.py"
head_core = subprocess.run(
    ["git", "-C", W, "show", f"HEAD:{CORE}"],
    capture_output=True, text=True, check=True).stdout
post_core = apply_file(head_core, hunks_by_file[CORE], CORE)
tree_core = open(os.path.join(W, CORE), encoding="utf-8").read()

out = {
    "sha_head": hashlib.sha256(head_core.encode()).hexdigest(),
    "sha_postimage": hashlib.sha256(post_core.encode()).hexdigest(),
    "sha_worktree": hashlib.sha256(tree_core.encode()).hexdigest(),
    "expected": EXPECTED,
    "postimage_matches_manifest": hashlib.sha256(post_core.encode()).hexdigest() == EXPECTED,
    "worktree_matches_manifest": hashlib.sha256(tree_core.encode()).hexdigest() == EXPECTED,
    "worktree_equals_postimage": tree_core == post_core,
}

if tree_core != post_core:
    # locate first differing line
    a, b = post_core.split("\n"), tree_core.split("\n")
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out["first_diff_line"] = i + 1
            out["postimage_line"] = x[:160]
            out["worktree_line"] = y[:160]
            break
    out["len_delta_lines"] = len(b) - len(a)

print(json.dumps(out, indent=1))
