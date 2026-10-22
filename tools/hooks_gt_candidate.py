"""Read-only certification preflight: exact member version, never installed bytes.

This emits an UNCERTIFIED candidate, not a vault record or authorization. No
caller may project hooks from it. See docs/HOOK_CERTIFICATION_PREFLIGHT.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

_spec = importlib.util.spec_from_file_location("hooks_gt", Path(__file__).with_name("hooks_gt.py"))
gt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gt)

MAX_FILE = 8 << 20
MAX_MANIFEST = 1 << 20
MAX_TOTAL = 64 << 20
MAX_FILES = 256
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_UNIT = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")


class CandidateError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise CandidateError(message)


def digest(value):
    require(isinstance(value, str) and _HEX.fullmatch(value), "invalid digest/version")
    return value


def unit(value):
    require(isinstance(value, str) and _UNIT.fullmatch(value), "invalid unit/member")
    return value


def relative(value):
    require(isinstance(value, str) and 0 < len(value) <= 512, "invalid relative path")
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value) and "\\" not in value,
            "invalid path characters")
    require(all(p not in ("", ".", "..") for p in value.split("/")), "noncanonical relative path")
    return value


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, "duplicate JSON key")
        out[key] = value
    return out


def parse(data):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: require(False, "nonfinite JSON number"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CandidateError("invalid or ambiguous JSON") from exc


class Reader:
    """Descriptor-relative, regular-file-only reads under an explicitly chosen store.

    Refuses symlinks below and at the store root, but does not authenticate its
    ancestors or provide a transactional snapshot against a same-UID adversary.
    """
    def __init__(self, root):
        self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.remaining = MAX_TOTAL

    def close(self):
        os.close(self.fd)

    def read(self, rel, limit=MAX_FILE):
        parts = relative(rel).split("/")
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            named = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            require(stat.S_ISREG(named.st_mode), "store object is not a regular file")
            child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            os.close(fd)
            fd = child
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode), "store object is not a regular file")
            require((named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
                    "store object replaced before open")
            cap = min(limit, self.remaining)
            require(before.st_size <= cap, "store object exceeds read budget")
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, cap + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                require(size <= cap, "store object grew beyond read budget")
            after = os.fstat(fd)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            require(signature(before) == signature(after), "store object changed during read")
            self.remaining -= size
            return b"".join(chunks)
        finally:
            os.close(fd)


def rows(value, *, sources=False, owner=None):
    require(isinstance(value, list) and 0 < len(value) <= MAX_FILES, "invalid file rows")
    out = {}
    for row in value:
        require(isinstance(row, dict) and set(row) == (
            {"path", "sha256", "source"} if sources else {"path", "sha256"}), "invalid file row")
        path = relative(row["path"])
        require(path not in out, "duplicate file path")
        if sources:
            require(row["source"] == f"plugins/{owner}/{path}", "unexpected source identity")
        out[path] = digest(row["sha256"])
    return out


def manifest(reader, name, version):
    data = reader.read(f"closures/{unit(name)}/{digest(version)}.json", MAX_MANIFEST)
    record = parse(data)
    require(isinstance(record, dict) and set(record) == {"manifest", "note"}, "invalid closure record")
    m = record["manifest"]
    require(isinstance(m, dict) and set(m) == {
        "unit", "member", "digest_rule", "registration", "registration_note",
        "files", "engine", "requires", "gt_version"}, "unsupported manifest schema")
    require(m["unit"] == name and m["gt_version"] == version and gt._version(m) == version,
            "closure identity/content mismatch")
    require(m["digest_rule"] == gt.DIGEST_RULE, "unsupported digest rule")
    return m, rows(m["files"], sources=True, owner=name)


def candidate(root, *, name, version, member):
    """Return a deterministic review candidate; no selection of latest/current."""
    unit(name)
    unit(member)
    digest(version)
    require(name != "_shared", "certification candidates are per member, not global engine")
    reader = None
    try:
        reader = Reader(root)
        m, own = manifest(reader, name, version)
        require(m["member"] == member, "member does not match the requested identity")
        registration = m["registration"]
        require(isinstance(registration, str) and registration in own
                and m["registration_note"] is None, "member has no bound registration")
        pin = m["engine"]
        require(isinstance(pin, dict) and set(pin) == {"unit", "gt_version", "files"}
                and pin["unit"] == "_shared", "missing/unsupported engine pin")
        engine, engine_files = manifest(reader, "_shared", pin["gt_version"])
        require(engine["member"] is None and engine["registration"] is None
                and engine["registration_note"] is None and engine["engine"] is None
                and engine["requires"] == [], "invalid engine closure")
        require(rows(pin["files"]) == engine_files, "engine pin differs from engine manifest")
        wanted = {f"{name}/{p}": d for p, d in own.items()}
        wanted.update({f"_shared/{p}": d for p, d in engine_files.items()})
        reqs = m["requires"]
        require(isinstance(reqs, list) and len(reqs) <= MAX_FILES, "invalid requirements")
        for req in reqs:
            require(isinstance(req, dict) and set(req) == {"unit", "path", "sha256"}, "invalid requirement")
            key = f"{unit(req['unit'])}/{relative(req['path'])}"
            require(key not in wanted, "overlapping or duplicate dependency path")
            wanted[key] = digest(req["sha256"])
        require(len(wanted) <= MAX_FILES, "closure exceeds file budget")
        files = []
        registration_key = f"{name}/{registration}"
        for path, expected in sorted(wanted.items()):
            data = reader.read(f"blobs/{expected[:2]}/{expected}")
            require(gt.canonical_digest(data) == expected, "blob differs from pinned digest")
            if not path.endswith(".json"):
                headers = [gt._HEADER_RE.match(line) for line in data.decode(
                    "utf-8", "surrogateescape").split("\n")]
                require(sum(h is not None for h in headers) == 1
                        and gt.header_value(data) == expected, "published header differs from manifest")
            if path == registration_key:
                reg = parse(data)
                require(isinstance(reg, dict) and isinstance(reg.get("hooks"), dict)
                        and bool(reg["hooks"]), "registration has no hook-event map")
            files.append({"path": path, "canonical_sha256": expected,
                          "bytes_sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
        result = {"schema": "hook-certification-candidate/v1", "status": "uncertified",
                  "unit": name, "member": member, "gt_version": version,
                  "engine_version": pin["gt_version"],
                  "registration": {"path": registration_key, "sha256": own[registration]},
                  "files": files}
        result["candidate_sha256"] = hashlib.sha256(json.dumps(
            result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return result
    except (OSError, KeyError, TypeError, RecursionError) as exc:
        raise CandidateError("store cannot supply a complete bounded candidate") from exc
    finally:
        if reader is not None:
            reader.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--member", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(candidate(args.store, name=args.unit, version=args.version,
                                   member=args.member), indent=2, sort_keys=True))
    except CandidateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
