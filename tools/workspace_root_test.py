#!/usr/bin/env python3
"""A baked path that does not exist does not fail loudly -- it disarms silently.

Hook manifests in this repo hard-code absolute paths to the scripts a runtime
must execute. `plugins/gemini/hooks/hooks.json` explains why, in its own
`_paths_note`:

    a sample with placeholder paths would be WORSE: a spawn error is a
    fail-open, so a path that does not exist silently DISARMS the gate
    rather than failing loudly.

That reasoning is correct. The file it is written in then baked a workspace root
one path segment short of the fleet's -- a directory that exists on this host and
is empty -- for every one of its four commands. ENOENT apiece, in a manifest
whose stated justification for baking paths at all is that a wrong one cannot be
noticed. (This docstring names no literal path on purpose: prose is stripped from
JSON manifests via `_`-keys, but a .py is scanned whole, and a gauge that flags
its own explanation is a gauge you delete.)

Nothing could catch that by reading, because each file is internally coherent.
It is only visible across files, which is what this checks.

THE INVARIANT
    Every absolute path baked into an invocation surface that refers to a
    hestia CHECKOUT must agree with every other one on where that checkout is.

"Invocation surface" is structural, not a filename list: a file the git index
marks 100755, or a .json declaring a "command". That is the set of files a
runtime spawns something from. Recorded data (.hardbound bundles carry Legion's
absolute paths by design) and prose are excluded because nothing spawns them.

"Refers to a checkout" is also structural: the segment after `/hestia/` must
name a path tracked in THIS repo. That is what separates a checkout root from an
install destination -- codex's gate points at a deployed copy under the user's
home whose tail is not a tracked path, so it is not claiming to point at a
checkout and is not held to the checkout's root. Same for a raw.githubusercontent
URL. The rule calibrates itself against the repo rather than a denylist.

Run:  ./tools/workspace_root_test.py
"""

import json
import re
import subprocess
import sys

# A leading `/` or `~/`, then anything up to a literal `/hestia/`, then a tail.
# The lookbehind rejects `//raw.githubusercontent.com/...` and any scheme-bearing
# URL: a checkout root is never preceded by `:` or another `/`.
BAKED = re.compile(
    rb"(?<![\w/.~:-])((?:/|~/)[\w./+-]*?)/hestia/([\w./+-]+)"
)

# A .json that declares what to execute. Structural: the file's own content says
# "a runtime spawns this", which is exactly the class that can be disarmed.
DECLARES_COMMAND = re.compile(rb'"command"\s*:')


def tracked(repo):
    out = subprocess.run(
        ["git", "ls-files", "-s", "-z"], cwd=repo, capture_output=True, check=True
    ).stdout
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        yield meta.partition(b" ")[0].decode(), path.decode()


def blob(repo, path):
    out = subprocess.run(["git", "show", f":{path}"], cwd=repo, capture_output=True)
    return out.stdout if out.returncode == 0 else b""


def spawnable(content):
    """Strip the prose regions of a manifest -- nothing spawns a comment.

    This repo's JSON manifests carry their documentation in `_`-prefixed keys
    (`_comment`, `_paths_note`, `_hooksConfig_note`), which no runtime reads.
    Without this, a note that correctly WARNS about a wrong path is scored as
    baking one, and the only way to pass the check is to stop documenting the
    defect -- a gauge that punishes its own explanation.

    Non-JSON and unparseable JSON are returned whole: a `#` comment can hold a
    path that a later edit turns into code, and in a shell script the comment is
    usually usage text for a default that must stay in sync with it anyway.
    """
    try:
        doc = json.loads(content)
    except Exception:
        return content

    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if not key.startswith("_"):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            out.append(node.encode())

    walk(doc)
    return b"\n".join(out)


def main():
    repo = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Read modes and contents from the INDEX, never the worktree. On the fleet's
    # NTFS mount every file reports 0777, so the filesystem cannot tell us which
    # files are executable -- only git can. (See shebang_exec_bit_test.py.)
    modes = dict((p, m) for m, p in tracked(repo))
    paths = set(modes)

    def is_tracked_path(tail):
        """True if `tail` names a tracked file or a directory containing one."""
        return tail in paths or any(p.startswith(tail.rstrip("/") + "/") for p in paths)

    roots = {}       # root -> [(file, full path), ...]
    unclassified = []  # /hestia/ references whose tail is not in this repo

    # Narrow to candidates BEFORE reading any blob. `git grep --cached` finds the
    # command-declaring .json files in one pass; ~1500 .hardbound bundles are
    # .json too, and a `git show` apiece against the NTFS mount costs a minute.
    grep = subprocess.run(
        ["git", "grep", "-l", "-z", "--cached", "-e", '"command"', "--", "*.json"],
        cwd=repo, capture_output=True,
    )
    manifests = {p.decode() for p in grep.stdout.split(b"\0") if p}

    surfaces = []
    for path, mode in sorted(modes.items()):
        if not (mode == "100755" or path in manifests):
            continue
        content = blob(repo, path)
        if content:
            surfaces.append((path, spawnable(content)))

    for path, content in surfaces:
        for match in BAKED.finditer(content):
            root, tail = match.group(1).decode(), match.group(2).decode()
            full = f"{root}/hestia/{tail}"
            if is_tracked_path(tail):
                roots.setdefault(root, []).append((path, full))
            else:
                unclassified.append((path, full))

    if unclassified:
        # Informational, not a failure: a deploy destination legitimately lives
        # outside the checkout. But a TYPO in a tail lands here too, and would
        # otherwise vanish from the check entirely -- so it is always printed.
        print(f"note  {len(unclassified)} /hestia/ reference(s) not treated as "
              f"checkout roots (tail is not a tracked path):")
        for path, full in unclassified:
            print(f"          {path}: {full}")
        print()

    # Second pass: a bare workspace root with no /hestia/ tail. `install.sh`
    # defaults WORKSPACE to one, and the first pass cannot see it -- there is no
    # tracked tail to calibrate against. Calibrate against the majority root's
    # own basename instead (derived, not hard-coded): any OTHER absolute path
    # ending in that same basename inside an invocation surface is a sibling
    # claiming to be the same workspace from a different place.
    if roots:
        majority = max(roots, key=lambda r: len(roots[r]))
        leaf = majority.rsplit("/", 1)[-1].encode()
        sibling = re.compile(
            rb"(?<![\w/.~:-])((?:/|~/)[\w./+-]*?/" + re.escape(leaf) + rb")(?![\w/-])"
        )
        for path, content in surfaces:
            for match in sibling.finditer(content):
                root = match.group(1).decode()
                if root != majority:
                    roots.setdefault(root, []).append((path, root))

    if len(roots) > 1:
        ranked = sorted(roots.items(), key=lambda kv: -len(kv[1]))
        majority = ranked[0][0]
        odd = ranked[1:]
        print(f"FAIL  {len(roots)} disagreeing checkout roots across "
              f"{len(surfaces)} invocation surfaces.\n")
        print(f"    majority ({len(ranked[0][1])} sites):  {majority}")
        for root, sites in odd:
            print(f"\n    outlier  ({len(sites)} sites):  {root}")
            for path, full in sites:
                print(f"        {path}\n            {full}")
        print("\nA spawn from the outlier root is ENOENT, and an ENOENT hook is "
              "fail-open:\nit does not deny, it does not witness, and it does not "
              "complain. Repoint it\nto the majority root, or if the outlier is "
              "correct, repoint the majority.")
        return 1

    if not roots:
        print(f"PASS  no checkout roots baked into {len(surfaces)} invocation surfaces")
        return 0

    root, sites = next(iter(roots.items()))
    print(f"PASS  all {len(sites)} baked checkout references across "
          f"{len(surfaces)} invocation surfaces agree on {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
