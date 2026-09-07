#!/usr/bin/env python3
"""Report the vintage of what the member mesh is ACTUALLY executing.

A mesh fix is not in force when it is merged. It is in force when the bytes a
watcher execs are the merged bytes. Those are two different questions and this
mesh has no instrument for the second one, so a fix can be authored, reviewed,
merged and green while every seat keeps running the code it replaced.

There are two independent lags, and they fail in opposite ways:

  fire-*.sh          exec'd fresh on every fire, so its vintage is whatever the
                     WORKING TREE holds right now. A shared development tree that
                     is checked out on a feature branch silently un-deploys every
                     mesh fix merged since that branch forked -- for all seats,
                     not just the seat whose branch it is.

  hestia-watch-*.sh  read by a long-running bash process, so its vintage is the
                     tree as of the process START. Editing the file underneath a
                     running watcher does not redeploy it; it is also a byte-offset
                     hazard, because bash reads a script lazily by offset.

So the deployed configuration is (branch the tree sits on) x (when each watcher
was last restarted), and neither coordinate is reported anywhere a member reads.
This prints both, plus the commits stranded between them and origin/main.

Exit status is the count of seats whose executing fire script is not main's, so
it can be used as a check. It resolves nothing by itself -- it only makes the
question askable.

Usage:  mesh_deploy_vintage.py [--repo PATH] [--json]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

MESH_DIR = "plugins/member-mesh"

# Derived from this file's own location (tools/ -> repo root) rather than pinned,
# so the probe answers for whatever checkout it was invoked from. A baked path
# would make it report on one seat's tree no matter which seat ran it -- the same
# class of defect it exists to detect.
DEFAULT_REPO = os.environ.get(
    "HESTIA_REPO", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def git(repo, *args):
    """Run a git command, returning stripped stdout ('' on any failure)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def watchers():
    """Every live watcher, with its start time and the fire script in its argv.

    The fire script is read from argv rather than assumed, because the watcher
    takes it as a parameter -- the path is a deployment fact, not a constant.
    """
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,lstart,args"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in ps.splitlines():
        if "hestia-watch-member.sh" not in line or "grep" in line:
            continue
        m = re.match(r"\s*(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s[\d:]+\s\d{4})\s+(.*)", line)
        if not m:
            continue
        pid, started, argv = m.group(1), m.group(2), m.group(3)
        parts = argv.split()
        watcher = next((p for p in parts if p.endswith("hestia-watch-member.sh")), "")
        fire = next((p for p in parts if "/fire-" in p and p.endswith(".sh")), "")
        seat = parts[parts.index(watcher) + 1] if watcher in parts and len(parts) > parts.index(watcher) + 1 else "?"
        found.append({
            "pid": int(pid), "seat": seat, "started": started,
            "started_epoch": _epoch(started), "watcher": watcher, "fire": fire,
        })
    return found


def _epoch(lstart):
    try:
        return time.mktime(time.strptime(lstart, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


def blob_of_file(repo, path):
    """Hash the file as it sits on disk -- what an exec would actually read."""
    return git(repo, "hash-object", path)


def drift_direction(repo, relpath, wt_blob):
    """stale-ancestor (safe fast-forward) vs fork (needs a merge).

    A worktree blob that appears in main's history FOR THAT PATH is a state main
    has already passed through, so main is simply ahead. A blob main has never
    held is a divergence, and restoring from main would discard work.
    """
    if not wt_blob:
        return "unknown"
    commits = git(repo, "log", "origin/main", "--format=%H", "--", relpath).split()
    for c in commits:
        if git(repo, "rev-parse", f"{c}:{relpath}") == wt_blob:
            return "stale-ancestor"
    return "fork"


# ---------------------------------------------------------------------------
# THE BANNER. `mesh_deploy_vintage.py` has been able to answer "is the mesh
# running main?" since 2026-08-25 and #606 stayed open for 12 more days, because
# an instrument nobody runs reports nothing. The binary layer solved exactly this
# and its solution is not a better instrument: `hestia --version` prints
# `v0.0.4-709-g839fc0e`, so the vintage arrives WITH the thing whose vintage it
# is. This mode is that, for the script layer -- one block the fire path pastes
# into the primer, so the next member to be handed a stale instruction is told
# why in the same breath.
#
# Three rules, and the silence is the important one:
#
#   nothing stranded          -> PRINT NOTHING. A banner on the healthy path is
#                                noise, and noise is what gets filtered out right
#                                before the one time it mattered.
#   HEAD merged into main     -> LOUD. After the merge there is no reason for the
#                                tree to be there, so this has no legitimate arm
#                                and needs no age threshold. #606 originally used
#                                "7 days old", which fires on a member legitimately
#                                mid-feature; "already merged" does not.
#   unmerged feature branch   -> QUIET, factual. Someone is working. Say what is
#                                stranded and let them decide.
#
# NO FETCH. This runs on the fire path, before a wake, holding the member lock.
# It reads the `origin/main` ref as last fetched, so its own answer can be stale
# in the safe direction: it can miss a fix merged since the last fetch, and it
# cannot invent one. `main()` fetches; this deliberately does not.
def primer_banner(repo):
    """Zero or more lines for the wake primer. Empty string = tree is current."""
    head = git(repo, "rev-parse", "--short", "HEAD")
    if not head:
        return ""                      # not a checkout we can read; say nothing
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "(detached)"
    stranded = [l for l in git(
        repo, "log", "HEAD..origin/main", "--format=%h %s", "--", MESH_DIR
    ).splitlines() if l]
    if not stranded:
        return ""
    merged = subprocess.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        capture_output=True, timeout=30,
    ).returncode == 0
    lines = []
    if merged:
        lines.append(
            "!! THE CODE THAT RENDERED THIS PROMPT IS NOT main. The shared tree is on "
            f"`{branch}` ({head}), which is ALREADY MERGED into origin/main "
            f"({git(repo, 'rev-parse', '--short', 'origin/main')}). Every mesh fix merged "
            "since is un-deployed, for every seat. Nothing about this branch is still "
            "needed; moving the tree to main is the whole repair (#606)."
        )
    else:
        lines.append(
            "!! THE CODE THAT RENDERED THIS PROMPT IS NOT main. The shared tree is on "
            f"`{branch}` ({head}) -- unmerged, so someone may be mid-feature. Mesh fixes "
            "merged to main are NOT in force here (#606)."
        )
    lines.append(
        f"   {len(stranded)} commit(s) touching {MESH_DIR} are merged and NOT executing:"
    )
    for l in stranded[:6]:
        lines.append(f"     {l}")
    if len(stranded) > 6:
        lines.append(f"     ... and {len(stranded) - 6} more")
    lines.append(
        "   Treat every instruction above as possibly rendered by superseded code, and "
        "check `git log HEAD..origin/main` before concluding a defect is new. Full "
        "report: tools/mesh_deploy_vintage.py"
    )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--primer-banner", action="store_true",
                    help="print the wake-primer block (empty if the tree is current) "
                         "and exit; makes no network call")
    args = ap.parse_args()
    repo = args.repo

    if args.primer_banner:
        b = primer_banner(repo)
        if b:
            print(b)
        return 0

    git(repo, "fetch", "origin", "main", "-q")
    head = git(repo, "rev-parse", "HEAD")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    main_sha = git(repo, "rev-parse", "origin/main")

    report = {
        "repo": repo, "head": head, "branch": branch, "origin_main": main_sha,
        "tree_is_main": head == main_sha, "seats": [], "stranded": [],
    }

    for w in watchers():
        seat = dict(w)
        fire_abs = w["fire"]
        rel = os.path.relpath(fire_abs, repo) if fire_abs.startswith(repo) else fire_abs
        seat["fire_rel"] = rel
        wt = blob_of_file(repo, fire_abs) if fire_abs else ""
        mn = git(repo, "rev-parse", f"origin/main:{rel}") if rel else ""
        seat["fire_blob_executing"] = wt
        seat["fire_blob_main"] = mn
        # The question is not "does the tree differ from main" but "do the bytes
        # this watcher will exec on its next fire differ from the merged bytes".
        seat["fire_in_force"] = bool(wt) and wt == mn
        seat["fire_drift"] = "none" if seat["fire_in_force"] else drift_direction(repo, rel, wt)

        # The watcher half: vintage is the process start, not the file on disk.
        wrel = os.path.relpath(w["watcher"], repo) if w["watcher"].startswith(repo) else w["watcher"]
        try:
            mtime = os.path.getmtime(w["watcher"])
        except OSError:
            mtime = None
        seat["watcher_rel"] = wrel
        seat["watcher_mtime"] = mtime
        # A file modified after the process began is a vintage NOBODY can name:
        # not the on-disk version, not cleanly the start version either.
        seat["watcher_edited_under_running_process"] = bool(
            mtime and w["started_epoch"] and mtime > w["started_epoch"])
        wwt = blob_of_file(repo, w["watcher"])
        seat["watcher_blob_on_disk"] = wwt
        seat["watcher_blob_main"] = git(repo, "rev-parse", f"origin/main:{wrel}")
        report["seats"].append(seat)

    stranded = git(repo, "log", "--format=%h\t%s", "origin/main", "--not", "HEAD", "--", MESH_DIR)
    report["stranded"] = [
        dict(zip(("sha", "subject"), ln.split("\t", 1)))
        for ln in stranded.splitlines() if "\t" in ln
    ]

    # Files main has that the executing tree does not: a whole feature can be
    # absent rather than stale, and absence renders as silence, not as an error.
    missing = []
    for ln in git(repo, "ls-tree", "-r", "--name-only", "origin/main", MESH_DIR).splitlines():
        if ln and not os.path.exists(os.path.join(repo, ln)):
            missing.append(ln)
    report["absent_from_tree"] = missing

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"repo        {repo}")
        print(f"branch      {branch}  ({head[:9]})")
        print(f"origin/main {main_sha[:9]}   tree_is_main={report['tree_is_main']}")
        print()
        for s in report["seats"]:
            mark = "IN FORCE" if s["fire_in_force"] else "STALE"
            print(f"  seat {s['seat']:<12} pid {s['pid']}  started {s['started']}")
            print(f"    fire    {s['fire_rel']}")
            print(f"            executing {s['fire_blob_executing'][:9]} vs main "
                  f"{s['fire_blob_main'][:9]}  [{mark}, drift={s['fire_drift']}]")
            print(f"    watcher {s['watcher_rel']}")
            if s["watcher_edited_under_running_process"]:
                print("            file was EDITED UNDER THE RUNNING PROCESS "
                      "— executing vintage is unnameable")
            print()
        print(f"stranded commits touching {MESH_DIR} "
              f"(merged to main, not in the executing tree): {len(report['stranded'])}")
        for c in report["stranded"]:
            print(f"  {c['sha']}  {c['subject']}")
        if report["absent_from_tree"]:
            print(f"\nfiles in main ABSENT from the executing tree: "
                  f"{len(report['absent_from_tree'])}")
            for f in report["absent_from_tree"]:
                print(f"  {f}")

    return sum(1 for s in report["seats"] if not s["fire_in_force"])


if __name__ == "__main__":
    sys.exit(main())
