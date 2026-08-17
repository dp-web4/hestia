#!/usr/bin/env python3
"""Fail when installation-local state or authority enters the public tree.

This is a source-boundary check, not a secret scanner for Git history.  It keeps
runtime evidence, operator discussion, worktrees, local scope derivation and
host-specific wiring out of new commits.  Historical credential review is a
separate release process because deleting a current file does not erase a blob.
"""
from __future__ import annotations

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


def inspect(repo: Path, paths: list[str]) -> list[str]:
    problems: list[str] = []
    for rel in paths:
        if rel.startswith(FORBIDDEN_ROOTS):
            problems.append(f"{rel}: installation-local root is tracked")
            continue
        if LOCAL_PROBE.match(rel):
            problems.append(f"{rel}: seat-prefixed research probe is tracked")
        full = repo / rel
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
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
    repo = Path(__file__).resolve().parents[1]
    problems = inspect(repo, tracked_paths(repo))
    if problems:
        print("PUBLIC BOUNDARY: FAIL")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("PUBLIC BOUNDARY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
