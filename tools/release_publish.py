#!/usr/bin/env python3
"""Attach a release's assets to its draft and publish it -- only when the whole manifest is there.

release.yml's `publish` job runs this (web4#904: one tag, one release). It exists as a script, not
inline workflow shell, so that the one step that makes a release visible can be tested with a
mocked `gh` (tools/release_publish_test.py). Codex's HOLD on hestia#1283 reproduced the inline
version publishing an EMPTY release: the artifact download was continue-on-error, a failed
download left no dist/, the fresh draft had no assets, "local list == remote list" compared two
empty lists as equal, and the draft was flipped to published with nothing on it.

So the gate here is not "what I uploaded equals what is attached". It is: the assemble job
succeeded, AND the local set is exactly MANIFEST(tag), AND the draft's attached set is exactly
MANIFEST(tag), AND the release is still a draft. Missing, extra or stale assets all block. Only
then is the draft PATCHed to published -- as a pre-release that is never `latest` for a
`vX.Y.Z-rc.N` tag, as the latest release for a plain `vX.Y.Z` (the installer resolves
releases/latest, #1279, so an rc must never become latest).

Everything goes through the release's numeric id, never its tag: the by-tag endpoints cannot see
drafts.

Usage:
    release_publish.py manifest LABEL                 # print the expected asset names
    release_publish.py check-dir DIR LABEL            # exit 1 unless DIR holds exactly the manifest
    release_publish.py publish --tag T --release-id ID --dist DIR --assemble RESULT --notes FILE
          [--kind release|prerelease]                 # env: GH_REPO (owner/name); gh on PATH
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

DAEMON_TARGETS = (
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "aarch64-apple-darwin",
)
APP_ASSETS = (
    "x86_64-linux.AppImage",
    "x86_64-linux.deb",
    "aarch64-macos.dmg",
    "aarch64-macos.app.tar.gz",
    "android-universal.apk",
)


def manifest(label: str) -> list[str]:
    """Every name a complete release carries: 8 assets, a .sha256 each, and SHA256SUMS."""
    assets = [f"hestia-{label}-{t}.tar.gz" for t in DAEMON_TARGETS]
    assets += [f"hestia-app-{label}-{a}" for a in APP_ASSETS]
    return sorted(assets + [a + ".sha256" for a in assets] + ["SHA256SUMS"])


def local_names(dist: pathlib.Path) -> list[str]:
    if not dist.is_dir():
        return []
    return sorted(p.name for p in dist.iterdir() if p.is_file())


def diff(want: list[str], have: list[str]) -> list[str]:
    w, h = set(want), set(have)
    return [f"missing {n}" for n in sorted(w - h)] + [f"unexpected {n}" for n in sorted(h - w)]


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} ... failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def get_release(repo: str, rid: str) -> dict:
    return json.loads(gh("api", f"repos/{repo}/releases/{rid}"))


def bound_to_tag(repo: str, tag: str, rid: str) -> bool:
    """True when GitHub's by-tag lookup returns THIS release (drafts are invisible to it)."""
    try:
        return str(json.loads(gh("api", f"repos/{repo}/releases/tags/{tag}")).get("id")) == str(rid)
    except Exception:  # noqa: BLE001 -- a 404 or a gh failure both mean "not bound"
        return False


def repair(repo: str, a) -> str:
    return f"fix by hand: gh api -X PATCH repos/{repo}/releases/{a.release_id} -f tag_name={a.tag}"


def remote_state(repo: str, a) -> str:
    """What the release is now, re-read -- never inferred from which call failed."""
    try:
        rel = get_release(repo, a.release_id)
    except Exception as e:  # noqa: BLE001 -- the state is then genuinely unknown; say so
        return f"release {a.release_id} state is UNKNOWN (re-read failed: {e})"
    return (f"release {a.release_id} now reads draft={str(rel.get('draft')).lower()}, "
            f"tag_name={rel.get('tag_name')!r}")


def cmd_check_dir(dist: pathlib.Path, label: str) -> int:
    problems = diff(manifest(label), local_names(dist))
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


def cmd_publish(a) -> int:
    repo = a.repo
    want = manifest(a.tag)
    have = local_names(a.dist)
    problems: list[str] = []

    rel = get_release(repo, a.release_id)
    if rel.get("tag_name") != a.tag:
        print(f"::error::release {a.release_id} is for {rel.get('tag_name')!r}, not {a.tag!r}")
        return 1
    if not rel.get("draft"):
        print(f"::error::release {a.release_id} ({a.tag}) is not a draft; refusing to modify it")
        return 1

    gh("api", "-X", "PATCH", f"repos/{repo}/releases/{a.release_id}",
       "-F", f"body=@{a.notes}", "-f", f"name={a.tag}")

    # Attach what exists, so a failed run leaves an informative draft. Replace by deleting the
    # same-named asset first (the upload endpoint refuses a duplicate name).
    attached = {x["name"]: x["id"] for x in rel.get("assets", [])}
    upload_failed = False
    for name in have:
        try:
            if name in attached:
                gh("api", "-X", "DELETE", f"repos/{repo}/releases/assets/{attached[name]}")
            gh("api", "-X", "POST",
               f"https://uploads.github.com/repos/{repo}/releases/{a.release_id}/assets?name={name}",
               "-H", "Content-Type: application/octet-stream",
               "--input", str(a.dist / name))
        except RuntimeError as e:
            upload_failed = True
            problems.append(f"upload of {name} failed: {e}")

    rel = get_release(repo, a.release_id)
    remote = sorted(x["name"] for x in rel.get("assets", []))
    print(f"attached to draft {a.release_id}: {len(remote)} asset(s)")

    if a.assemble != "success":
        problems.append(f"assemble result is {a.assemble!r}, not 'success'")
    problems += [f"local: {p}" for p in diff(want, have)]
    problems += [f"draft: {p}" for p in diff(want, remote)]
    if not rel.get("draft"):
        problems.append("the release stopped being a draft while assets were attaching")
    if upload_failed and not problems:
        problems.append("an upload failed")

    if problems:
        for p in problems:
            print(f"::error::{p}")
        print(f"::error::{a.tag} is left as a DRAFT and was NOT published.")
        return 1

    pre = a.kind == "prerelease"
    # tag_name GOES IN THE PUBLISH PATCH. v0.3.0-rc.1 (run 38289872894) published with every
    # asset but as `untagged-<hex>`: GitHub keeps a draft under a placeholder name until it is
    # published, and a PATCH that flips draft=false without naming the tag left the placeholder.
    # The pre-publish check above read the draft's tag_name and passed; only the by-tag lookup
    # after publishing tells the truth, so that is what is verified below.
    # From the publish PATCH on, "left as a DRAFT" is no longer known to be true: a gh failure here
    # may come after GitHub applied the flip (Codex HOLD #1285: a failed re-bind was reported as a
    # draft while the release was public and untagged). Report what the remote actually holds.
    try:
        gh("api", "-X", "PATCH", f"repos/{repo}/releases/{a.release_id}",
           "-f", f"tag_name={a.tag}",
           "-F", "draft=false",
           "-F", f"prerelease={'true' if pre else 'false'}",
           "-f", f"make_latest={'false' if pre else 'true'}")
        if not bound_to_tag(repo, a.tag, a.release_id):
            print(f"::warning::{a.tag}: published release {a.release_id} is not reachable by its tag; "
                  "re-binding tag_name once")
            gh("api", "-X", "PATCH", f"repos/{repo}/releases/{a.release_id}", "-f", f"tag_name={a.tag}")
            if not bound_to_tag(repo, a.tag, a.release_id):
                print(f"::error::{a.tag}: release {a.release_id} is published but NOT bound to its tag; "
                      f"{repair(repo, a)}")
                return 1
    except RuntimeError as e:
        print(f"::error::{e}")
        print(f"::error::{a.tag}: failed after the publish PATCH was sent; {remote_state(repo, a)}")
        print(f"::error::{a.tag}: if release {a.release_id} is published but untagged, {repair(repo, a)}")
        return 1
    print(f"published {a.tag} as {'a PRE-RELEASE (not latest)' if pre else 'the LATEST release'}"
          f" with {len(remote)} assets")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("label")
    c = sub.add_parser("check-dir")
    c.add_argument("dist", type=pathlib.Path)
    c.add_argument("label")
    p = sub.add_parser("publish")
    p.add_argument("--tag", required=True)
    p.add_argument("--release-id", required=True)
    p.add_argument("--dist", type=pathlib.Path, required=True)
    p.add_argument("--assemble", required=True)
    p.add_argument("--notes", type=pathlib.Path, required=True)
    p.add_argument("--kind", choices=("release", "prerelease"), required=True)
    p.add_argument("--repo", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "manifest":
        print("\n".join(manifest(a.label)))
        return 0
    if a.cmd == "check-dir":
        return cmd_check_dir(a.dist, a.label)
    a.repo = a.repo or os.environ.get("GH_REPO", "")
    if not a.repo:
        print("::error::GH_REPO is not set")
        return 1
    try:
        return cmd_publish(a)
    except RuntimeError as e:
        print(f"::error::{e}")
        print(f"::error::{a.tag} is left as a DRAFT and was NOT published.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
