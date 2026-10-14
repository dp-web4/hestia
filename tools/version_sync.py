#!/usr/bin/env python3
"""One version for the daemon, the app, the wire crate and the plugin SDKs.

hestia's daemon and desktop app release together under ONE lockstep version and
ONE tag (dp, 2026-10-11; web4#904 phase 1). The repo has no Cargo workspace --
core, wire, app/src-tauri and plugin-sdk/rust are separate crates with their own
lockfiles and path deps into the web4 sibling -- and half the manifests are JSON
or pyproject, so no single build tool owns the number. The root `VERSION` file
does. This tool checks (default) or writes (`--write`) every place the number is
restated:

  Cargo.toml   core, wire, app/src-tauri, plugin-sdk/rust   [package] version
  Cargo.toml   core's `hestia-wire` dependency requirement   "=X.Y.Z"
  Cargo.lock   core (hestia, hestia-wire), app (hestia-app, hestia-wire)
  JSON         app/package.json, app/package-lock.json (root + packages[""]),
               app/src-tauri/tauri.conf.json, plugin-sdk/typescript/package.json
  Python       plugin-sdk/python/pyproject.toml, hestia_plugin_sdk.__version__

Not covered, on purpose: hardbound-pak/ (its own product line), demo/ and
plugins/openclaw (consumers, not shipped artifacts).

Usage:
    python3 tools/version_sync.py                  # check; exit 1 on any drift
    python3 tools/version_sync.py --write          # rewrite every site to VERSION
    python3 tools/version_sync.py --tag v0.3.0     # check, AND the tag is v$VERSION
    python3 tools/version_sync.py --tag v0.3.0-rc.1  # ... or a release candidate of it
    python3 tools/version_sync.py --tag-kind v0.3.0-rc.1   # print `release` or `prerelease`

Release tags (dp, 2026-10-12): exactly `vX.Y.Z` (a release, published as latest) or
`vX.Y.Z-rc.N` (a release candidate, published as a GitHub pre-release and never latest),
with X.Y.Z equal to VERSION and N a SemVer numeric identifier (digits, no leading zero).
Nothing else is a release tag: not `-rc`, `-rc.`, `-rc.01`, `-beta.1`, `-RC.1`, `.1`.
    python3 tools/version_sync.py --print          # print VERSION

Writes are textual (one targeted substitution per site) so no file is reformatted;
every write is re-read through a real parser (tomllib / json) before it counts.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - CI runs 3.12
    tomllib = None

REPO = pathlib.Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class Site:
    """One place a version is restated. `read` returns what is there now;
    `write` returns the new file text with the version replaced."""

    def __init__(self, rel: str, label: str):
        self.rel = rel
        self.label = label

    def path(self, root: pathlib.Path) -> pathlib.Path:
        return root / self.rel

    def read(self, text: str) -> str | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def write(self, text: str, version: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class TomlTableKey(Site):
    """`version = "..."` as the first such key inside a named [table]."""

    def __init__(self, rel: str, table: str, label: str | None = None):
        super().__init__(rel, label or f"[{table}] version")
        self.table = table

    def _span(self, text: str) -> tuple[int, int] | None:
        head = re.search(rf"^\[{re.escape(self.table)}\]\s*$", text, re.M)
        if not head:
            return None
        nxt = re.search(r"^\[", text[head.end():], re.M)
        end = head.end() + (nxt.start() if nxt else len(text) - head.end())
        return head.end(), end

    def read(self, text):
        span = self._span(text)
        if not span:
            return None
        m = re.search(r'^version\s*=\s*"([^"]*)"', text[span[0]:span[1]], re.M)
        return m.group(1) if m else None

    def write(self, text, version):
        span = self._span(text)
        if not span:
            raise ValueError(f"{self.rel}: no [{self.table}] table")
        body = text[span[0]:span[1]]
        new, n = re.subn(r'^(version\s*=\s*")[^"]*(")', rf"\g<1>{version}\g<2>", body, count=1, flags=re.M)
        if n != 1:
            raise ValueError(f"{self.rel}: no version key in [{self.table}]")
        return text[:span[0]] + new + text[span[1]:]


class CargoDepReq(Site):
    """An in-repo path dependency's version requirement, pinned exactly: in
    lockstep the wire crate a daemon was built against IS the same release."""

    def __init__(self, rel: str, dep: str):
        super().__init__(rel, f"dependency {dep} version requirement")
        self.dep = dep
        self.rx = re.compile(rf'^({re.escape(dep)}\s*=\s*\{{[^}}\n]*\bversion\s*=\s*")([^"]*)(")', re.M)

    def read(self, text):
        m = self.rx.search(text)
        if not m:
            return None
        req = m.group(2)
        return req[1:] if req.startswith("=") else f"(not exact: {req})"

    def write(self, text, version):
        new, n = self.rx.subn(rf"\g<1>={version}\g<3>", text, count=1)
        if n != 1:
            raise ValueError(f"{self.rel}: no {self.dep} dependency with a version requirement")
        return new


class CargoLockPkg(Site):
    """A path package's entry in a Cargo.lock. Path packages carry no source or
    checksum line, so the version line is the whole record of them."""

    def __init__(self, rel: str, pkg: str):
        super().__init__(rel, f"lock entry {pkg}")
        self.rx = re.compile(rf'(\[\[package\]\]\nname = "{re.escape(pkg)}"\nversion = ")([^"]*)(")')

    def read(self, text):
        found = self.rx.findall(text)
        if len(found) != 1:
            return None if not found else f"(ambiguous: {len(found)} entries)"
        return found[0][1]

    def write(self, text, version):
        new, n = self.rx.subn(rf"\g<1>{version}\g<3>", text)
        if n != 1:
            raise ValueError(f"{self.rel}: expected exactly one entry, found {n}")
        return new


class JsonVersion(Site):
    """A JSON "version" key at a given object path. The write is textual: the
    n-th `"version": "..."` occurrence in document order is replaced, and the
    parse afterwards confirms it was the intended key."""

    def __init__(self, rel: str, keypath: tuple[str, ...], occurrence: int = 0):
        label = "version" if not keypath else ".".join(repr(k) if k == "" else k for k in keypath) + ".version"
        super().__init__(rel, label)
        self.keypath = keypath
        self.occurrence = occurrence

    def read(self, text):
        node = json.loads(text)
        for k in self.keypath:
            node = node.get(k, {}) if isinstance(node, dict) else {}
        v = node.get("version") if isinstance(node, dict) else None
        return v if isinstance(v, str) else None

    def write(self, text, version):
        hits = list(re.finditer(r'("version"\s*:\s*")([^"]*)(")', text))
        if len(hits) <= self.occurrence:
            raise ValueError(f"{self.rel}: no version occurrence #{self.occurrence}")
        m = hits[self.occurrence]
        return text[:m.start(2)] + version + text[m.end(2):]


class PyDunderVersion(Site):
    def __init__(self, rel: str):
        super().__init__(rel, "__version__")
        self.rx = re.compile(r'^(__version__\s*=\s*")([^"]*)(")', re.M)

    def read(self, text):
        m = self.rx.search(text)
        return m.group(2) if m else None

    def write(self, text, version):
        new, n = self.rx.subn(rf"\g<1>{version}\g<3>", text, count=1)
        if n != 1:
            raise ValueError(f"{self.rel}: no __version__")
        return new


SITES: list[Site] = [
    TomlTableKey("core/Cargo.toml", "package"),
    CargoDepReq("core/Cargo.toml", "hestia-wire"),
    CargoLockPkg("core/Cargo.lock", "hestia"),
    CargoLockPkg("core/Cargo.lock", "hestia-wire"),
    TomlTableKey("wire/Cargo.toml", "package"),
    CargoLockPkg("wire/Cargo.lock", "hestia-wire"),
    TomlTableKey("app/src-tauri/Cargo.toml", "package"),
    CargoLockPkg("app/src-tauri/Cargo.lock", "hestia-app"),
    CargoLockPkg("app/src-tauri/Cargo.lock", "hestia-wire"),
    JsonVersion("app/src-tauri/tauri.conf.json", ()),
    JsonVersion("app/package.json", ()),
    JsonVersion("app/package-lock.json", (), occurrence=0),
    JsonVersion("app/package-lock.json", ("packages", ""), occurrence=1),
    TomlTableKey("plugin-sdk/rust/Cargo.toml", "package"),
    JsonVersion("plugin-sdk/typescript/package.json", ()),
    TomlTableKey("plugin-sdk/python/pyproject.toml", "project"),
    PyDunderVersion("plugin-sdk/python/hestia_plugin_sdk/__init__.py"),
]


def read_version(root: pathlib.Path = REPO) -> str:
    v = (root / "VERSION").read_text().strip()
    if not SEMVER.match(v):
        raise ValueError(f"VERSION is not X.Y.Z: {v!r}")
    return v


def _reparse(rel: str, text: str) -> None:
    if rel.endswith(".json"):
        json.loads(text)
    elif rel.endswith((".toml", ".lock")) and tomllib is not None:
        tomllib.loads(text)


def check(root: pathlib.Path = REPO, version: str | None = None) -> list[str]:
    """Every disagreement, as a human-readable line. Empty means in sync."""
    version = version or read_version(root)
    problems = []
    for site in SITES:
        p = site.path(root)
        if not p.exists():
            problems.append(f"{site.rel}: missing (expected {site.label} = {version})")
            continue
        got = site.read(p.read_text())
        if got != version:
            problems.append(f"{site.rel}: {site.label} = {got!r}, VERSION = {version!r}")
    return problems


def write(root: pathlib.Path = REPO, version: str | None = None) -> list[str]:
    version = version or read_version(root)
    changed = []
    texts: dict[str, str] = {}
    for site in SITES:
        texts.setdefault(site.rel, site.path(root).read_text())
        texts[site.rel] = site.write(texts[site.rel], version)
    for rel, text in texts.items():
        _reparse(rel, text)
        p = root / rel
        if p.read_text() != text:
            p.write_text(text)
            changed.append(rel)
    return changed


RC_SUFFIX = re.compile(r"-rc\.(0|[1-9][0-9]*)")


def tag_kind(tag: str, root: pathlib.Path = REPO) -> str | None:
    """`release` for v$VERSION, `prerelease` for v$VERSION-rc.N, None for anything else."""
    tag = tag.removeprefix("refs/tags/")
    want = "v" + read_version(root)
    if tag == want:
        return "release"
    if tag.startswith(want) and RC_SUFFIX.fullmatch(tag[len(want):]):
        return "prerelease"
    return None


def tag_problem(tag: str, root: pathlib.Path = REPO) -> str | None:
    if tag_kind(tag, root) is None:
        want = "v" + read_version(root)
        return (f"tag {tag.removeprefix('refs/tags/')!r} is not a release tag for VERSION "
                f"(expected {want!r} or {want + '-rc.N'!r})")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite every site to VERSION")
    ap.add_argument("--tag", help="also require this tag to be v$VERSION or v$VERSION-rc.N")
    ap.add_argument("--tag-kind", metavar="TAG",
                    help="print `release` or `prerelease` for TAG and exit (1 if not a release tag)")
    ap.add_argument("--print", action="store_true", help="print VERSION and exit")
    ap.add_argument("--root", type=pathlib.Path, default=REPO, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    version = read_version(a.root)
    if a.print:
        print(version)
        return 0
    if a.tag_kind is not None:
        kind = tag_kind(a.tag_kind, a.root)
        if kind is None:
            print(tag_problem(a.tag_kind, a.root), file=sys.stderr)
            return 1
        print(kind)
        return 0
    if a.write:
        for rel in write(a.root, version):
            print(f"wrote {rel}")
    problems = check(a.root, version)
    if a.tag:
        tp = tag_problem(a.tag, a.root)
        if tp:
            problems.append(tp)
    if problems:
        print(f"version drift against VERSION={version} (fix: python3 tools/version_sync.py --write):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"all {len(SITES)} version sites = {version}" + (f"; tag {a.tag} matches" if a.tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
