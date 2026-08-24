#!/usr/bin/env python3
"""Rust build-artifact reaper for the fleet workspace: measure, classify, then reap.

WHY THIS EXISTS. The workspace fills with `target/` directories — 58GB across 15 of them
when this was written, on a host whose single physical disk was at 94% — and the cleanup
has been done ad hoc every time, from memory, by whoever noticed. Nothing in any repo
mentioned `cargo clean`. Done from memory, it goes wrong in one specific way, below.

THE TRAP THIS EXISTS TO PREVENT. `CARGO_TARGET_DIR` is exported in this workspace,
pointing at the SHARED WARM target that the build-lock shim relies on to keep worktree
builds incremental. A plain `cargo clean`, run in any crate, therefore cleans the shared
cache and leaves every stale per-repo `target/` exactly where it was. That is the precise
inverse of the intent: it destroys the one directory whose warmth is load-bearing — a cold
rebuild afterwards saturates the 9p mount that every member's gate call traverses — while
reclaiming none of the dead weight. So this tool never invokes a bare `cargo clean`; it
always passes `--target-dir` explicitly, and it refuses outright to touch the shared one.

WHY `cargo clean` AND NOT `rm -rf`. Two reasons, and the second is the load-bearing one.
It is the tool that owns the directory. And the governance gate refuses `rm` outside
absolute /tmp paths, so a reaper built on `rm` would be a reaper that has to be escalated
or routed around every single time — which is how a protocol stops being followed.

POLICY, stated so it can be argued with rather than inferred from behaviour:
  - PROTECTED, never reaped: the shared `CARGO_TARGET_DIR`; any target whose OWN CRATE
    DIRECTORY has uncommitted changes (mid-experiment: rebuilding is cheap but re-deriving
    what someone was doing is not). Scoped to the crate, not the repository — a repo whose
    dirt lives in an unrelated subtree (daemon-written instance state, for instance) is not
    evidence that this crate's target is warm. See `tree_is_dirty`.
  - FRESH: touched within --fresh-days (default 14). Reported, not reaped, because a warm
    target for something in active use is worth more than the space.
  - STALE: everything else. Reaped only with --reap.

DEFAULT IS REPORT-ONLY. `--reap` is required to delete anything, and the tool refuses to
run at all while a build is in flight.

Usage:
    tools/cargo_target_reaper.py                 # measure and classify, delete nothing
    tools/cargo_target_reaper.py --reap          # reap the STALE set
    tools/cargo_target_reaper.py --reap --fresh-days 30
"""

import argparse
import os
import subprocess
import sys
import time

FRESH_DAYS_DEFAULT = 14


# One fact, one precedence, in the order the rest of the fleet resolves it.
#
# This tool read only FLEET_ROOT, a THIRD spelling of the workspace root — the others being
# HESTIA_WORKSPACE, which this daemon's own service unit carries (docs/ENVIRONMENT.md), and
# AI_WORKSPACE, which operator tooling around a multi-repo checkout conventionally sets.
# A second name for one fact is what a deployment silently disagrees over: nothing is
# broken, but an operator who has configured a workspace root has still not configured
# THIS, so the tool measures a different tree than the scripts beside it.
#
# FLEET_ROOT keeps working — it may be set on seats and in units nobody has audited, and
# breaking it to tidy a name would trade a real outage for a cosmetic one. It is last, and
# documented as legacy.
WORKSPACE_ENV_VARS = ("AI_WORKSPACE", "HESTIA_WORKSPACE", "FLEET_ROOT")


def workspace_root():
    """The directory holding the sibling repos. Derived, never hardcoded — the fleet spans
    three filesystem conventions and `tools/public_boundary.py` bans baked paths.

    Precedence: AI_WORKSPACE, then HESTIA_WORKSPACE, then FLEET_ROOT (legacy), then derived
    from this file's location. A set-but-missing value is reported and REFUSED rather than
    silently skipped — ignoring what an operator configured is its own class of surprise,
    and a reaper that quietly measures a different tree than the one you named is worse
    than one that stops."""
    for var in WORKSPACE_ENV_VARS:
        env = os.environ.get(var)
        if not env:
            continue
        if os.path.isdir(env):
            return env
        sys.exit("%s is set to %s, which is not a directory. Fix it or unset it; "
                 "this tool will not fall back to a guess when you have named a root."
                 % (var, env))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <root>/hestia
    return os.path.dirname(here)


def is_cargo_target(path):
    """A cargo target dir IDENTIFIES ITSELF; do not ask what it is named.

    Measured 2026-08-23: this tool reported "0 reapable, 5 dirs seen" on a workspace whose
    single largest item was `hestia/.kimi-target` at 14.8 GB. It was invisible because the
    scan matched the literal name `target`, and that directory is not spelled `target`.
    A name is a convention; what cargo writes inside is evidence.

    NOT CACHEDIR.TAG. The first version of this check read that file and matched the
    signature `8a477f597d28d172789f06886806bc55` — which is the signature from the
    *cachedir spec itself*, written identically by pytest, and it pulled in fifteen
    `.pytest_cache` directories as "cargo targets". A shared standard cannot identify one
    of its users. `.rustc_info.json` is cargo's own, and the debug/release pair is the
    shape nothing else has."""
    if os.path.isfile(os.path.join(path, ".rustc_info.json")):
        return True
    # A target dir cargo has built into, whose .rustc_info.json was cleaned away: require
    # BOTH the cache tag and cargo's profile layout, so a bare cache dir cannot qualify.
    if not os.path.isfile(os.path.join(path, "CACHEDIR.TAG")):
        return False
    return any(os.path.isdir(os.path.join(path, prof))
               for prof in ("debug", "release"))


def stray_files(target):
    """Files at the target ROOT that cargo did not put there.

    `cargo clean` deletes the whole directory, strays included. Measured 2026-08-23:
    `.kimi-target` held six — three of kimi-code's verification scripts
    (`verify_0013_prd_claims.py` and siblings), their measured JSON outputs, and a drafted
    PR body. Regenerable is not the same as unused, and a build cache is a place people
    put things. Reaping refuses on strays rather than discovering this the hard way."""
    keep = {"CACHEDIR.TAG", ".rustc_info.json"}
    try:
        return sorted(f for f in os.listdir(target)
                      if f not in keep and os.path.isfile(os.path.join(target, f)))
    except Exception:
        return []


def worktree_roots(root):
    """Git worktrees living OUTSIDE the workspace root.

    Measured 2026-08-23: of 47 hestia worktrees, 15 were under /tmp — entirely outside any
    walk rooted at the workspace, so a workspace-rooted scan cannot see their targets and
    reports a confident zero for them. Asking git where its worktrees are beats assuming
    they are where we would have put them."""
    out = []
    try:
        entries = sorted(os.listdir(root))
    except Exception:
        return out
    real_root = os.path.realpath(root)
    for name in entries:
        repo = os.path.join(root, name)
        if not os.path.exists(os.path.join(repo, ".git")):
            continue
        try:
            r = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"],
                               capture_output=True, text=True, timeout=120)
        except Exception:
            continue
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            wt = line.split(" ", 1)[1]
            if not os.path.realpath(wt).startswith(real_root) and os.path.isdir(wt):
                out.append(wt)
    return sorted(set(out))


def find_targets(root, max_depth=6):
    """Depth 6, not 4: nested worktrees put a target at `<root>/repo/.wt/<name>/core/target`,
    which is five levels down. The old default could not reach them even once `.wt` was
    traversable."""
    out = []
    root_depth = root.rstrip("/").count("/")
    for dirpath, dirnames, _ in os.walk(root):
        if dirpath.count("/") - root_depth >= max_depth:
            dirnames[:] = []
            continue
        # `.wt` USED TO BE EXCLUDED HERE, beside `.git` and `node_modules`. That hid 18
        # worktrees and 19 GB by construction — the exclusion was written when `.wt` was
        # assumed to be git internals, and it is not: it is where worktrees live.
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules") and not d.startswith(".venv")]
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if is_cargo_target(full):
                # Crate attribution is an ATTRIBUTE, not a filter. An orphan target with no
                # sibling manifest is still a real target dir holding real gigabytes, and
                # `cargo clean --target-dir` cleans it from any crate.
                crate = dirpath if os.path.isfile(os.path.join(dirpath, "Cargo.toml")) else None
                out.append((crate, full))
            else:
                keep.append(d)
        dirnames[:] = keep
    return sorted(out, key=lambda r: r[1])


def du_mb(path):
    try:
        r = subprocess.run(["du", "-s", "--block-size=1M", path],
                           capture_output=True, text=True, timeout=1800)
        return int(r.stdout.split()[0]) if r.returncode == 0 and r.stdout.split() else None
    except Exception:
        return None


def newest_mtime(path, cap=4000):
    """Directory mtime lies about build recency — writing a file deep in the tree does not
    touch the root. Sample the newest mtime instead, bounded so this stays cheap."""
    newest = 0.0
    seen = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                m = os.lstat(os.path.join(dirpath, f)).st_mtime
            except OSError:
                continue
            newest = max(newest, m)
            seen += 1
            if seen >= cap:
                return newest
    return newest or os.path.getmtime(path)


def tree_is_dirty(crate_dir):
    try:
        # `-- .` is load-bearing. `git status` reports the WHOLE repository regardless
        # of `-C`, so without a pathspec this asks "is any file in this repo dirty?" while
        # being named `crate_dir` and read as "is this crate dirty?".
        #
        # Measured on a fleet host 2026-08-21: SAGE/sage-rs classified PROTECTED(dirty)
        # holding 324MB, while the crate itself was clean — the six dirty entries were
        # sage-daemon instance state under sage/instances/, rewritten every couple of
        # minutes. On that host the repo is dirty ~100% of the time by construction, so
        # the protection was permanently ON for that crate, and a signal that is always on
        # carries no information: it exempted a crate rather than protecting an experiment.
        #
        # Scoping to the crate keeps the rule's INTENT — do not reap the warm target of
        # something someone is actively working on — and drops only the case where the
        # dirt is in an unrelated subtree.
        r = subprocess.run(["git", "-C", crate_dir, "status", "--porcelain", "--", "."],
                           capture_output=True, text=True, timeout=300)
        return bool(r.stdout.strip()) if r.returncode == 0 else False
    except Exception:
        return False


def build_running():
    for name in ("cargo", "rustc"):
        try:
            if subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0:
                return name
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reap", action="store_true", help="actually clean the STALE set")
    ap.add_argument("--fresh-days", type=int, default=FRESH_DAYS_DEFAULT)
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    root = args.root or workspace_root()
    shared = os.path.realpath(os.environ.get("CARGO_TARGET_DIR", "")) if os.environ.get("CARGO_TARGET_DIR") else None

    busy = build_running()
    if busy and args.reap:
        print(f"REFUSING: {busy} is running. Reaping a target dir under an active build "
              f"corrupts it and the failure surfaces later, somewhere else.", file=sys.stderr)
        return 2

    print(f"workspace: {root}")
    print(f"shared CARGO_TARGET_DIR: {shared or '(unset)'}"
          f"{'  <- PROTECTED' if shared else ''}")
    if shared:
        print("  a bare `cargo clean` would clean THAT and nothing else; this tool never does.")
    print()

    now = time.time()
    # Worktrees outside the workspace are scanned too — 15 of hestia's live under /tmp,
    # and a walk rooted at the workspace reports a confident zero for every one of them.
    scan_roots = [root] + worktree_roots(root)
    if len(scan_roots) > 1:
        print(f"  + {len(scan_roots) - 1} worktree root(s) outside the workspace")
        print()

    found = []
    seen = set()
    for r_ in scan_roots:
        for crate, target in find_targets(r_):
            real = os.path.realpath(target)
            if real in seen:
                continue
            seen.add(real)
            found.append((crate, target))

    rows = []
    for crate, target in found:
        strays = stray_files(target)
        if shared and os.path.realpath(target) == shared:
            cls = "PROTECTED(shared)"
        elif crate and tree_is_dirty(crate):
            cls = "PROTECTED(dirty)"
        elif strays:
            # Not a warning. `cargo clean` would delete these, and they are the one thing
            # in a target dir that no build can put back.
            cls = "PROTECTED(strays)"
        else:
            age_days = (now - newest_mtime(target)) / 86400.0
            cls = "FRESH" if age_days < args.fresh_days else "STALE"
        rows.append({"crate": crate, "target": target, "cls": cls, "strays": strays,
                     "mb": du_mb(target) or 0,
                     "age": (now - newest_mtime(target)) / 86400.0})

    rows.sort(key=lambda r: -r["mb"])

    def label(r):
        # Orphan targets have no crate; name the TARGET so the row still points at a path.
        base = r["crate"] or r["target"]
        try:
            rel = os.path.relpath(base, root)
        except ValueError:
            rel = base
        return rel if not rel.startswith("../") else base

    width = max((len(label(r)) for r in rows), default=20)
    for r in rows:
        suffix = ""
        if r["cls"] == "PROTECTED(strays)":
            suffix = f"  <- {len(r['strays'])} non-build file(s): {', '.join(r['strays'][:3])}"
        elif r["crate"] is None:
            suffix = "  <- orphan target (no owning Cargo.toml)"
        print(f"  {r['mb']:>7} MB  {r['age']:>5.0f}d  {r['cls']:<18} "
              f"{label(r):<{width}}{suffix}")

    stale = [r for r in rows if r["cls"] == "STALE"]
    total = sum(r["mb"] for r in stale)
    print(f"\n  reapable (STALE): {len(stale)} dirs, {total} MB "
          f"({total/1024:.1f} GB)")
    protected = [r for r in rows if r["cls"].startswith("PROTECTED")]
    if protected:
        print(f"  protected:        {len(protected)} dirs, "
              f"{sum(r['mb'] for r in protected)} MB — not touched")

    if not args.reap:
        print("\n  report only. re-run with --reap to clean the STALE set.")
        return 0

    print()
    freed = 0
    for r in stale:
        # `--target-dir` explicitly, so the exported CARGO_TARGET_DIR cannot redirect this
        # at the shared cache. This is the whole safety property of the tool.
        # `cargo clean --target-dir` works from ANY crate, so an orphan target (no owning
        # manifest) is still reapable — run it from this tool's own crate in that case.
        cwd = r["crate"] or os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "core")
        p = subprocess.run(["cargo", "clean", "--target-dir", r["target"]],
                           cwd=cwd, capture_output=True, text=True, timeout=3600)
        line = (p.stderr or p.stdout).strip().splitlines()
        msg = line[-1].strip() if line else f"exit {p.returncode}"
        # `label()`, not relpath: an ORPHAN target has no crate, and relpath(None) raises
        # ValueError mid-reap — after some dirs are already gone. Measured 2026-08-23: it
        # crashed having reaped 1 of 5, leaving the operator with a traceback instead of a
        # report of what had just been deleted. A reporting line must not be able to abort
        # the loop it is reporting on.
        print(f"  {label(r):<{width}} {msg}")
        if p.returncode == 0:
            freed += r["mb"]
    print(f"\n  reclaimed ~{freed} MB ({freed/1024:.1f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
