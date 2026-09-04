"""Compute the certification subject for each thin shim.

The daemon/vault remains the authority. This tool is an independent diagnostic and CI
falsifier for the exact same subject: shim bytes plus the active common runtime set.

A raw shim hash is insufficient because the shim delegates every decision to the shared
gate. The certified subject is therefore:

    sha256(schema || criteria || api || shim bytes || runtime-name/runtime-bytes ...)

The runtime set is read from RUNTIME_MANIFEST.txt. There is no second hard-coded list.
Missing or unreadable inputs are errors, never an empty/clean result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

SCHEMA = "hestia-shim-cert/v1"
CRITERIA = "PRD_SHIM_CERTIFICATION.md@2026-09-04"
GATE_API = "decide/1"

_HOOK = "pre_" + "tool_" + "use.py"
_GEM = "before_" + "tool.py"
REPO_SHIMS = {
    "claude-code": ("claude-code", "hooks", _HOOK),
    "codex": ("codex", "hooks", _HOOK),
    "kimi": ("kimi", "hooks", _HOOK),
    "gemini": ("gemini", "hooks", _GEM),
}
DEPLOYED_SHIMS = {
    "claude-code": ("~", ".claude", "hooks", "hestia", _HOOK),
    "codex": ("~", ".codex", "hooks", _HOOK),
    "kimi": ("~", ".kimi-code", "hooks", _HOOK),
    "gemini": ("~", ".gemini", "hestia-plugins", "gemini", "hooks", _GEM),
}


class Unknown(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(os.getenv("HESTIA_REPO_ROOT") or Path(__file__).resolve().parents[1])


def hestia_home() -> Path:
    return Path(os.path.expanduser(os.getenv("HESTIA_HOME", "~/.hestia")))


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise Unknown(f"{path}: {type(exc).__name__}: {exc}") from exc


def runtime_names() -> tuple[str, ...]:
    manifest = repo_root() / "plugins" / "_shared" / "RUNTIME_MANIFEST.txt"
    try:
        names = tuple(
            line.strip() for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except OSError as exc:
        raise Unknown(f"cannot read runtime manifest {manifest}: {exc}") from exc
    if not names or len(set(names)) != len(names):
        raise Unknown("runtime manifest is empty or contains duplicate entries")
    return names


def shim_path(seat: str, deployed: bool) -> Path:
    parts = DEPLOYED_SHIMS[seat] if deployed else REPO_SHIMS[seat]
    if deployed:
        return Path(os.path.expanduser(os.path.join(*parts)))
    return repo_root() / "plugins" / Path(*parts)


def runtime_dir(deployed: bool) -> Path:
    return hestia_home() / "shared" if deployed else repo_root() / "plugins" / "_shared"


def difference_declaration(shim: bytes) -> str:
    text = shim.decode("utf-8", "replace")
    return "\n".join(
        line.strip() for line in text.splitlines() if "HARNESS-DIFFERENCE:" in line
    )


def certification(seat: str, deployed: bool) -> dict:
    shim_file = shim_path(seat, deployed)
    shim = read_bytes(shim_file)
    names = runtime_names()
    rdir = runtime_dir(deployed)
    runtime = [(name, read_bytes(rdir / name)) for name in names]

    h = hashlib.sha256()
    for scalar in (SCHEMA, CRITERIA, GATE_API):
        h.update(scalar.encode("utf-8")); h.update(b"\0")
    h.update(shim); h.update(b"\0")
    for name, payload in runtime:
        h.update(name.encode("utf-8")); h.update(b"\0")
        h.update(payload); h.update(b"\0")
    h.update(difference_declaration(shim).encode("utf-8")); h.update(b"\0")

    return {
        "seat": seat,
        "scope": "deployed" if deployed else "repo",
        "schema": SCHEMA,
        "criteria": CRITERIA,
        "gate_api": GATE_API,
        "certification_sha256": h.hexdigest(),
        "shim_path": str(shim_file),
        "shim_sha256_raw": hashlib.sha256(shim).hexdigest(),
        "runtime_dir": str(rdir),
        "runtime": {
            name: hashlib.sha256(payload).hexdigest() for name, payload in runtime
        },
        "difference_declaration": difference_declaration(shim),
    }


def cmd_preimage(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(certification(args.seat, args.deployed), indent=2, sort_keys=True))
        return 0
    except Unknown as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return 2


def cmd_report(_args: argparse.Namespace) -> int:
    rows = []
    failed = False
    for seat in REPO_SHIMS:
        try:
            expected = certification(seat, False)["certification_sha256"]
            actual = certification(seat, True)["certification_sha256"]
            verdict = "MATCHED" if expected == actual else "DRIFTED"
            detail = actual[:16] if verdict == "MATCHED" else (
                f"repo={expected[:12]} deployed={actual[:12]}"
            )
            failed |= verdict != "MATCHED"
        except Unknown as exc:
            verdict, detail, failed = "UNKNOWN", str(exc), True
        rows.append((seat, verdict, detail))

    width = max(map(len, REPO_SHIMS))
    print(f"{'seat':<{width}}  {'verdict':<9}  detail")
    for seat, verdict, detail in rows:
        print(f"{seat:<{width}}  {verdict:<9}  {detail}")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preimage")
    p.add_argument("--seat", required=True, choices=sorted(REPO_SHIMS))
    p.add_argument("--deployed", action="store_true")
    p.set_defaults(run=cmd_preimage)
    p = sub.add_parser("report")
    p.set_defaults(run=cmd_report)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
