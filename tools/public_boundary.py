#!/usr/bin/env python3
"""Fail when installation-local state or authority enters the public tree.

This is a source-boundary check, not a secret scanner for Git history.  It keeps
runtime evidence, operator discussion, worktrees, local scope derivation and
host-specific wiring out of new commits.  Historical credential review is a
separate release process because deleting a current file does not erase a blob.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_ROOTS = (
    ".hardbound/",
    "forum/",
    ".wt/",
    ".local-research/",
    ".local-deployment/",
    "deploy/cbp/",
)
LOCAL_PROBE = re.compile(r"^tools/(?:cbp|claude|codex|kimi)_")
LOCAL_HOME = re.compile(r"/home/([A-Za-z0-9_.-]+)/")
ALLOWED_SYNTHETIC_USERS = {"member", "user", "tester", "x", "u", "other"}
MOUNTED_HOST_PATH = re.compile(r"/mnt/[A-Za-z]/(?:[^\s'\"`]+/){2,}")
TOKEN_SHAPES = (
    re.compile(r"\bsk-(?:live|proj|svcacct)-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
RUNTIME_SUFFIXES = {".py", ".sh", ".json", ".toml", ".service", ".yaml", ".yml"}


def tracked_paths(repo: Path) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def is_test(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return ("tests" in parts or name.startswith("test_")
            or name.endswith(("_test.py", "_test.sh")))


def cached_texts(repo: Path, paths: list[str]) -> dict[str, str]:
    """Read index blobs in one Git process rather than one process per path."""
    request = "".join(f":{rel}\n" for rel in paths).encode()
    proc = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=repo, input=request,
        capture_output=True, check=True,
    )
    stream = io.BytesIO(proc.stdout)
    result: dict[str, str] = {}
    for rel in paths:
        header = stream.readline().rstrip(b"\n")
        if header.endswith(b" missing"):
            continue
        fields = header.split()
        if len(fields) != 3 or fields[1] != b"blob":
            raise RuntimeError(f"unexpected git cat-file header for {rel}: {header!r}")
        size = int(fields[2])
        raw = stream.read(size)
        if stream.read(1) != b"\n":
            raise RuntimeError(f"missing git cat-file delimiter after {rel}")
        try:
            result[rel] = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return result


def worktree_text(repo: Path, rel: str) -> str | None:
    full = repo / rel
    if not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def inspect(repo: Path, paths: list[str], *, cached: bool = False) -> list[str]:
    problems: list[str] = []
    index = cached_texts(repo, paths) if cached else {}
    for rel in paths:
        if rel.startswith(FORBIDDEN_ROOTS):
            problems.append(f"{rel}: installation-local root is tracked")
            continue
        if LOCAL_PROBE.match(rel):
            problems.append(f"{rel}: seat-prefixed research probe is tracked")
        text = index.get(rel) if cached else worktree_text(repo, rel)
        if text is None:
            continue

        boundary_impl = rel == "tools/public_boundary.py"
        if not boundary_impl:
            for token_re in TOKEN_SHAPES:
                if token_re.search(text):
                    problems.append(f"{rel}: credential-shaped token")
                    break
        if "-----BEGIN PRIVATE KEY-----" in text and not is_test(rel) and not boundary_impl:
            problems.append(f"{rel}: private-key header outside an adversarial test")

        runtime = (Path(rel).suffix in RUNTIME_SUFFIXES and not is_test(rel)
                   and not boundary_impl)
        if runtime:
            if "private-context" in text or "repos.jsonl" in text:
                problems.append(f"{rel}: runtime mechanism depends on private operator context")
            if MOUNTED_HOST_PATH.search(text):
                problems.append(f"{rel}: runtime mechanism bakes a mounted-host path")
            for user in LOCAL_HOME.findall(text):
                if user not in ALLOWED_SYNTHETIC_USERS:
                    problems.append(f"{rel}: runtime mechanism bakes a local home path")
                    break

        if rel.endswith("/hooks/hydrate.sh"):
            for forbidden in ("HESTIA_REPO_REGISTRY", "repos.jsonl", "PRIVATE_EXCEPTIONS",
                              'ident.setdefault("mrh"', '["in_scope"] ='):
                if forbidden in text:
                    problems.append(f"{rel}: continuity hook writes authorization ({forbidden})")

        if rel.endswith("/instance/identity.seed.json"):
            try:
                seed = json.loads(text)
            except json.JSONDecodeError as exc:
                problems.append(f"{rel}: invalid JSON: {exc}")
                continue
            if seed.get("relationships"):
                problems.append(f"{rel}: public seed contains installation relationships")
            if (seed.get("mrh") or {}).get("in_scope"):
                problems.append(f"{rel}: public seed contains installation scope")

    return sorted(set(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cached", action="store_true",
        help="inspect the staged index exactly (for a composable pre-commit check)",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    problems = inspect(repo, tracked_paths(repo), cached=args.cached)
    if problems:
        print("PUBLIC BOUNDARY: FAIL")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("PUBLIC BOUNDARY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
