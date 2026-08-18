#!/usr/bin/env python3
"""Regression tests for tools/public_boundary.py."""
import json
import os
import subprocess
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


def exercise_hydrate(member, home_var, instance_var, agents_var, plugin_var):
    """Run the real continuity hook and prove it cannot become authority."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        instance = root / "configured-instance"
        instance.mkdir()
        identity_path = instance / "identity.json"
        identity = {
            "session_count": 4,
            "first_session": "2026-01-01T00:00:00+00:00",
            "last_session": "2026-01-02T00:00:00+00:00",
            "phase": "test",
            "role": "role:test",
            "sessions": [],
            "relationships": {"peer": {"trust": "local-test"}},
            "mrh": {"in_scope": ["repo:must-survive"]},
        }
        identity_path.write_text(json.dumps(identity))
        agents = root / "AGENTS.md"
        agents.write_text(
            "before\n<!-- HESTIA:STATE:BEGIN -->\nold\n"
            "<!-- HESTIA:STATE:END -->\nafter\n"
        )
        observe = root / "observe"
        observe.mkdir()
        env = dict(os.environ)
        env.update({
            home_var: str(root / "unused-default-home"),
            instance_var: str(instance),
            agents_var: str(agents),
            plugin_var: str(REPO / "plugins" / member),
            "HESTIA_OBSERVE_DIR": str(observe),
        })
        script = REPO / "plugins" / member / "hooks" / "hydrate.sh"
        subprocess.run(
            [str(script)], input='{"session_id":"boundary-test"}\n', text=True,
            env=env, check=True,
        )
        hydrated = json.loads(identity_path.read_text())
        check(f"{member} relationships unchanged",
              hydrated["relationships"] == identity["relationships"])
        check(f"{member} scope unchanged", hydrated["mrh"] == identity["mrh"])
        rendered = agents.read_text()
        check(f"{member} configured identity path rendered",
              str(identity_path.resolve()) in rendered)
        default_identity = {"codex": "~/.codex/", "kimi": "~/.kimi-code/"}[member]
        check(f"{member} default identity path absent", default_identity not in rendered)
        return rendered


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

codex_state = exercise_hydrate(
    "codex", "CODEX_HOME", "HESTIA_CODEX_INSTANCE_DIR",
    "HESTIA_CODEX_AGENTS_MD", "CODEX_PLUGIN_ROOT",
)
check("Codex state names edit coverage", "apply_patch" in codex_state)
check("Codex state names MCP coverage", "MCP Function-payload" in codex_state)
check("Codex stale shell-only claim absent", "SHELL tool ONLY" not in codex_state)

exercise_hydrate(
    "kimi", "KIMI_CODE_HOME", "HESTIA_KIMI_INSTANCE_DIR",
    "HESTIA_KIMI_AGENTS_MD", "KIMI_PLUGIN_ROOT",
)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    staged = root / "runtime.py"
    staged.write_text('ROOT = "/home/actual-operator/runtime"\n')
    subprocess.run(["git", "add", "runtime.py"], cwd=root, check=True)
    # A working-tree scan sees the safe unstaged replacement.  A pre-commit
    # scan must still reject the exact installation path already in the index.
    staged.write_text('ROOT = "/home/user/runtime"\n')
    check("working tree differs safely", boundary.inspect(root, ["runtime.py"]) == [])
    cached = boundary.inspect(root, boundary.tracked_paths(root), cached=True)
    check("cached snapshot is inspected", any("local home path" in p for p in cached))

    # Git permits newlines in filenames. The index reader uses NUL framing so an
    # adversarial path cannot desynchronize the scanner's path-to-blob mapping.
    odd = root / "odd\nruntime.py"
    odd.write_text('ROOT = "/home/another-operator/runtime"\n')
    subprocess.run(["git", "add", "odd\nruntime.py"], cwd=root, check=True)
    cached = boundary.inspect(root, boundary.tracked_paths(root), cached=True)
    check("newline path stays framed", any("odd\nruntime.py" in p for p in cached))

    link = root / "innocent-link"
    link.symlink_to("relative-product-path")
    subprocess.run(["git", "add", "innocent-link"], cwd=root, check=True)
    unexpected = root / "notes.bin"
    unexpected.write_bytes(b"\xff\x00installation-local")
    subprocess.run(["git", "add", "notes.bin"], cwd=root, check=True)
    paths = boundary.tracked_paths(root)
    modes = boundary.tracked_modes(root)
    cached = boundary.inspect(root, paths, cached=True, modes=modes)
    check("staged symlink rejected", any("innocent-link" in p and "not a regular" in p
                                         for p in cached))
    check("unexpected binary rejected", any("notes.bin" in p and "non-text" in p
                                             for p in cached))

    icon = root / "app" / "src-tauri" / "icons" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\n\xff")
    subprocess.run(["git", "add", "app/src-tauri/icons/icon.png"], cwd=root, check=True)
    icon_rel = "app/src-tauri/icons/icon.png"
    allowed = boundary.inspect(
        root, [icon_rel], cached=True, modes=boundary.tracked_modes(root),
    )
    check("reviewed product binary allowed", allowed == [])

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

live = boundary.inspect(REPO, boundary.tracked_paths(REPO), modes=boundary.tracked_modes(REPO))
if live:
    raise AssertionError("public tree violates boundary:\n  " + "\n  ".join(live))

print("public-boundary tests: PASS")
