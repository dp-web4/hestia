"""Compute the certification subject for each thin shim.

The daemon/vault remains the authority. This tool is an independent diagnostic and CI
falsifier for the exact same subject: shim bytes plus the active common runtime set.

A raw shim hash is insufficient because the shim delegates every decision to the shared
gate. The certified subject is therefore:

    sha256(schema || criteria-label || criteria-BYTES || api || shim bytes
           || runtime-name/runtime-bytes ...)

The criteria enter as the hash of the normative document's contents, not as the label
naming it: the label is hand-maintained and has already failed to move when the criteria
did.

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
from typing import Optional

# The certification scalars are NOT redeclared here. They are read out of the canonical
# template, which is the artifact the criteria are about, so this tool cannot certify
# against a schema/criteria/API the template does not actually claim. Re-typing them was a
# third copy of the same three strings (template, shim, tool) with nothing keeping them
# equal -- the identical shape as the enumeration drift the PRD documents about itself.
_TEMPLATE_SCALARS = {
    "SCHEMA": "SHIM_CERTIFICATION_SCHEMA",
    "CRITERIA": "CERTIFICATION_CRITERIA",
    "GATE_API": "REQUIRED_GATE_API",
}


def canonical_criteria() -> tuple:
    """The criteria the digest actually commits to: (label, path, bytes).

    Hashing the LABEL alone was a hole. `CERTIFICATION_CRITERIA` is a hand-maintained
    string, and on 2026-09-22 the criteria it names changed four times in one day -- the
    permitted-function names, their byte-identical/adapter kinds, C4's 5/3 split and its
    worked example -- while the label stayed `...@2026-09-04` and every certification digest
    stayed byte-for-byte identical. A certification that survives a material change to the
    standard it certifies against is not evidence of anything.

    The PRD's own formula is `sha256(criteria_version + shim bytes + runtime set + gate API
    version + justified difference declaration)`, and its vault record carries a
    `criteria_version` field. A hand-typed label is a criteria *name*; a version has to
    follow the contents. The label's filename must resolve under `docs/`, and the file's
    bytes are what enter the preimage.
    """
    label = canonical_scalars()["CRITERIA"]
    filename = str(label).split("@", 1)[0].strip()
    if not filename:
        raise Unknown(f"CERTIFICATION_CRITERIA {label!r} names no document before '@'")
    path = repo_root() / "docs" / filename
    return label, path, read_bytes(path)


def canonical_scalars() -> dict:
    """Read the three certification scalars from the template by parsing it.

    Parsed, not imported: the template is a reference artifact that expects a harness
    around it, and importing it to read three constants would run its module body.
    """
    import ast

    path = repo_root() / "plugins" / "_template" / "shim_template.py"
    try:
        tree = ast.parse(read_bytes(path).decode("utf-8"))
    except SyntaxError as exc:
        raise Unknown(f"canonical template {path} does not parse: {exc}") from exc
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, "id", None)
            for key, want in _TEMPLATE_SCALARS.items():
                if name == want and isinstance(node.value, ast.Constant):
                    found[key] = node.value.value
    missing = sorted(set(_TEMPLATE_SCALARS) - set(found))
    if missing:
        raise Unknown(f"canonical template {path} declares no "
                      f"{', '.join(_TEMPLATE_SCALARS[m] for m in missing)}")
    return found

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


_HOME_OVERRIDE: Optional[str] = None


def hestia_home() -> Path:
    """The installation root to verify against. THERE IS NO DEFAULT.

    A verifier that guesses `~/.hestia` when HESTIA_HOME is unset can certify a tree
    nobody asked about and report MATCHED for it. That is worse than the same defect in a
    seat (#944, "there is no default, by design"), because the whole product of this tool
    is the claim that a specific installation is the certified one. Unset is UNKNOWN, and
    UNKNOWN is a result: `report` exits non-zero rather than inventing a root.

    This PRD names the hazard in its own drift table -- "which home | `$HESTIA_HOME`,
    default `~/.hestia` | hardcoded `~`" -- and this function used to be an instance of it.
    """
    home = _HOME_OVERRIDE or os.getenv("HESTIA_HOME")
    if not home:
        raise Unknown("HESTIA_HOME is not set and --home was not given; refusing to guess "
                      "an installation root (there is no default, by design). Pass --home "
                      "or export HESTIA_HOME.")
    return Path(os.path.expanduser(home))


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
    scalars = canonical_scalars()
    crit_label, crit_path, crit_bytes = canonical_criteria()
    crit_digest = hashlib.sha256(crit_bytes).hexdigest()
    for scalar in (scalars["SCHEMA"], crit_label, crit_digest, scalars["GATE_API"]):
        h.update(scalar.encode("utf-8")); h.update(b"\0")
    h.update(shim); h.update(b"\0")
    for name, payload in runtime:
        h.update(name.encode("utf-8")); h.update(b"\0")
        h.update(payload); h.update(b"\0")
    h.update(difference_declaration(shim).encode("utf-8")); h.update(b"\0")

    return {
        "seat": seat,
        "scope": "deployed" if deployed else "repo",
        "schema": scalars["SCHEMA"],
        "criteria": crit_label,
        "criteria_sha256": crit_digest,
        "criteria_path": str(crit_path),
        "gate_api": scalars["GATE_API"],
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
    global _HOME_OVERRIDE
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=None,
                        help="installation root to verify (else $HESTIA_HOME; there is no "
                             "default — an unset root is UNKNOWN, not a guess)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preimage")
    p.add_argument("--seat", required=True, choices=sorted(REPO_SHIMS))
    p.add_argument("--deployed", action="store_true")
    p.set_defaults(run=cmd_preimage)
    p = sub.add_parser("report")
    p.set_defaults(run=cmd_report)
    args = parser.parse_args(argv)
    _HOME_OVERRIDE = args.home
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
