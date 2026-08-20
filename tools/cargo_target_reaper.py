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
  - PROTECTED, never reaped: the shared `CARGO_TARGET_DIR`; any target inside a git
    worktree with uncommitted changes (a dirty tree may be mid-experiment, and rebuilding
    is cheap but re-deriving what someone was doing is not).
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


def workspace_root():
    """The directory holding the sibling repos. Derived, never hardcoded — the fleet spans
    three filesystem conventions and `tools/public_boundary.py` bans baked paths."""
    env = os.environ.get("FLEET_ROOT")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <root>/hestia
    return os.path.dirname(here)


def find_targets(root, max_depth=4):
    out = []
    root_depth = root.rstrip("/").count("/")
    for dirpath, dirnames, _ in os.walk(root):
        if dirpath.count("/") - root_depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".wt") and not d.startswith(".venv")]
        if "target" in dirnames:
            t = os.path.join(dirpath, "target")
            # A target dir is only reapable through cargo if a manifest owns it.
            if os.path.isfile(os.path.join(dirpath, "Cargo.toml")):
                out.append((dirpath, t))
            dirnames.remove("target")
    return sorted(out)


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
        r = subprocess.run(["git", "-C", crate_dir, "status", "--porcelain"],
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
    rows = []
    for crate, target in find_targets(root):
        if shared and os.path.realpath(target) == shared:
            cls = "PROTECTED(shared)"
        elif tree_is_dirty(crate):
            cls = "PROTECTED(dirty)"
        else:
            age_days = (now - newest_mtime(target)) / 86400.0
            cls = "FRESH" if age_days < args.fresh_days else "STALE"
        rows.append({"crate": crate, "target": target, "cls": cls,
                     "mb": du_mb(target) or 0,
                     "age": (now - newest_mtime(target)) / 86400.0})

    rows.sort(key=lambda r: -r["mb"])
    width = max((len(os.path.relpath(r["crate"], root)) for r in rows), default=20)
    for r in rows:
        print(f"  {r['mb']:>7} MB  {r['age']:>5.0f}d  {r['cls']:<18} "
              f"{os.path.relpath(r['crate'], root):<{width}}")

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
        p = subprocess.run(["cargo", "clean", "--target-dir", r["target"]],
                           cwd=r["crate"], capture_output=True, text=True, timeout=3600)
        line = (p.stderr or p.stdout).strip().splitlines()
        msg = line[-1].strip() if line else f"exit {p.returncode}"
        print(f"  {os.path.relpath(r['crate'], root):<{width}} {msg}")
        if p.returncode == 0:
            freed += r["mb"]
    print(f"\n  reclaimed ~{freed} MB ({freed/1024:.1f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
