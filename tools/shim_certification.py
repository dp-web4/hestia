#!/usr/bin/env python3
"""Certification preimage for a seat shim — compute, compare, and report drift.

Deliverables 5 and 6 of dp's 2026-09-04 request. This tool does NOT introduce a second
certification store: `vault::gate_integrity` already exists, already holds expectations in
the encrypted vault, already computes hashes daemon-side, and already rejects self-attested
hashes. This is the preimage calculator that feeds it, plus the drift report that consumes
it.

WHY A PREIMAGE AND NOT sha256(shim.py)
---------------------------------------
A shim delegates *all* governance to the common gate. Hashing only the shim permits the
absurd state GPT named on #934: a 140-line shim stays "certified" while the 480-line
decision engine underneath it is replaced. The certification must bind what was actually
reviewed:

    certification = sha256(
          criteria_version
        + exact shim bytes
        + exact common runtime set          <- the DEPLOYED tree, not the repo's
        + gate API version
        + justified harness-difference declaration
    )

One hash to verify, rather than a hash plus a side condition someone forgets to check.

THE DEPLOYED/REPO DISTINCTION IS LOAD-BEARING
----------------------------------------------
`--deployed` binds the copies that actually govern: the shim the harness config points at,
and the shared tree the shim's authority bootstrap resolves. Repo-vs-deployed is where
drift has historically hidden on this fleet, and a certification of the repo copy would
certify something no seat executes.

FAIL DIRECTION
--------------
Every unreadable input is a hard error. A preimage computed over a partially-read set would
be a hash of an unknown thing that looks exactly as authoritative as a hash of a known one.
Never "certify by absence".

Usage:
    shim_certification.py preimage --seat claude-code [--deployed]
    shim_certification.py report [--deployed]        # all seats, drift table
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

CRITERIA_VERSION = "PRD_SHIM_CERTIFICATION.md@2026-09-04"
GATE_API_VERSION = "decide/1"

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

# The common runtime set: every module whose bytes can change a decision. Bind ALL of them,
# because binding a subset means the unbound remainder can change under a green
# certification — the exact defect the preimage exists to prevent, one level down.
RUNTIME_SET = (
    "hestia_single_gate.py",
    "hestia_gate_core.py",
    "hestia_gate_mechanism.py",
    "hestia_governance_closure.py",
    "hestia_shell_classifier.py",
)


class Missing(Exception):
    pass


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Missing(f"{path}: {exc.__class__.__name__}: {exc}") from exc


def _repo_root() -> str:
    # Overridable so CI (and a reviewer checking a branch) can point at an alternate tree.
    # Deliberately affects the REPO side only: the deployed side must stay anchored to the
    # real installed locations, or "deployed" would stop meaning deployed.
    return os.getenv("HESTIA_REPO_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))


def _shim_path(seat: str, deployed: bool) -> str:
    if deployed:
        return os.path.expanduser(os.path.join(*DEPLOYED_SHIMS[seat]))
    return os.path.join(_repo_root(), "plugins", *REPO_SHIMS[seat])


def _runtime_dir(deployed: bool) -> str:
    if deployed:
        return os.path.expanduser(os.path.join("~", ".hestia", "shared"))
    return os.path.join(_repo_root(), "plugins", "_shared")


def _difference_declaration(seat: str, shim_src: bytes) -> str:
    """The justified harness-difference declaration, read from the shim's own header.

    C10 requires each permitted difference to be justified in the shim header, and §3.1
    requires the digest to cover comments for exactly this reason: the justification is
    part of what was certified. Absence is not an error — a seat with no declared
    difference contributes the empty string — but a CHANGE to it changes the preimage.
    """
    text = shim_src.decode("utf-8", "replace")
    marker = "HARNESS-DIFFERENCE:"
    lines = [ln.strip() for ln in text.split("\n") if marker in ln]
    return "\n".join(lines)


def preimage(seat: str, deployed: bool) -> dict:
    shim_path = _shim_path(seat, deployed)
    shim = _read(shim_path)

    rt_dir = _runtime_dir(deployed)
    runtime = {}
    for name in RUNTIME_SET:
        runtime[name] = _read(os.path.join(rt_dir, name))

    decl = _difference_declaration(seat, shim)

    h = hashlib.sha256()
    h.update(CRITERIA_VERSION.encode())
    h.update(b"\x00")
    h.update(shim)
    h.update(b"\x00")
    for name in RUNTIME_SET:               # fixed order: the tuple, not dict iteration
        h.update(name.encode())
        h.update(b"\x00")
        h.update(runtime[name])
        h.update(b"\x00")
    h.update(GATE_API_VERSION.encode())
    h.update(b"\x00")
    h.update(decl.encode())

    return {
        "seat": seat,
        "scope": "deployed" if deployed else "repo",
        "certification": h.hexdigest(),
        "criteria_version": CRITERIA_VERSION,
        "gate_api_version": GATE_API_VERSION,
        "shim_path": shim_path,
        "shim_sha256_raw": hashlib.sha256(shim).hexdigest(),
        "runtime_dir": rt_dir,
        "runtime_sha256": {n: hashlib.sha256(b).hexdigest()[:16] for n, b in runtime.items()},
        "difference_declaration": decl,
    }


def cmd_preimage(args) -> int:
    try:
        print(json.dumps(preimage(args.seat, args.deployed), indent=2))
    except Missing as exc:
        print(f"ERROR (fail-closed, not 'certified by absence'): {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_report(args) -> int:
    """Drift table. Verdicts deliberately mirror gate_integrity's vocabulary, plus DRIFTED.

    DRIFTED is not MISWIRED. A miswired shim reads as governed and is not. A drifted shim
    IS governed — by code nobody certified. Conflating them loses the distinction the
    agent-inventory README already insists on for the miswired case.
    """
    rows, rc = [], 0
    for seat in REPO_SHIMS:
        try:
            repo = preimage(seat, False)["certification"]
        except Missing as exc:
            rows.append((seat, "UNREADABLE", str(exc)[:48])); rc = 1; continue
        try:
            dep = preimage(seat, True)["certification"]
        except Missing as exc:
            rows.append((seat, "MISSING", str(exc)[:48])); rc = 1; continue
        if repo == dep:
            rows.append((seat, "MATCHED", dep[:16]))
        else:
            rows.append((seat, "DRIFTED", f"repo={repo[:12]} deployed={dep[:12]}"))
            rc = 1

    width = max(len(s) for s in REPO_SHIMS)
    print(f"{'seat':<{width}}  {'verdict':<11}  detail")
    print("-" * (width + 60))
    for seat, verdict, detail in rows:
        print(f"{seat:<{width}}  {verdict:<11}  {detail}")
    print()
    print("MATCHED    deployed preimage equals the repo preimage")
    print("DRIFTED    deployed governs with code whose certification differs")
    print("MISSING    no deployed artifact — the seat is not governed by what was certified")
    print("UNREADABLE could not look; never reported as certified")
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("preimage", help="compute one seat's certification preimage")
    a.add_argument("--seat", required=True, choices=sorted(REPO_SHIMS))
    a.add_argument("--deployed", action="store_true", help="bind the deployed copies")
    a.set_defaults(fn=cmd_preimage)

    b = sub.add_parser("report", help="repo-vs-deployed drift table for every seat")
    b.add_argument("--deployed", action="store_true", help="(accepted; report always compares both)")
    b.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
