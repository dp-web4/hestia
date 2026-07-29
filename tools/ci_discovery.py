#!/usr/bin/env python3
"""Single source of truth for which test files CI runs.

CI calls this to GET the list. The guards import it to REASON about the list.
There is therefore no "model of CI" to fall out of step with CI -- the previous
design had two globs living in ci.yml and a copy of them in a test, and the
whole class of bug being fixed here is a copy drifting from its original.

The split:

  bare_python_files()  -> run by the `plugin tests (python)` job as `python3 F`
  hooks_job_files()    -> run by the `hook tests (python)` job, which needs
                          cwd=plugins/claude-code/hooks (those tests import the
                          hook modules sitting next to them) and setup-python
  excluded()           -> declared un-runnable in tools/ci_excluded_tests.txt,
                          each with a written reason

Every tracked test-shaped file belongs to exactly one of those three, and
tools/ci_test_coverage_test.py fails if any file belongs to none.

Discovery is from `git ls-files`, not the filesystem: an untracked scratch file
in somebody's worktree is not the repo's obligation, and a tracked file is one
whether or not it happens to be checked out.

Usage:
    python3 tools/ci_discovery.py bare    # newline-separated, for CI
    python3 tools/ci_discovery.py hooks
    python3 tools/ci_discovery.py excluded
    python3 tools/ci_discovery.py report  # human-readable audit of all three
"""

import pathlib
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

MANIFEST = REPO / "tools" / "ci_excluded_tests.txt"

# The hooks job owns this directory: those tests import the hook modules beside
# them, so they need that cwd and cannot be run from the repo root.
HOOKS_DIR = "plugins/claude-code/hooks"


def is_test_shaped(path: str) -> bool:
    """Both conventions the repo actually uses.

    The prefix/suffix split is exactly what hid seven files: `plugins/*/tests/
    *_test.py` could not see `test_path_scope.py` sitting in the very directory
    it globs. Discovery accepts both and stops caring which a author picked.
    """
    name = path.rsplit("/", 1)[-1]
    if not name.endswith(".py"):
        return False
    return name.endswith("_test.py") or name.startswith("test_")


def tracked_python_files() -> list[str]:
    """Every tracked .py. The raw material the anchors in the coverage test
    sweep with rules deliberately looser than is_test_shaped()."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO,
        capture_output=True, check=True,
    ).stdout
    return sorted(
        p for p in (raw.decode() for raw in out.split(b"\0") if raw)
        if p.endswith(".py")
    )


def all_test_shaped() -> list[str]:
    return [p for p in tracked_python_files() if is_test_shaped(p)]


def excluded() -> list[str]:
    """Paths declared un-runnable, from the manifest. Reasons live in comments."""
    if not MANIFEST.exists():
        return []
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return sorted(
        s for s in (ln.strip() for ln in lines)
        if s and not s.startswith("#")
    )


def hooks_job_files() -> list[str]:
    return [p for p in all_test_shaped() if p.startswith(HOOKS_DIR + "/")]


def bare_python_files() -> list[str]:
    """What the plugin-tests job runs, from the repo root, with bare python3."""
    skip = set(excluded()) | set(hooks_job_files())
    return [p for p in all_test_shaped() if p not in skip]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "bare":
        print("\n".join(bare_python_files()))
    elif mode == "hooks":
        print("\n".join(hooks_job_files()))
    elif mode == "excluded":
        print("\n".join(excluded()))
    elif mode == "report":
        every = all_test_shaped()
        bare, hooks, exc = bare_python_files(), hooks_job_files(), excluded()
        print(f"{len(every)} test-shaped file(s) tracked\n")
        for label, group in (("RUN (plugin tests job)", bare),
                            ("RUN (hook tests job)", hooks),
                            ("DECLARED NOT RUN", exc)):
            print(f"  {label}: {len(group)}")
            for p in group:
                print(f"      {p}")
        orphans = sorted(set(every) - set(bare) - set(hooks) - set(exc))
        print(f"\n  UNACCOUNTED: {len(orphans)}")
        for p in orphans:
            print(f"      {p}")
        return 1 if orphans else 0
    else:
        print(f"unknown mode {mode!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
