#!/usr/bin/env python3
"""Fail when installation-local state or authority enters the public tree.

This is a source-boundary check, not a secret scanner for Git history.  It keeps
runtime evidence, operator discussion, worktrees, local scope derivation and
host-specific wiring out of new commits.  Historical credential review is a
separate release process because deleting a current file does not erase a blob.
"""
from __future__ import annotations

import argparse
import hashlib
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
REGULAR_MODES = {"100644", "100755"}
BINARY_MANIFEST = "tools/public_binary_assets.sha256"


def tracked_paths(repo: Path) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def tracked_modes(repo: Path) -> dict[str, str]:
    raw = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=repo)
    modes: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, _object_id, stage = metadata.split()
        rel = path.decode("utf-8", "surrogateescape")
        modes[rel] = mode.decode() if stage == b"0" else f"unmerged-stage-{stage.decode()}"
    return modes


def is_test(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return ("tests" in parts or name.startswith("test_")
            or name.endswith(("_test.py", "_test.sh")))


def cached_blobs(repo: Path, paths: list[str]) -> dict[str, bytes]:
    """Read index blobs in one Git process rather than one process per path."""
    request = b"".join(
        b":" + rel.encode("utf-8", "surrogateescape") + b"\0" for rel in paths
    )
    proc = subprocess.run(
        ["git", "cat-file", "--batch", "-Z"], cwd=repo, input=request,
        capture_output=True, check=True,
    )
    stream = io.BytesIO(proc.stdout)
    result: dict[str, bytes] = {}
    for rel in paths:
        header_bytes = bytearray()
        while True:
            byte = stream.read(1)
            if byte == b"\0":
                break
            if not byte:
                raise RuntimeError(f"truncated git cat-file header for {rel!r}")
            header_bytes.extend(byte)
        header = bytes(header_bytes)
        if header.endswith(b" missing"):
            continue
        fields = header.split()
        if len(fields) != 3:
            raise RuntimeError(f"unexpected git cat-file header for {rel}: {header!r}")
        size = int(fields[2])
        raw = stream.read(size)
        if stream.read(1) != b"\0":
            raise RuntimeError(f"missing git cat-file delimiter after {rel}")
        result[rel] = raw
    return result


def worktree_blob(repo: Path, rel: str) -> bytes | None:
    full = repo / rel
    if not full.is_file():
        return None
    try:
        return full.read_bytes()
    except OSError:
        return None


def parse_binary_manifest(raw: bytes) -> tuple[dict[str, str], list[str]]:
    entries: dict[str, str] = {}
    problems: list[str] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {}, [f"{BINARY_MANIFEST}: manifest is not UTF-8 text"]
    ordered: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            problems.append(f"{BINARY_MANIFEST}:{number}: malformed manifest row")
            continue
        digest, rel = match.groups()
        if rel in entries:
            problems.append(f"{BINARY_MANIFEST}:{number}: duplicate path {rel}")
            continue
        entries[rel] = digest
        ordered.append(rel)
    if ordered != sorted(ordered):
        problems.append(f"{BINARY_MANIFEST}: paths are not sorted")
    return entries, problems


def inspect(repo: Path, paths: list[str], *, cached: bool = False,
            modes: dict[str, str] | None = None) -> list[str]:
    problems: list[str] = []
    index = cached_blobs(repo, paths) if cached else {}
    modes = modes or {}
    path_set = set(paths)

    def blob(rel: str) -> bytes | None:
        return index.get(rel) if cached else worktree_blob(repo, rel)

    manifest: dict[str, str] = {}
    if BINARY_MANIFEST in path_set:
        manifest_raw = blob(BINARY_MANIFEST)
        if manifest_raw is None:
            problems.append(f"{BINARY_MANIFEST}: tracked manifest is unreadable")
        else:
            manifest, manifest_problems = parse_binary_manifest(manifest_raw)
            problems.extend(manifest_problems)
    for rel in paths:
        if rel.startswith(FORBIDDEN_ROOTS):
            problems.append(f"{rel}: installation-local root is tracked")
            continue
        if LOCAL_PROBE.match(rel):
            problems.append(f"{rel}: seat-prefixed research probe is tracked")
        mode = modes.get(rel)
        if mode is not None and mode not in REGULAR_MODES:
            problems.append(f"{rel}: tracked mode {mode} is not a regular file")
            continue
        if not cached and (repo / rel).is_symlink():
            problems.append(f"{rel}: worktree path is a symlink")
            continue
        raw = blob(rel)
        if raw is None:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            actual = hashlib.sha256(raw).hexdigest()
            expected = manifest.get(rel)
            if expected is None:
                problems.append(f"{rel}: non-text blob is absent from reviewed manifest")
            elif expected != actual:
                problems.append(f"{rel}: non-text blob changed without manifest review")
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

    for rel, expected in manifest.items():
        if rel not in path_set:
            problems.append(f"{BINARY_MANIFEST}: untracked or missing asset {rel}")
            continue
        raw = blob(rel)
        if raw is None:
            problems.append(f"{BINARY_MANIFEST}: unreadable asset {rel}")
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            problems.append(f"{BINARY_MANIFEST}: listed asset is text {rel}")
        if hashlib.sha256(raw).hexdigest() != expected:
            problems.append(f"{rel}: non-text blob changed without manifest review")

    return sorted(set(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cached", action="store_true",
        help="inspect the staged index exactly (for a composable pre-commit check)",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    problems = inspect(
        repo, tracked_paths(repo), cached=args.cached, modes=tracked_modes(repo),
    )
    if problems:
        print("PUBLIC BOUNDARY: FAIL")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("PUBLIC BOUNDARY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
