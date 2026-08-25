#!/usr/bin/env python3
"""Report which engine file this seat's registered hook actually loads, and how old it is.

Host-state reporting only: reads, hashes, prints. Mutates nothing.

The thing worth measuring is not the hook. Every seat's hook is a thin shim that
resolves a sibling module two directory levels up and imports it; the imported
module is what decides. A seat can carry a current shim over a months-old engine
and every surface that inspects "the hook" will report it healthy.

So this resolves the sibling the way the shim does -- from the shim's own
location at runtime, never from a literal spelled here -- hashes what it finds,
and compares that to the tracked copy and to the tracked copy's upstream tip.

Exit status is a verdict, not an error:
  0  installed engine matches the tracked upstream tip
  1  installed engine differs (stale or forked) -- read the report
  2  could not determine (shim or engine not found)
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ENGINE_STEM = "hestia_governance_closure"
SIBLING_DIRNAME = "_shared"
PARENTS_UP = 2  # the shim's own resolution: parents[2] / _shared


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def find_shim() -> Path | None:
    """Locate the registered PreToolUse shim on this seat.

    Deliberately does NOT read the settings file: on a governed seat that read is
    itself gate-classified, and a probe that needs an approval to run is a probe
    nobody runs. The shim lives at a stable location per engine; check the ones
    that exist and take the first hit.
    """
    home = Path(os.path.expanduser("~"))
    candidates = [
        home / ".claude" / "hooks" / "hestia" / "pre_tool_use.py",
        home / ".codex" / "hooks" / "hestia" / "pre_tool_use.py",
        home / ".kimi" / "hooks" / "hestia" / "pre_tool_use.py",
    ]
    env = os.environ.get("HESTIA_SHIM_PATH")
    if env:
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def resolve_engine(shim: Path) -> Path | None:
    """Resolve the engine exactly as the shim does, including the env override that
    takes precedence over the relative walk."""
    override = os.environ.get("HESTIA_SHARED_DIR")
    shared = Path(override) if override else shim.parents[PARENTS_UP] / SIBLING_DIRNAME
    engine = shared / (ENGINE_STEM + ".py")
    return engine if engine.is_file() else None


def git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def tracked_copy(repo: Path) -> Path | None:
    hits = list(repo.glob("**/" + SIBLING_DIRNAME + "/" + ENGINE_STEM + ".py"))
    return hits[0] if hits else None


def main() -> int:
    repo = Path(__file__).resolve().parents[1]

    shim = find_shim()
    if shim is None:
        print("UNDETERMINED: no registered shim found on this seat")
        return 2
    engine = resolve_engine(shim)
    if engine is None:
        print("UNDETERMINED: shim at %s resolves no engine" % shim)
        print("  (the shim's Tier-2 fallback matcher is what would be enforcing)")
        return 2

    installed_sha = sha256(engine)
    print("shim      %s" % shim)
    print("engine    %s" % engine)
    print("installed %s  mtime=%s" % (
        installed_sha[:8],
        subprocess.run(["date", "-u", "-r", str(engine), "+%Y-%m-%dT%H:%M:%SZ"],
                       capture_output=True, text=True).stdout.strip() or "?",
    ))

    local = tracked_copy(repo)
    if local is None:
        print("UNDETERMINED: no tracked copy under %s" % repo)
        return 2
    local_sha = sha256(local)
    rel = local.relative_to(repo)
    print("tracked   %s  %s" % (local_sha[:8], rel))

    upstream_sha = None
    blob = git(repo, "rev-parse", "origin/main:%s" % rel)
    if blob:
        raw = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", blob],
                             capture_output=True, timeout=30)
        if raw.returncode == 0:
            upstream_sha = hashlib.sha256(raw.stdout).hexdigest()
            print("upstream  %s  origin/main:%s" % (upstream_sha[:8], rel))
    if upstream_sha is None:
        print("upstream  UNKNOWN (no origin/main copy readable)")

    reference = upstream_sha or local_sha
    label = "origin/main" if upstream_sha else "local tracked copy"

    if installed_sha == reference:
        print()
        print("VERDICT: installed engine MATCHES %s" % label)
        return 0

    print()
    print("VERDICT: installed engine DIFFERS from %s" % label)
    # Direction matters: if the installed bytes exist anywhere in this repo's
    # history the seat is merely behind (a fast-forward fixes it). If they exist
    # nowhere, the installed engine is off-history and copying over it would
    # discard whatever produced it.
    #
    # The search key must be a GIT OBJECT ID, not the content sha256 printed
    # above -- git names a blob by sha1 over "blob <len>\0<content>", so handing
    # --find-object a sha256 matches nothing, always, and the probe would report
    # FORKED for every seat including a perfectly healthy one. Ask git for the
    # id it would use.
    blob_id = git(repo, "hash-object", "--", str(engine))
    if not blob_id:
        print("  DIRECTION: undetermined (could not hash installed engine as a blob)")
        return 1

    # Enumerate every blob this PATH has ever carried, across all refs, and ask
    # whether the installed bytes are one of them.
    #
    # The obvious instrument -- `git log --find-object` -- is wrong here twice
    # over, and both ways it fails SILENTLY toward "not in history":
    #   1. it matches the blob at ANY path, so an unrelated file that once held
    #      identical bytes reads as a hit for this one;
    #   2. it does not diff merge commits by default, so a blob introduced by a
    #      merge is invisible to it.
    # Defect 2 is not hypothetical: run it against origin/main's own CURRENT
    # blob and it reports absent. That is the control below -- if the reference
    # blob is missing from the enumerated set, the set is not trustworthy and
    # this refuses to render a direction rather than guessing.
    history = set()
    for commit in (git(repo, "rev-list", "--all", "--", str(rel)) or "").split():
        b = git(repo, "rev-parse", "-q", "--verify", "%s:%s" % (commit, rel))
        if b:
            history.add(b)

    upstream_blob = git(repo, "rev-parse", "origin/main:%s" % rel)
    if upstream_blob and upstream_blob not in history:
        print("  DIRECTION: undetermined -- the path-history enumeration failed its"
              " own control (origin/main's live blob is absent from it), so any"
              " verdict from it would be an artifact")
    elif blob_id in history:
        print("  DIRECTION: installed bytes are a past version of THIS path"
              " (%d versions on record) -- seat is BEHIND, fast-forward is safe"
              % len(history))
    else:
        print("  DIRECTION: installed bytes match NO version this path has ever"
              " had -- FORKED; copying over it discards an unarchived engine")
    print("  This engine is what refuses and permits on this seat. The tracked")
    print("  copy is not consulted at runtime and its test results do not")
    print("  describe what is enforcing here.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
