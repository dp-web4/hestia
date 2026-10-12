#!/usr/bin/env python3
"""The lockstep version check (tools/version_sync.py), on the repo and on a broken copy of it.

1. THE GATE: every manifest in this commit agrees with the root VERSION. This file is in the
   discovered test set (tools/ci_discovery.py), so a PR that bumps one manifest and not the
   others is red in `plugin tests (python)`.
2. The checker sees drift at every site it claims (each site is broken in turn in a temp copy:
   a site the checker cannot see failing is a site it does not check).
3. `--write` repairs the copy to a state the checker passes, without reformatting: the only
   changed lines are version lines.
4. The release check: a tag equal to v$VERSION passes, anything else fails.

Run: python3 tools/version_sync_test.py   (bare; exit 1 on failure)
"""
import difflib
import importlib.util
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("version_sync", HERE / "version_sync.py")
VS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VS)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILS.append(name + (f"\n    {detail}" if detail else ""))


def copy_tree(dst: pathlib.Path) -> None:
    (dst / "VERSION").write_text((VS.REPO / "VERSION").read_text())
    for rel in {s.rel for s in VS.SITES}:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VS.REPO / rel, dst / rel)


def main() -> int:
    # 1. the repo itself
    problems = VS.check()
    check("this commit's manifests agree with VERSION", not problems, "\n    ".join(problems))
    version = VS.read_version()
    check("VERSION is X.Y.Z", bool(VS.SEMVER.match(version)), version)

    # 2. each site, broken alone, is seen
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        copy_tree(root)
        check("a pristine copy passes", VS.check(root) == [], str(VS.check(root)))
        for site in VS.SITES:
            p = site.path(root)
            original = p.read_text()
            p.write_text(site.write(original, "9.9.9"))
            got = VS.check(root)
            check(f"breaking {site.rel} [{site.label}] is reported", len(got) == 1 and site.rel in got[0],
                  str(got))
            p.write_text(original)

    # 3. --write repairs a copy where everything drifted, touching only version lines
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        copy_tree(root)
        before = {s.rel: s.path(root).read_text() for s in VS.SITES}
        (root / "VERSION").write_text("7.8.9\n")
        check("a VERSION bump alone is drift at every site", len(VS.check(root)) == len(VS.SITES),
              str(len(VS.check(root))))
        changed = VS.write(root)
        check("--write leaves no drift", VS.check(root) == [], str(VS.check(root)))
        check("--write touched every file", sorted(changed) == sorted(before), str(changed))
        for rel, old in before.items():
            new = (root / rel).read_text()
            for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                    check(f"{rel}: --write changed only version text", "7.8.9" in line or re.search(
                        r"version|hestia-wire", line) is not None, line)
        check("--write is idempotent", VS.write(root) == [])

    # 4. the release tag
    check("tag v$VERSION passes", VS.tag_problem(f"v{version}") is None)
    check("refs/tags/v$VERSION passes", VS.tag_problem(f"refs/tags/v{version}") is None)
    for bad in (version, f"v{version}.1", "v0.0.4", f"app-v{version}"):
        check(f"tag {bad!r} fails", VS.tag_problem(bad) is not None)
    check("the CLI exits 1 on a wrong tag", VS.main(["--tag", "v0.0.0"]) == 1)
    check("the CLI exits 0 on the right tag", VS.main(["--tag", f"v{version}"]) == 0)

    for f in FAILS:
        print("FAIL", f)
    print(f"version_sync: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s); "
          f"{len(VS.SITES)} sites, VERSION={version})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
