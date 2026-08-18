#!/usr/bin/env python3
"""Regression tests for tools/public_boundary.py."""
import hashlib
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

# The credential-shape rule had no arms at all before this block, and it cannot get one
# written the obvious way: a literal counterexample in THIS file would be flagged in the
# real tree, because the shape rule takes no `is_test` exemption.  So the two tokens below
# are assembled at call time.  That is an input to the scanner, not a hiding place — and
# the arms are built so the exemption cannot be mistaken for a path-wide carve-out.
check("the reviewed-example allowlist is non-empty",
      bool(boundary.PUBLISHED_EXAMPLE_TOKENS))
REVIEWED_EXAMPLE = next(iter(boundary.PUBLISHED_EXAMPLE_TOKENS))
UNREVIEWED_SIBLING = "AKIA" + "7QY2NBWKZ4XJDT9F"   # same shape, value nobody reviewed

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "core" / "tests").mkdir(parents=True)
    (root / "tools").mkdir()

    pin = root / "core" / "tests" / "unscrubbed_pin.rs"
    pin.write_text(f'const SHAPED: &str = "{REVIEWED_EXAMPLE}";\n')
    check("reviewed example passes",
          boundary.inspect(root, ["core/tests/unscrubbed_pin.rs"]) == [])

    # Value-scoped, not path-scoped: the sibling sits on a test path too, and the ONLY
    # thing that differs between this arm and the one above is whether the value was
    # reviewed.  A carve-out for `is_test` paths would green both and prove nothing.
    sibling = root / "core" / "tests" / "pasted_fixture.rs"
    sibling.write_text(f'const CAPTURED: &str = "{UNREVIEWED_SIBLING}";\n')
    check("unreviewed sibling on a test path is still caught",
          any("credential-shaped token" in p
              for p in boundary.inspect(root, ["core/tests/pasted_fixture.rs"])))

    # And the exemption must not cover for its neighbour.  A `search`-then-skip
    # implementation greens this file: the reviewed example matches first and the real
    # token never gets looked at.  Filtering the matches is what fails it.
    both = root / "tools" / "runtime_notes.py"
    both.write_text(f'EXAMPLE = "{REVIEWED_EXAMPLE}"\nREAL = "{UNREVIEWED_SIBLING}"\n')
    check("a reviewed example does not shield a token beside it",
          any("credential-shaped token" in p
              for p in boundary.inspect(root, ["tools/runtime_notes.py"])))

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
    check("unexpected binary rejected", any("notes.bin" in p and "manifest" in p
                                             for p in cached))

    worktree_link = root / "worktree-link"
    worktree_link.write_text("regular in the index\n")
    subprocess.run(["git", "add", "worktree-link"], cwd=root, check=True)
    worktree_link.unlink()
    worktree_link.symlink_to("relative-product-path")
    worktree = boundary.inspect(
        root, ["worktree-link"], cached=False, modes=boundary.tracked_modes(root),
    )
    check("unstaged worktree symlink rejected",
          any("worktree-link" in p and "worktree path is a symlink" in p
              for p in worktree))

    icon = root / "app" / "src-tauri" / "icons" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon_bytes = b"\x89PNG\r\n\x1a\n\xff"
    icon.write_bytes(icon_bytes)
    icon_rel = "app/src-tauri/icons/icon.png"
    manifest = root / boundary.BINARY_MANIFEST
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(f"{hashlib.sha256(icon_bytes).hexdigest()}  {icon_rel}\n")
    subprocess.run(
        ["git", "add", icon_rel, boundary.BINARY_MANIFEST], cwd=root, check=True,
    )
    allowed = boundary.inspect(
        root, [icon_rel, boundary.BINARY_MANIFEST], cached=True,
        modes=boundary.tracked_modes(root),
    )
    check("reviewed product binary allowed", allowed == [])

    icon.write_bytes(icon_bytes + b"changed")
    subprocess.run(["git", "add", icon_rel], cwd=root, check=True)
    changed = boundary.inspect(
        root, [icon_rel, boundary.BINARY_MANIFEST], cached=True,
        modes=boundary.tracked_modes(root),
    )
    check("changed product binary needs review",
          any(icon_rel in p and "manifest review" in p for p in changed))

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
