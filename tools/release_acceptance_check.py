#!/usr/bin/env python3
"""Read-only release acceptance: manifest, checksum metadata, tag and latest identity.

Uses authenticated gh GET requests. Downloads only the nine small checksum files,
not executable bundles. PASS establishes consistency with GitHub-reported asset
digests, NOT independent hashing of downloaded binaries or runtime compatibility.
No tag, release, installation, or local file is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess

from release_publish import manifest


def checksum_rows(data: bytes) -> dict[str, str]:
    rows = {}
    for line in data.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](\S+)", line)
        if not match:
            raise ValueError("malformed checksum row")
        digest, name = match.groups()
        if name in rows:
            raise ValueError("duplicate checksum row")
        rows[name] = digest
    return rows


def validate(release: dict, latest: dict, tag: str, expected_latest: str,
             checksums: dict[str, bytes]) -> dict:
    errors = []
    rc = re.fullmatch(r"v\d+\.\d+\.\d+-rc\.\d+", tag) is not None
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", tag):
        errors.append("unsupported release tag")
    if release.get("tag_name") != tag or release.get("draft") is not False:
        errors.append("requested tag is not a published release")
    if release.get("prerelease") is not rc:
        errors.append("prerelease flag does not match tag kind")
    if (latest.get("tag_name") != expected_latest
            or latest.get("draft") is not False
            or latest.get("prerelease") is not False):
        errors.append("latest differs from the expected stable release")
    if rc and latest.get("id") == release.get("id"):
        errors.append("RC is exposed as latest")
    if not rc and latest.get("id") != release.get("id"):
        errors.append("stable candidate is not latest")

    assets = release.get("assets", [])
    names = [a["name"] for a in assets]
    expected = manifest(tag)
    if sorted(names) != expected:
        errors.append("asset names differ from the exact 17-file manifest")
    by_name = {a["name"]: a for a in assets}
    for asset in assets:
        if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
            errors.append(f"empty or invalid asset size: {asset['name']}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or ""):
            errors.append(f"missing GitHub SHA256 digest: {asset['name']}")

    payload_names = [n for n in expected if n != "SHA256SUMS" and not n.endswith(".sha256")]
    checksum_names = {"SHA256SUMS", *(n + ".sha256" for n in payload_names)}
    if set(checksums) != checksum_names:
        errors.append("checksum downloads differ from the expected nine files")
    for name, data in checksums.items():
        asset = by_name.get(name, {})
        if len(data) != asset.get("size"):
            errors.append(f"checksum size mismatch: {name}")
        if "sha256:" + hashlib.sha256(data).hexdigest() != asset.get("digest"):
            errors.append(f"checksum digest mismatch: {name}")
    try:
        combined = checksum_rows(checksums.get("SHA256SUMS", b""))
        if set(combined) != set(payload_names):
            errors.append("SHA256SUMS does not enumerate exactly the eight bundles")
        for name in payload_names:
            rows = checksum_rows(checksums.get(name + ".sha256", b""))
            digest = combined.get(name)
            if digest is None or rows != {name: digest}:
                errors.append(f"sidecar disagrees with SHA256SUMS: {name}")
            if "sha256:" + (digest or "") != by_name.get(name, {}).get("digest"):
                errors.append(f"bundle metadata disagrees with SHA256SUMS: {name}")
    except (ValueError, UnicodeError) as exc:
        errors.append(str(exc))
    return {"tag": tag, "release_id": release.get("id"),
            "latest": latest.get("tag_name"), "asset_count": len(assets),
            "checksum_bytes_downloaded": sum(map(len, checksums.values())),
            "evidence": "checksum files hashed; bundle digests from GitHub metadata only",
            "pass": not errors, "errors": errors}


def get(endpoint: str, binary: bool = False) -> bytes:
    # Explicit GET even when callers change gh defaults; never invoke a mutation API.
    cmd = ["gh", "api", "--method", "GET", endpoint]
    if binary:
        cmd += ["-H", "Accept: application/octet-stream"]
    return subprocess.run(cmd, check=True, capture_output=True, timeout=45).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="dp-web4/hestia")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-latest", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("repo must be owner/name")
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", args.tag):
        parser.error("tag must be vX.Y.Z or vX.Y.Z-rc.N")
    prefix = f"repos/{args.repo}/releases"
    try:
        release = json.loads(get(f"{prefix}/tags/{args.tag}"))
        latest = json.loads(get(f"{prefix}/latest"))
        checksums = {}
        for asset in release.get("assets", []):
            name = asset["name"]
            if name in manifest(args.tag) and (name == "SHA256SUMS" or name.endswith(".sha256")):
                if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= 65536:
                    raise ValueError("checksum asset exceeds bounded download size")
                checksums[name] = get(f"{prefix}/assets/{int(asset['id'])}", binary=True)
        result = validate(release, latest, args.tag, args.expected_latest, checksums)
    except (ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"pass": False, "error": type(exc).__name__,
                          "evidence": "acceptance check incomplete"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
