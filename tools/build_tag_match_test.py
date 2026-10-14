#!/usr/bin/env python3
"""ONLY RELEASE TAGS NAME A BUILD (web4#904): every build-id producer describes with one glob.

A hestia build id is a `git describe` string. The Android `app-v*` tags are ancestors of main, so
an unmatched describe can name a daemon after the app: on 2026-08-08 the reference daemon reported
`app-v0.1.2-761-g9a6a5c2`. core/build.rs bakes `--match 'v[0-9]*'`, and the strings it produces
are compared by the deploy, the dashboard's authority file, the member-mesh watcher and the
upgrade-path harness. One producer left on the old spelling makes them disagree only on the day
an app tag lands near a release, which is the day nobody is looking. So this pins:

1. Each named producer uses exactly the glob `v[0-9]*`.
2. A sweep: no non-test source line runs `describe ... --tags` without `--match` (a two-line
   window, for calls split across lines).
3. deploy/install-members.sh is governed (closure floor) and its fix is HELD: its unmatched line
   is accepted only while held/<sha256>.patch exists, is named by its own digest, and changes
   exactly that line to the matched form. Once applied, the matched form is required.

Run: python3 tools/build_tag_match_test.py   (exit 1 on failure)
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GLOB = "v[0-9]*"
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {detail}"))
    if not cond:
        FAILS.append(name)


def text(rel: str) -> str:
    return (REPO / rel).read_text()


# ---- 1. the named producers ---------------------------------------------------------------------
check("core/build.rs bakes --match v[0-9]*",
      '"describe", "--tags", "--match", "v[0-9]*", "--always", "--dirty"' in text("core/build.rs"))
deploy = text("deploy/from-main/hestia-deploy.sh")
check("hestia-deploy.sh: BUILD_TAG_MATCH is the glob", f"\nBUILD_TAG_MATCH='{GLOB}'\n" in deploy)
check("hestia-deploy.sh: the target is described with it",
      'describe --tags --match "$BUILD_TAG_MATCH" --always)"' in deploy)
watch = text("plugins/member-mesh/hestia-watch-member.sh")
check("watcher: WATCH_BUILD_TAG_MATCH is the glob", f"\nWATCH_BUILD_TAG_MATCH='{GLOB}'\n" in watch)
check("watcher: the source is described with it",
      'describe --tags --match "$WATCH_BUILD_TAG_MATCH" --always --dirty' in watch)
check("upgrade_path_test.py: BUILD_TAG_MATCH is the glob",
      f'\nBUILD_TAG_MATCH = "{GLOB}"\n' in text("tools/upgrade_path_test.py"))

# ---- 2. the sweep -------------------------------------------------------------------------------
DESCRIBE = re.compile(r"""describe["',\s]+(?:--[a-z=0-9]+["',\s]+)*--tags""")
COMMENT = re.compile(r"^\s*(#|//|///|//!)")
INSTALLER = "deploy/install-members.sh"
files = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.sh", "*.py", "*.rs", "*.yml"],
                       capture_output=True, text=True, check=True).stdout.split()
unmatched: list[str] = []
installer_lines: list[str] = []
for rel in files:
    if rel.startswith("held/") or "/tests/" in rel or rel.endswith("_test.py") \
            or rel.startswith("tests/"):
        continue
    p = REPO / rel
    if not p.is_file():
        continue
    try:
        lines = p.read_text().splitlines()
    except UnicodeDecodeError:
        continue
    for i, line in enumerate(lines):
        if COMMENT.match(line) or not DESCRIBE.search(line):
            continue
        window = line + (lines[i + 1] if i + 1 < len(lines) else "")
        if "--match" in window:
            continue
        if rel == INSTALLER:
            installer_lines.append(line)
        else:
            unmatched.append(f"{rel}:{i + 1}: {line.strip()}")
check("no build-id producer outside the installer describes without --match", not unmatched,
      "; ".join(unmatched))

# ---- 3. the governed installer: matched, or its fix held -----------------------------------------
installer = text(INSTALLER)
MATCHED = f"""describe --tags --match '{GLOB}' --always --dirty"""
if not installer_lines:
    check("installer: build_id is described with the glob", MATCHED in installer)
else:
    held_ok = False
    detail = "no held patch fixes it"
    for patch in sorted((REPO / "held").glob("*.patch")):
        body = patch.read_bytes()
        if f"a/{INSTALLER}".encode() not in body:
            continue
        if hashlib.sha256(body).hexdigest() != patch.stem:
            detail = f"{patch.name} is not named by its digest"
            continue
        minus = [ln[1:] for ln in body.decode().splitlines()
                 if ln.startswith("-") and not ln.startswith("---")]
        plus = [ln[1:] for ln in body.decode().splitlines()
                if ln.startswith("+") and not ln.startswith("+++")]
        if minus == installer_lines and any(MATCHED in ln for ln in plus):
            held_ok = True
            print(f"PENDING installer build_id: governed, fix held as held/{patch.name} "
                  "(held/README-lockstep.md)")
            break
    check("installer: an unmatched build_id is accepted only while its fix is held", held_ok, detail)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    sys.exit(1)
print("\nALL CHECKS PASSED")
