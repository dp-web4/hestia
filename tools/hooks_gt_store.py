#!/usr/bin/env python3
"""The local hook ground-truth STORE: immutable, deduplicated, verified, and INERT.

docs/PRD_HOOK_GROUND_TRUTH.md, slice 2 (G3). dp: "install should create a local directory." GPT
(#1155 review): "slice 2 can proceed as inert storage work"; each certified member version must
bind its hook bytes, registration and exact shared-engine version, and "a global shared/current
flip must not change an older certified member silently".

WHAT IT HOLDS, under `$HESTIA_HOME/hooks-gt.store/`:

  blobs/<aa>/<digest>          every GT file, keyed by its CANONICAL digest (tools/hooks_gt.py's
                               rule), read-only. Identical bytes are stored once, whichever unit
                               or version they came from.
  closures/<unit>/<v>.json     one record per published unit version (`gt_version`, a content
                               address over the manifest): its files (path -> digest), its
                               registration, its ENGINE PIN (the _shared version + digests) and
                               its declared `requires`. Immutable: a record for a version that
                               already exists must be byte-identical, or ingest refuses.

WHAT IT DOES NOT DO -- by design, and each is a later slice:
  * no `current` link, and nothing reads this store to deploy, project, load or activate hooks
    (projection is slice 4);
  * a closure's presence here is NOT certification (slice 3): ingest records what was PUBLISHED,
    and the operator certifies a member's version separately;
  * nothing global moves. Two versions of a member, and two engine versions, coexist; resolving a
    member version always yields ITS pinned engine, never "the latest".

    HESTIA_HOME=... python3 tools/hooks_gt_store.py ingest --repo .     # refuses unless the GT holds
    HESTIA_HOME=... python3 tools/hooks_gt_store.py list
    HESTIA_HOME=... python3 tools/hooks_gt_store.py verify              # re-hash every blob + closure

`HESTIA_HOME` has no default (no hardcoded paths; #944): the store refuses to guess where it lives.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("hooks_gt", HERE / "hooks_gt.py")
hooks_gt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks_gt)

STORE = "hooks-gt.store"
INERT_NOTE = ("stored as PUBLISHED; presence here is not certification and nothing deploys from "
              "this store (PRD_HOOK_GROUND_TRUTH slices 3-4)")


class StoreError(Exception):
    pass


def store_root(home: str | os.PathLike | None) -> Path:
    if not home:
        raise StoreError("HESTIA_HOME is not set; the store has no default location, by design")
    return Path(home) / STORE


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".staging.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / digest[:2] / digest


def put_blob(root: Path, data: bytes) -> tuple[str, bool]:
    """Store `data` under its canonical digest. Returns (digest, written). An existing blob is
    re-verified before it is reused; one whose bytes no longer match its key is a corrupt store,
    which is refused, never silently kept or overwritten."""
    digest = hooks_gt.canonical_digest(data)
    p = blob_path(root, digest)
    if p.exists():
        if hooks_gt.canonical_digest(p.read_bytes()) != digest:
            raise StoreError(f"blob {digest[:12]} in the store no longer matches its digest -- the "
                             f"store is tampered or corrupt; refusing to reuse it")
        return digest, False
    _atomic_write(p, data, 0o444)
    return digest, True


def get_blob(root: Path, digest: str) -> bytes:
    """Read and RE-VERIFY. A blob that does not hash to its key is never returned."""
    p = blob_path(root, digest)
    try:
        data = p.read_bytes()
    except OSError as e:
        raise StoreError(f"blob {digest[:12]} is missing from the store ({e})")
    if hooks_gt.canonical_digest(data) != digest:
        raise StoreError(f"blob {digest[:12]} does not match its digest -- tampered or corrupt")
    return data


def closure_record(manifest: dict) -> dict:
    return {
        "unit": manifest["unit"],
        "member": manifest["member"],
        "gt_version": manifest["gt_version"],
        "registration": manifest["registration"],
        "files": {r["path"]: r["sha256"] for r in manifest["files"]},
        "sources": {r["path"]: r["source"] for r in manifest["files"]},
        "engine": manifest.get("engine"),
        "requires": manifest.get("requires") or [],
        "manifest": manifest,
        "note": INERT_NOTE,
    }


def _closure_bytes(rec: dict) -> bytes:
    return (json.dumps(rec, indent=2, sort_keys=True) + "\n").encode()


def ingest(repo: Path, home) -> dict:
    """Copy the repo's published GT into the store. Refused, writing NOTHING, unless the repo's
    GT holds under tools/hooks_gt.py check. Returns counts. Idempotent: a re-ingest of the same
    publication writes no blob and no closure."""
    root = store_root(home)
    findings = hooks_gt.check(repo)
    if findings:
        raise StoreError("the repo's ground truth does not hold; nothing was ingested:\n  "
                         + "\n  ".join(findings))
    gt = repo / hooks_gt.GT_DIR
    manifests = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
                 for p in sorted(gt.glob("*/manifest.json"))}
    written = reused = closures_new = 0
    # Blobs first, closures last: a closure is only ever written after every byte it names is
    # present and verified, so an interrupted ingest leaves blobs nobody references, never a
    # closure that points at nothing.
    for unit, m in manifests.items():
        for r in m["files"]:
            data = (gt / unit / r["path"]).read_bytes()
            digest, new = put_blob(root, data)
            if digest != r["sha256"]:
                raise StoreError(f"{unit}/{r['path']}: stored digest {digest[:12]} != manifest "
                                 f"{r['sha256'][:12]}")
            written += new
            reused += not new
    for unit, m in manifests.items():
        rec = closure_record(m)
        data = _closure_bytes(rec)
        p = root / "closures" / unit / f"{m['gt_version']}.json"
        if p.exists():
            if p.read_bytes() != data:
                raise StoreError(f"closure {unit}@{m['gt_version'][:12]} already exists with DIFFERENT "
                                 f"content -- closures are immutable; refusing")
            continue
        _atomic_write(p, data, 0o444)
        closures_new += 1
    return {"blobs_written": written, "blobs_reused": reused, "closures_written": closures_new,
            "units": sorted(manifests)}


def load_closure(root: Path, unit: str, version: str) -> dict:
    p = root / "closures" / unit / f"{version}.json"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoreError(f"closure {unit}@{version[:12]} is not in the store ({e})")
    # A closure is itself content-addressed through its manifest's gt_version.
    if hooks_gt._version(rec["manifest"]) != version or rec["gt_version"] != version:
        raise StoreError(f"closure {unit}@{version[:12]} does not match its own version -- tampered")
    return rec


def resolve(home, unit: str, version: str) -> dict[str, bytes]:
    """Everything this member version would execute, re-verified: its own files, ITS pinned engine
    (by version -- never the newest), and its declared requirements. Keys are `<unit>/<path>`.
    Nothing calls this to deploy yet; it is the read contract slice 4 will use."""
    root = store_root(home)
    rec = load_closure(root, unit, version)
    out = {f"{unit}/{path}": get_blob(root, d) for path, d in sorted(rec["files"].items())}
    pin = rec.get("engine")
    if pin:
        eng = load_closure(root, pin["unit"], pin["gt_version"])
        pinned = {f["path"]: f["sha256"] for f in pin["files"]}
        if pinned != eng["files"]:
            raise StoreError(f"{unit}@{version[:12]} pins engine {pin['gt_version'][:12]} with digests "
                             f"that disagree with that engine's own closure")
        for path, d in sorted(pinned.items()):
            out[f"{pin['unit']}/{path}"] = get_blob(root, d)
    for req in rec.get("requires") or []:
        out[f"{req['unit']}/{req['path']}"] = get_blob(root, req["sha256"])
    return out


def listing(home) -> list[dict]:
    root = store_root(home)
    rows = []
    for p in sorted((root / "closures").glob("*/*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        rows.append({"unit": rec["unit"], "member": rec["member"], "gt_version": rec["gt_version"],
                     "engine": (rec.get("engine") or {}).get("gt_version"),
                     "files": len(rec["files"])})
    return rows


def verify(home) -> list[str]:
    """Re-hash every blob and every closure; resolve every closure. Findings as sentences."""
    root = store_root(home)
    findings = []
    for p in sorted((root / "blobs").glob("*/*")):
        if hooks_gt.canonical_digest(p.read_bytes()) != p.name:
            findings.append(f"blob {p.name[:12]} does not match its digest")
    for row in listing(home):
        try:
            resolve(home, row["unit"], row["gt_version"])
        except StoreError as e:
            findings.append(str(e))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--repo", type=Path, default=HERE.parent)
    sub.add_parser("list")
    sub.add_parser("verify")
    a = ap.parse_args(argv)
    home = os.environ.get("HESTIA_HOME")
    try:
        if a.cmd == "ingest":
            print(json.dumps(ingest(a.repo, home), indent=2))
        elif a.cmd == "list":
            for r in listing(home):
                print(f"{r['unit']:12} {r['gt_version'][:12]}  engine {str(r['engine'])[:12]}  "
                      f"{r['files']} file(s)")
        else:
            f = verify(home)
            for x in f:
                print("FINDING", x)
            print(f"{len(f)} finding(s)" if f else "ok: every blob and closure verifies")
            return 1 if f else 0
    except StoreError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
