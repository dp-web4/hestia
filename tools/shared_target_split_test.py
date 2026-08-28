#!/usr/bin/env python3
"""A path dependency compiled under two spellings of its own location is one crate twice.

WHY THIS EXISTS. On 2026-08-27 every hestia worktree stopped building locally while CI
stayed green. The compiler said:

    note: there are multiple different versions of crate `serde_core` in the dependency graph

while `cargo tree -i serde_core` showed exactly one. The dependency GRAPH was clean; the
ARTIFACTS were split. hestia declares web4 crates as relative path deps (`../../web4/...`),
cargo hashes the path STRING it computes and never canonicalizes it, so:

    hestia/core             records  ai-agents/web4/web4-trust-core
    hestia/.wt/<name>/core  records  hestia/.wt/web4/web4-trust-core   (a symlink, same dir)

Same crate, same real location, two metadata hashes, two artifact sets in the shared
CARGO_TARGET_DIR. A downstream crate links the copy its fingerprint did not name, and rustc
reports the only thing it can see -- a trait bound on some transitive crate -- forty lines
from anything that names the cause. It was diagnosed as a branch bug three separate times.

WHAT THIS CHECKS. For every package in the CURRENT checkout's graph whose source is a
PATH (not a registry), count the fingerprint directories the shared target holds for it.
The healthy number is exactly one. Two or more means two spellings, and this says so in
words instead of leaving it to rustc.

TWO KINDS OF CRATE ARE DELIBERATELY NOT COUNTED, and each exclusion was learned by the
guard going red on a healthy target:

  Registry crates. `serde_core` legitimately has ten fingerprint dirs (host vs target,
  feature sets, build-script variants) and none of them is a defect.

  Crates INSIDE this git checkout. `hestia` had 217 variants on the day this was written
  and every one was correct: each worktree's `hestia/core` IS a different source tree on a
  different branch, so one artifact set per worktree is the healthy state. The first
  version of this guard counted them and reported the defect it exists to catch against a
  target that had just been fixed. The second version excluded only cargo's workspace
  members and then flagged `hestia-wire` (23 variants) -- a sibling path dep at `../wire`,
  outside cargo's `workspace_root` of `core/` but inside the same checkout, varying per
  worktree for the same legitimate reason. The boundary is the GIT TOPLEVEL.

Only EXTERNAL path dependencies -- packages whose manifest lives outside this checkout --
must resolve to one spelling, because only those are the same source reached from many
places. A guard that is red forever gets ignored, which is how the 37-second shebang guard
ended up reporting from CI logs instead of preventing anything.

WHAT THIS DOES NOT DO. It does not fix anything and does not clean anything. The fix is
the `paths` override in an ancestor `.cargo/config.toml` (see `.cargo/config.toml.example`
at the repo root) plus `cargo clean -p` on the affected crates once, and both of those are
decisions a person should make with the reason in front of them.

Exit status is a verdict:
  0  every path-dependency crate has exactly one artifact set in the shared target
  1  at least one is split -- the report names the crate and the remedy
  2  cannot determine (no shared target, no cargo, or discovery found no path deps)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def external_path_dep_names(manifest_dir: Path) -> set[str]:
    """Package names whose source is a path (`source: null`) AND whose manifest lives
    OUTSIDE this git checkout.

    Workspace members are excluded on purpose: a worktree's own crates are a different
    source tree per worktree, so several artifact sets for them is the healthy state, not
    the defect. The defect is one EXTERNAL directory reached under two spellings, and that
    is exactly the set this returns.
    """
    out = subprocess.run(
        ["cargo", "metadata", "--format-version", "1"],
        cwd=manifest_dir, capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-300:] or "cargo metadata failed")
    meta = json.loads(out.stdout)
    # THE BOUNDARY IS THE GIT CHECKOUT, NOT CARGO'S WORKSPACE ROOT. The first cut used
    # `workspace_root`, which for hestia is `core/` -- and `wire/` is a sibling path dep at
    # `../wire`, outside `core/` but inside the same checkout. It was reported as split
    # (23 variants) when every one of them was a different worktree's own copy. Same
    # misclassification as counting `hestia` itself, one directory out. Anything under the
    # git toplevel is ours and legitimately varies per worktree; only what lies OUTSIDE the
    # checkout is one directory that several checkouts must agree on.
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=manifest_dir, capture_output=True, text=True,
    )
    if top.returncode != 0:
        raise RuntimeError("not inside a git checkout; cannot tell own crates from external")
    root = Path(top.stdout.strip()).resolve()
    names = set()
    for p in meta["packages"]:
        if p.get("source") is not None:
            continue
        try:
            Path(p["manifest_path"]).resolve().relative_to(root)
            continue                      # under the checkout: a workspace member, skip
        except ValueError:
            names.add(p["name"])          # outside it: an external path dep, check
    return names


def variants(fingerprint_dir: Path, name: str) -> list[str]:
    """Fingerprint directories for `name`: `<name>-<16 hex>`. The hyphen-then-hash suffix
    is what separates `web4-core-abc...` from `web4-core-derive-abc...`, so match the
    exact prefix plus hash rather than a bare startswith."""
    hits = []
    for d in fingerprint_dir.iterdir():
        if not d.is_dir():
            continue
        stem, _, suffix = d.name.rpartition("-")
        if stem == name and len(suffix) == 16 and all(c in "0123456789abcdef" for c in suffix):
            hits.append(d.name)
    return sorted(hits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest-dir", default=None,
                    help="directory holding the Cargo.toml to resolve (default: core/ "
                         "beside this file's repo root, else cwd)")
    ap.add_argument("--fingerprint-dir", default=None,
                    help="override the fingerprint directory (default: "
                         "$CARGO_TARGET_DIR/debug/.fingerprint). Used by the sabotage arm.")
    ap.add_argument("--names", default=None,
                    help="comma-separated crate names to check instead of discovering "
                         "them via cargo metadata. Used by the sabotage arm.")
    args = ap.parse_args()

    if args.fingerprint_dir:
        fp = Path(args.fingerprint_dir)
    else:
        target = os.environ.get("CARGO_TARGET_DIR")
        if not target:
            print("cannot determine: CARGO_TARGET_DIR is not set, so there is no SHARED "
                  "target for two checkouts to disagree in. Per-checkout targets cannot "
                  "have this defect.", file=sys.stderr)
            return 2
        fp = Path(target) / "debug" / ".fingerprint"
    if not fp.is_dir():
        print(f"cannot determine: no fingerprint directory at {fp}", file=sys.stderr)
        return 2

    if args.names:
        names = {n.strip() for n in args.names.split(",") if n.strip()}
    else:
        here = Path(__file__).resolve()
        manifest_dir = Path(args.manifest_dir) if args.manifest_dir else here.parent.parent / "core"
        if not (manifest_dir / "Cargo.toml").is_file():
            manifest_dir = Path.cwd()
        try:
            names = external_path_dep_names(manifest_dir)
        except Exception as e:  # noqa: BLE001 - any failure here is the same verdict
            print(f"cannot determine: {e}", file=sys.stderr)
            return 2
    if not names:
        print("cannot determine: discovery found no EXTERNAL path dependencies", file=sys.stderr)
        return 2

    split = {}
    for n in sorted(names):
        v = variants(fp, n)
        if len(v) > 1:
            split[n] = v

    print(f"shared target : {fp}")
    print(f"external path-dep crates: {len(names)} checked ({', '.join(sorted(names))})")
    if not split:
        print("PASS  every path-dependency crate has exactly one artifact set")
        return 0

    print(f"FAIL  {len(split)} path-dependency crate(s) compiled under MORE THAN ONE spelling "
          f"of their location:\n")
    for n, v in split.items():
        print(f"    {n}")
        for d in v:
            print(f"        {d}")
    print(
        "\nThis is one crate twice, not two versions. Cargo hashed two different PATH STRINGS\n"
        "for the same directory (typically a relative `../../` dep reached from checkouts at\n"
        "different depths, one of them through a symlink). Downstream crates link whichever\n"
        "copy their fingerprint named, and rustc reports it as 'multiple different versions'\n"
        "of some transitive crate -- nowhere near the cause.\n"
        "\n"
        "Remedy (both halves, in this order):\n"
        "  1. give every checkout ONE spelling: a `paths = [...]` override in a .cargo/config.toml\n"
        "     ABOVE every checkout, listing each affected crate by absolute path\n"
        "     (see .cargo/config.toml.example at the repo root);\n"
        "  2. `cargo clean -p " + " -p ".join(split) + "` once, because the override changes\n"
        "     the crates' identities and the old compilations are invalid by construction.\n"
        "A PARTIAL override is worse than none: the crates left out still arrive by the old\n"
        "spelling and drag their own copies of the shared ones with them.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
