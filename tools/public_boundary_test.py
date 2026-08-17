#!/usr/bin/env python3
"""Regression tests for tools/public_boundary.py."""
import json
import os
import sys
import tempfile
from pathlib import Path

import public_boundary as boundary

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins" / "_shared"))
from hestia_gate_core import HarnessProfile, detect_workspace


def check(label, condition):
    if not condition:
        raise AssertionError(label)


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "forum").mkdir()
    (root / "forum" / "note.md").write_text("local")
    (root / "plugins" / "member" / "hooks").mkdir(parents=True)
    hydrate = root / "plugins" / "member" / "hooks" / "hydrate.sh"
    hydrate.write_text('PRIVATE_EXCEPTIONS={"operator-repo"}\n')
    (root / "plugins" / "member" / "instance").mkdir()
    seed = root / "plugins" / "member" / "instance" / "identity.seed.json"
    seed.write_text(json.dumps({"relationships": {"peer": {}}, "mrh": {"in_scope": ["repo:x"]}}))
    bad = boundary.inspect(root, [
        "forum/note.md",
        "plugins/member/hooks/hydrate.sh",
        "plugins/member/instance/identity.seed.json",
    ])
    check("local root", any("installation-local root" in p for p in bad))
    check("authority writer", any("continuity hook writes authorization" in p for p in bad))
    check("relationships", any("installation relationships" in p for p in bad))
    check("scope", any("installation scope" in p for p in bad))

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "plugins" / "member" / "instance").mkdir(parents=True)
    seed = root / "plugins" / "member" / "instance" / "identity.seed.json"
    seed.write_text(json.dumps({"relationships": {}, "mrh": {"in_scope": []}}))
    check("generic seed passes", boundary.inspect(root, [
        "plugins/member/instance/identity.seed.json"
    ]) == [])

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    nested = root / "checkout" / "project"
    nested.mkdir(parents=True)
    # Familiar sibling names must not become installation authority.
    (root / "checkout" / "hestia").mkdir()
    (root / "checkout" / "private-context").mkdir()
    old_cwd = Path.cwd()
    old_ws = os.environ.pop("HESTIA_WORKSPACE", None)
    try:
        os.chdir(nested)
        profile = HarnessProfile(member_id="test", identity_path="")
        check("no name-based discovery", detect_workspace(profile) == str(nested))
        (root / "checkout" / ".hestia-workspace").write_text("\n")
        check("portable marker", detect_workspace(profile) == str(root / "checkout"))
        explicit = root / "explicit"
        explicit.mkdir()
        os.environ["HESTIA_WORKSPACE"] = str(explicit)
        check("explicit env wins", detect_workspace(profile) == str(explicit))
    finally:
        os.chdir(old_cwd)
        if old_ws is None:
            os.environ.pop("HESTIA_WORKSPACE", None)
        else:
            os.environ["HESTIA_WORKSPACE"] = old_ws

live = boundary.inspect(REPO, boundary.tracked_paths(REPO))
if live:
    raise AssertionError("public tree violates boundary:\n  " + "\n  ".join(live))

print("public-boundary tests: PASS")
