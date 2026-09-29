#!/usr/bin/env python3
"""Hook ground truth (GT): publish the tested hooks into `hooks-gt/`, and check that they still hold.

docs/PRD_HOOK_GROUND_TRUTH.md, slice 1 (G1, G2). dp, 2026-09-28: *"the hestia repo needs to have a
directory with tested and maintained hooks for supported harnesses. those are the ground truth ...
when hook is published to the repo its sha should be in the comment and metadata"* and *"two copies
are the redundancy check."*

LAYOUT. `hooks-gt/<unit>/` for each harness plugin (claude-code, codex, gemini, kimi) plus `_shared`
(the decision engine every gate imports, one artifact with the hooks per #481). Each unit holds:
  - the published copy of every file the member installs (its `expects.json` install.files), or
    for `_shared` every module in RUNTIME_MANIFEST.txt, at the same relative path;
  - the registration template (`hooks/hooks.json`) when the member ships one -- the registration
    EDGE is ground truth too (the Discover bypass changed only that edge, and #1156 measured that
    nothing saw it);
  - `manifest.json`: member, per-file canonical sha256, the source path it was published from, and
    `gt_version` (content-addressed over the file list).

THE DIGEST RULE. A file cannot contain its own hash, so the canonical digest of a GT file is sha256
over its bytes with the value on its `hestia-gt-sha256:` header line replaced by 64 zeros. JSON has
no comments, so a JSON file carries no header and its digest is plain sha256. The manifest is the
authority; the header is the human-readable copy, and a header that disagrees with the manifest is a
finding in its own right.

THE REDUNDANCY CHECK. `plugins/<member>/` stays the working source. A GT file with its header line
removed must equal its source byte for byte; a difference is an UNPUBLISHED change (someone edited
the source without re-publishing, or the GT copy was edited in place). CI runs `check`.

    python3 tools/hooks_gt.py check                  # exit 1 on any finding
    python3 tools/hooks_gt.py publish --emit-patch P # write the GT tree as ONE patch to P

`publish` never writes the tree itself. GT files carry gate names (pre_tool_use.py ...), which are
governance markers: landing them is a governed act, and it should be one reviewable `git apply`,
not a script writing gate-named files past the gate.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT_DIR = "hooks-gt"
HEADER_KEY = "hestia-gt-sha256:"
ZERO = "0" * 64
_HEADER_RE = re.compile(r"^(#\s*" + re.escape(HEADER_KEY) + r"\s*)([0-9a-f]{64})(.*)$")
DIGEST_RULE = ("sha256 over the file bytes with the 64-hex value on its `hestia-gt-sha256:` header "
               "line replaced by 64 zeros; files without a header (JSON) are plain sha256")


def canonical_digest(data: bytes) -> str:
    lines = data.decode("utf-8", "surrogateescape").split("\n")
    out = []
    for ln in lines:
        m = _HEADER_RE.match(ln)
        out.append(m.group(1) + ZERO + m.group(3) if m else ln)
    return hashlib.sha256("\n".join(out).encode("utf-8", "surrogateescape")).hexdigest()


def header_value(data: bytes) -> str | None:
    for ln in data.decode("utf-8", "surrogateescape").split("\n"):
        m = _HEADER_RE.match(ln)
        if m:
            return m.group(2)
    return None


def strip_header(data: bytes) -> bytes:
    """The GT file as its source had it: the header line removed."""
    lines = data.decode("utf-8", "surrogateescape").split("\n")
    kept = [ln for ln in lines if not _HEADER_RE.match(ln)]
    return "\n".join(kept).encode("utf-8", "surrogateescape")


def with_header(src: bytes, rel: str) -> bytes:
    """Insert the header after a shebang (or at the top); JSON gets none."""
    if rel.endswith(".json"):
        return src
    text = src.decode("utf-8", "surrogateescape")
    line = f"# {HEADER_KEY} {ZERO}  (published ground truth; manifest: {GT_DIR})"
    lines = text.split("\n")
    at = 1 if lines and lines[0].startswith("#!") else 0
    lines.insert(at, line)
    placeholder = "\n".join(lines).encode("utf-8", "surrogateescape")
    digest = canonical_digest(placeholder)
    return placeholder.replace(ZERO.encode(), digest.encode(), 1)


def units(root: Path = ROOT) -> dict[str, dict]:
    """{unit: {member, files: {gt_rel: source_rel}, registration, requires}} from the declarations,
    never a glob. `requires` is the member's declared cross-unit dependency (install.requires:
    ["<unit>/<path>", ...]) -- gemini's gate runs claude-code's gate as its governor."""
    out: dict[str, dict] = {}
    for exp in sorted((root / "plugins").glob("*/expects.json")):
        d = exp.parent.name
        spec = json.loads(exp.read_text(encoding="utf-8"))
        inst = spec.get("install") or {}
        files = {rel: f"plugins/{d}/{rel}" for rel in inst.get("files") or []}
        tmpl = exp.parent / "hooks" / "hooks.json"
        if tmpl.is_file():
            files["hooks/hooks.json"] = f"plugins/{d}/hooks/hooks.json"
        out[d] = {"member": inst.get("member") or d, "files": files,
                  "registration": "hooks/hooks.json" if tmpl.is_file() else None,
                  "requires": sorted(inst.get("requires") or [])}
    man = root / "plugins" / "_shared" / "RUNTIME_MANIFEST.txt"
    names = [ln.strip() for ln in man.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    out["_shared"] = {"member": None, "files": {n: f"plugins/_shared/{n}" for n in names},
                      "registration": None, "requires": []}
    return out


def _version(body: dict) -> str:
    """Content address of a manifest: sha256 over its canonical JSON WITHOUT `gt_version`. Every
    field is covered -- identity, registration, rows, the engine pin, requires -- so a manifest
    whose metadata was edited no longer matches its own version."""
    b = {k: v for k, v in body.items() if k != "gt_version"}
    return hashlib.sha256(json.dumps(b, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def manifest_for(unit: str, u: dict, digests: dict[str, str], engine: dict | None,
                 requires: list[dict]) -> dict:
    """The ONE composition of a unit's manifest, used by publish and by check alike.

    A MEMBER'S CERTIFIED CLOSURE (#1160 review): a member's version must identify its whole
    decision behaviour, so it binds the exact shared engine it runs (`engine`: the _shared
    version and every engine file digest) and every cross-unit file it executes (`requires`).
    Change the engine and every member's version changes; certify a member and you have certified
    the engine bytes it will resolve. Members still move independently: two members may pin
    different engine versions, and the store deduplicates identical blobs."""
    rows = [{"path": rel, "sha256": digests[rel], "source": src}
            for rel, src in sorted(u["files"].items())]
    body = {
        "unit": unit,
        "member": u["member"],
        "digest_rule": DIGEST_RULE,
        "registration": u["registration"],
        "registration_note": (None if u["registration"] or unit == "_shared" else
                              "this member ships no registration template yet; its registration "
                              "edge is NOT ground truth until it does"),
        "files": rows,
        "engine": engine,
        "requires": requires,
    }
    body["gt_version"] = _version(body)
    return body


def _engine_pin(shared_manifest: dict) -> dict:
    return {"unit": "_shared", "gt_version": shared_manifest["gt_version"],
            "files": [{"path": r["path"], "sha256": r["sha256"]} for r in shared_manifest["files"]]}


def _compose(root: Path, digest_of) -> dict[str, dict]:
    """Every unit's manifest, engine first, from a digest source (`digest_of(unit, rel)`)."""
    decl = units(root)
    out: dict[str, dict] = {}
    shared = decl["_shared"]
    out["_shared"] = manifest_for("_shared", shared,
                                  {rel: digest_of("_shared", rel) for rel in shared["files"]}, None, [])
    pin = _engine_pin(out["_shared"])
    for unit, u in decl.items():
        if unit == "_shared":
            continue
        reqs = []
        for ref in u["requires"]:
            runit, _, rrel = ref.partition("/")
            reqs.append({"unit": runit, "path": rrel, "sha256": digest_of(runit, rrel)})
        out[unit] = manifest_for(unit, u, {rel: digest_of(unit, rel) for rel in u["files"]}, pin, reqs)
    return out


def build(root: Path = ROOT) -> dict[str, bytes]:
    """{repo-relative path: bytes} for the whole GT tree as it should be published now."""
    decl = units(root)
    tree: dict[str, bytes] = {}
    for unit, u in decl.items():
        for gt_rel, src_rel in u["files"].items():
            tree[f"{GT_DIR}/{unit}/{gt_rel}"] = with_header((root / src_rel).read_bytes(), gt_rel)

    def digest_of(unit, rel):
        return canonical_digest(tree[f"{GT_DIR}/{unit}/{rel}"])

    for unit, m in _compose(root, digest_of).items():
        tree[f"{GT_DIR}/{unit}/manifest.json"] = (json.dumps(m, indent=2) + "\n").encode()
    return tree


def check(root: Path = ROOT) -> list[str]:
    """Every finding, as a sentence. Empty means the GT holds.

    The manifest is VERIFIED, not trusted (#1160 review): the expected manifest is recomputed from
    the declarations and the GT files' own digests, and the one on disk must equal it exactly --
    identity, registration, sources, rows (no duplicates), engine pin, requires, and version.
    Files on disk that no manifest names are findings too."""
    findings: list[str] = []
    gt = root / GT_DIR
    if not gt.is_dir():
        return [f"{GT_DIR}/ does not exist: nothing is published"]
    declared = units(root)
    on_disk = {p.name for p in gt.iterdir() if p.is_dir()}
    for unit in sorted(on_disk - set(declared)):
        findings.append(f"{unit}: published in {GT_DIR}/ but no longer declared by any plugin")

    def digest_of(unit, rel):
        f = gt / unit / rel
        return canonical_digest(f.read_bytes()) if f.is_file() else "missing"

    expected = _compose(root, digest_of)
    for unit in sorted(declared):
        mpath = gt / unit / "manifest.json"
        if not mpath.is_file():
            findings.append(f"{unit}: declared but never published (no {GT_DIR}/{unit}/manifest.json)")
            continue
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except ValueError as e:
            findings.append(f"{unit}: manifest.json is not JSON ({e})")
            continue
        rows = m.get("files") or []
        paths = [r.get("path") for r in rows]
        for dup in sorted({p for p in paths if paths.count(p) > 1}):
            findings.append(f"{unit}/{dup}: listed more than once in the manifest")
        exp = expected[unit]
        # Per-file checks first: they name the file, which is what a reader needs.
        want = declared[unit]["files"]
        pub = {r.get("path"): r for r in rows}
        for gt_rel in sorted(set(pub) | set(want)):
            if gt_rel not in pub:
                findings.append(f"{unit}/{gt_rel}: declared by the plugin but not in the published manifest")
                continue
            if gt_rel not in want:
                findings.append(f"{unit}/{gt_rel}: published but no longer declared by the plugin")
                continue
            f = gt / unit / gt_rel
            if not f.is_file():
                findings.append(f"{unit}/{gt_rel}: in the manifest but the GT file is missing")
                continue
            data = f.read_bytes()
            digest = canonical_digest(data)
            if digest != pub[gt_rel].get("sha256"):
                findings.append(f"{unit}/{gt_rel}: GT file does not match its published sha "
                                f"(manifest {str(pub[gt_rel].get('sha256'))[:12]}, file {digest[:12]}) -- MISWIRED")
            hv = header_value(data)
            if not gt_rel.endswith(".json") and hv != pub[gt_rel].get("sha256"):
                findings.append(f"{unit}/{gt_rel}: header sha {str(hv)[:12]} disagrees with the "
                                f"manifest {str(pub[gt_rel].get('sha256'))[:12]}")
            src = root / want[gt_rel]
            if not src.is_file():
                findings.append(f"{unit}/{gt_rel}: its source {want[gt_rel]} is gone")
            elif strip_header(data) != src.read_bytes():
                findings.append(f"{unit}/{gt_rel}: UNPUBLISHED change -- {want[gt_rel]} differs from "
                                f"its published ground truth; re-publish (tools/hooks_gt.py publish)")
        # Then the whole-manifest contract: every field, exactly.
        for key in sorted(set(exp) | set(m)):
            if key in ("files",):
                if [{k: r.get(k) for k in ("path", "sha256", "source")} for r in rows] != exp["files"]:
                    if not any(x.startswith(f"{unit}/") for x in findings):
                        findings.append(f"{unit}: manifest file rows differ from the declared, digested set")
                continue
            if m.get(key) != exp.get(key):
                findings.append(f"{unit}: manifest `{key}` is {json.dumps(m.get(key))[:80]}, "
                                f"expected {json.dumps(exp.get(key))[:80]}")
        # Files on disk that no manifest names.
        listed = {str(Path(p)) for p in paths} | {"manifest.json"}
        for f in sorted((gt / unit).rglob("*")):
            if f.is_file() and str(f.relative_to(gt / unit)) not in listed:
                findings.append(f"{unit}/{f.relative_to(gt / unit)}: on disk but in no manifest")
    return findings


def emit_patch(root: Path, out: Path) -> int:
    """The GT tree as one unified patch against the working tree (new, changed and removed files)."""
    tree = build(root)
    gt = root / GT_DIR
    existing = {str(p.relative_to(root)) for p in gt.rglob("*") if p.is_file()} if gt.is_dir() else set()
    chunks = []
    for rel in sorted(set(tree) | existing):
        new = tree.get(rel)
        p = root / rel
        old = p.read_bytes() if p.is_file() else None
        if old == new:
            continue
        a = [] if old is None else old.decode("utf-8", "surrogateescape").splitlines(True)
        b = [] if new is None else new.decode("utf-8", "surrogateescape").splitlines(True)
        hdr = f"diff --git a/{rel} b/{rel}\n"
        if old is None:
            src = new.startswith(b"#!")
            hdr += f"new file mode {'100755' if src else '100644'}\n"
        elif new is None:
            hdr += "deleted file mode 100644\n"
        d = list(difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{rel}",
                                      "/dev/null" if new is None else f"b/{rel}"))
        for i, ln in enumerate(d):
            if not ln.endswith("\n"):
                d[i] = ln + "\n\\ No newline at end of file\n"
        chunks.append(hdr + "".join(d))
    out.write_text("".join(chunks), encoding="utf-8", errors="surrogateescape")
    return len(chunks)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("publish")
    p.add_argument("--emit-patch", required=True, type=Path)
    p.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        f = check()
        for x in f:
            print("FINDING", x)
        print(f"{len(f)} finding(s)" if f else "ok: every published hook matches its sha and its source")
        return 1 if f else 0
    n = emit_patch(a.root, a.emit_patch)
    print(f"{n} file change(s) -> {a.emit_patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
