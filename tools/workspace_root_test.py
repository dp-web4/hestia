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

WHAT AGREEMENT CANNOT TELL YOU
    Agreement is not correctness. Twelve sites agreeing on a root that does not
    exist pass an agreement check while every gate they name is ENOENT -- the
    original defect, uniformly applied. And during a legitimate migration the
    correctly-moved sites are the minority, so ranking by headcount names them
    the outlier and instructs you to revert the only ones that work.

    So the roots are also ANCHORED: does `<root>/hestia` hold a checkout on THIS
    host? That question is put to the filesystem, not the index -- deliberately,
    and it is the only one here that is. Every other check makes a claim about
    the repo, which the index answers exactly. This one makes a claim about the
    host the paths were baked for, and only the host can answer it.

    An anchored root outranks a majority one. An agreement that anchors nowhere
    is reported UNCONFIRMED, never PASS: the check cannot separate "baked for a
    host that is not this one" from "wrong everywhere", and PASS would be
    choosing the flattering reading. Both exit 0 -- a gauge that fails on every
    host but one gets ignored on all of them, and being ignored is the failure
    mode this file exists to prevent. The word is the signal, not the code.

Run:  ./tools/workspace_root_test.py
"""

import json
import os
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


def sites(n):
    return f"{n} site" + ("" if n == 1 else "s")


def anchored(root):
    """Does `root` name a workspace holding a hestia checkout on THIS host?

    The only filesystem question in this file, and the only one that can be
    asked of the filesystem: whether a baked root is real is a fact about the
    host, not about the repo. `.git` is `exists`-checked rather than `isdir`
    because in a worktree it is a file.

    A deploy copy of the tree that is not a checkout does not anchor. That is
    conservative on purpose -- an unanchored root is reported, not failed, so
    the cost of being strict here is a word, and the cost of being loose is a
    disarmed gate that reads as confirmed.
    """
    return os.path.exists(os.path.join(os.path.expanduser(root), "hestia", ".git"))


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
        # Calibrate on the anchored root when there is exactly one, so that a
        # migration whose new root is still in the minority calibrates on the
        # root that exists rather than on the one being migrated away from.
        confirmed = [r for r in roots if anchored(r)]
        calibration = confirmed[0] if len(confirmed) == 1 else max(
            roots, key=lambda r: len(roots[r])
        )
        leaf = calibration.rsplit("/", 1)[-1].encode()
        sibling = re.compile(
            rb"(?<![\w/.~:-])((?:/|~/)[\w./+-]*?/" + re.escape(leaf) + rb")(?![\w/-])"
        )
        for path, content in surfaces:
            for match in sibling.finditer(content):
                root = match.group(1).decode()
                if root != calibration:
                    roots.setdefault(root, []).append((path, root))

    if not roots:
        print(f"PASS  no checkout roots baked into {len(surfaces)} invocation surfaces")
        return 0

    # Re-anchor: the sibling pass can have introduced roots the first one missed.
    confirmed = [r for r in roots if anchored(r)]

    if len(roots) > 1:
        if len(confirmed) == 1:
            # The anchor beats the headcount. This is the migration case: the
            # moved sites are still the minority, and they are the right ones.
            keep = confirmed[0]
            basis = (f"    anchored ({sites(len(roots[keep]))}):  {keep}\n"
                     f"        a hestia checkout is really there on this host")
        else:
            keep = max(roots, key=lambda r: len(roots[r]))
            note = ("no root anchors to a checkout on this host"
                    if not confirmed else
                    f"{len(confirmed)} roots anchor here, so the anchor cannot pick")
            basis = (f"    majority ({sites(len(roots[keep]))}):  {keep}\n"
                     f"        ranked by headcount only -- {note}")
        odd = sorted(((r, s) for r, s in roots.items() if r != keep),
                     key=lambda kv: -len(kv[1]))
        print(f"FAIL  {len(roots)} disagreeing checkout roots across "
              f"{len(surfaces)} invocation surfaces.\n")
        print(basis)
        for root, rs in odd:
            print(f"\n    outlier  ({sites(len(rs))}):  {root}")
            for path, full in rs:
                print(f"        {path}\n            {full}")
        print("\nA spawn from the outlier root is ENOENT, and an ENOENT hook is "
              "fail-open:\nit does not deny, it does not witness, and it does not "
              f"complain. Repoint it\nto {keep}"
              + ("." if len(confirmed) == 1 else
                 ", or if the outlier is correct, repoint the rest."))
        return 1

    root, only = next(iter(roots.items()))
    if confirmed:
        print(f"PASS  all {len(only)} baked checkout references across "
              f"{len(surfaces)} invocation surfaces agree on {root},\n"
              f"      and a hestia checkout is really there on this host")
        return 0

    here = os.path.dirname(subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip().removesuffix("/.git")) or "(not determinable)"
    print(f"UNCONFIRMED  all {len(only)} baked checkout references across "
          f"{len(surfaces)} invocation surfaces\n"
          f"             agree on {root} -- and nothing is there.\n")
    print(f"    no hestia checkout at {root}/hestia on this host\n"
          f"    this checkout's workspace is {here}\n")
    print("Agreement is not correctness: these sites could be baked for a host "
          "that is not\nthis one, or they could be wrong everywhere. If this is "
          "the host they were baked\nfor, every one of them is ENOENT, and an "
          "ENOENT hook is fail-open -- it does not\ndeny, it does not witness, "
          "and it does not complain. Exit 0 because this check\ncannot tell "
          "those two apart; it will not say PASS for the same reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
