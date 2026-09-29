#!/usr/bin/env python3
"""deploy/register-members.py: registration is the installer's act, never a hand edit (#1133).

The case that must never regress is thor's, 2026-09-27: codex's config.toml carried observe.sh
on PostToolUse and nothing for witness.py, so the installer skipped the witness every cycle and
no codex act ever reached the chain. Case A reproduces that file shape and asserts the script
adds exactly the missing hook, that install-members.sh's own line-scan reader then SEES it, and
that a second run changes nothing. The rest are the ways this could go wrong quietly: a harness
that is not here must not be minted a registration (#1130), an unrendered placeholder must
refuse, a broken result must restore, and DRY_RUN must write nothing.

Run: python3 tools/register_members_test.py   (bare; exit 1 on failure; pytest-collectable)
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "register-members.py"

_spec = importlib.util.spec_from_file_location("register_members", SCRIPT)
RM = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(RM)

CODEX_TOML = """approval_policy = "on-request"
sandbox_mode    = "workspace-write"

[features]
codex_hooks = true

# ---- hestia: the fail-closed scope + egress + society-safety gate ----
[[hooks.PreToolUse]]
matcher = ".*"

[[hooks.PreToolUse.hooks]]
type          = "command"
command       = "python3 /home/u/.codex/hooks/pre_tool_use.py"
statusMessage = "hestia: scope + safety gate"
timeout       = 15

[[hooks.SessionStart]]

[[hooks.SessionStart.hooks]]
type    = "command"
command = "/home/u/.codex/hooks/observe.sh"
timeout = 15

[[hooks.PostToolUse]]
matcher = ".*"

[[hooks.PostToolUse.hooks]]
type    = "command"
command = "/home/u/.codex/hooks/observe.sh"
timeout = 10

[[hooks.SessionEnd]]

[[hooks.SessionEnd.hooks]]
type    = "command"
command = "/home/u/.codex/hooks/hydrate.sh"
timeout = 20

[hooks.state]

[hooks.state."/home/u/.codex/config.toml:pre_tool_use:0:0"]
approved = true
"""


def _plugins(tmp: Path) -> Path:
    """A plugins dir holding the REAL codex and claude-code manifests and templates."""
    p = tmp / "plugins"
    for m in ("codex", "claude-code"):
        (p / m / "hooks").mkdir(parents=True)
        (p / m / "expects.json").write_text((REPO / "plugins" / m / "expects.json").read_text())
        src = REPO / "plugins" / m / "hooks" / "hooks.json"
        if src.exists():
            (p / m / "hooks" / "hooks.json").write_text(src.read_text())
    return p


def _installer_reader(path: Path) -> set[str]:
    """install-members.sh's toml-hook-commands reader, verbatim semantics: `command = "..."`
    lines, the absolute-path token's basename."""
    seen = set()
    for line in path.read_text().splitlines():
        m = re.match(r"""\s*command\s*=\s*(['"])(.*)\1\s*$""", line)
        if m:
            for tok in m.group(2).split():
                if tok.startswith("/"):
                    seen.add(os.path.basename(tok))
    return seen


def _run(tmp: Path, plugins: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k not in ("DRY_RUN", "HESTIA_WORKSPACE")}
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--plugins", str(plugins), "--home", str(tmp), *args],
                          capture_output=True, text=True, env=e)


def test_thor_case_registers_only_the_missing_witness():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML)
        before = _installer_reader(cfg)
        assert "witness.py" not in before and "observe.sh" in before, before

        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "REGISTERED codex: PostToolUse/witness.py" in r.stdout, r.stdout
        # exactly one registration, and nothing already present was touched
        assert r.stdout.count("REGISTERED codex") == 1, r.stdout
        after = cfg.read_text()
        assert after.startswith(CODEX_TOML), "existing content was rewritten or reordered"
        assert "python3 " + str(tmp / ".codex" / "hooks" / "witness.py") in after, after
        assert "@HESTIA" not in after, "an unrendered placeholder reached the config"
        assert (tmp / ".codex" / "config.toml.pre-register.bak").read_text() == CODEX_TOML

        # the installer's own reader now sees the witness: install-members will install it
        assert "witness.py" in _installer_reader(cfg)
        # and the result parses as TOML on an interpreter that can check
        try:
            import tomllib
            data = tomllib.loads(after)
            posts = data["hooks"]["PostToolUse"]
            cmds = [h["command"] for g in posts for h in g["hooks"]]
            assert any(c.endswith("witness.py") for c in cmds) and any(c.endswith("observe.sh") for c in cmds), cmds
            assert data["features"]["codex_hooks"] is True
        except ImportError:
            pass

        # idempotent: a second run is a byte-identical no-op
        r2 = _run(tmp, plugins, "--member", "codex")
        assert r2.returncode == 0 and "ok    codex" in r2.stdout, r2.stdout
        assert cfg.read_text() == after


KIMI_TOML = """default_model = "kimi"

[[hooks]]
event = "SessionStart"
command = "/HOME/.kimi-code/hooks/observe.sh"
timeout = 15

[[hooks]]
event = "PostToolUse"
command = "/HOME/.kimi-code/hooks/observe.sh"
timeout = 10

[[hooks]]
event = "PostToolUseFailure"
command = "/HOME/.kimi-code/hooks/observe.sh"
timeout = 10

[[hooks]]
event = "SessionEnd"
command = "/HOME/.kimi-code/hooks/observe.sh"
timeout = 10

[[hooks]]
event = "SessionEnd"
command = "/HOME/.kimi-code/hooks/hydrate.sh"
timeout = 20

[[hooks]]
event = "PostToolUse"
command = "HESTIA_PLUGIN_ID=kimi-code python3 /HOME/.kimi-code/hooks/witness.py"
timeout = 10

[[hooks]]
command = "python3 /HOME/.kimi-code/hooks/pre_tool_use.py"
event = "PreToolUse"
timeout = 15
"""


def test_kimi_flat_layout_registers_the_failure_witness_only():
    """kimi's config is flat `[[hooks]] event = ...` tables. The seat already ran a witness on
    PostToolUse (its private fork, at the installed path) but none on PostToolUseFailure — the
    event kimi fires INSTEAD of PostToolUse for a failed call — so no failed kimi act was ever
    witnessed. Registration must see what is there (keys in either order) and add only that."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        (plugins / "kimi" / "hooks").mkdir(parents=True)
        (plugins / "kimi" / "expects.json").write_text((REPO / "plugins" / "kimi" / "expects.json").read_text())
        (plugins / "kimi" / "hooks" / "hooks.json").write_text(
            (REPO / "plugins" / "kimi" / "hooks" / "hooks.json").read_text())
        cfg = tmp / ".kimi-code" / "config.toml"
        cfg.parent.mkdir()
        before = KIMI_TOML.replace("/HOME", str(tmp))
        cfg.write_text(before)
        r = _run(tmp, plugins, "--member", "kimi")
        assert r.returncode == 0, r.stdout + r.stderr
        added = sorted(ln.split(": ", 1)[1] for ln in r.stdout.splitlines()
                       if ln.strip().startswith("REGISTERED kimi"))
        assert "PostToolUseFailure/witness.py" in r.stdout, r.stdout
        assert "PostToolUse/witness.py" not in r.stdout.replace("PostToolUseFailure/witness.py", ""), r.stdout
        assert "PreToolUse/pre_tool_use.py" not in r.stdout, "a key-order-swapped table was not read"
        after = cfg.read_text()
        assert after.startswith(before), "existing content was rewritten or reordered"
        assert "[[hooks.PostToolUseFailure" not in after, "wrote codex's nested layout into kimi's flat file"
        try:
            import tomllib
            data = tomllib.loads(after)
            evs = [(h["event"], h["command"].split()[-1].rsplit("/", 1)[-1]) for h in data["hooks"]]
            assert ("PostToolUseFailure", "witness.py") in evs, evs
        except ImportError:
            pass
        r2 = _run(tmp, plugins, "--member", "kimi")
        assert r2.returncode == 0 and "REGISTERED" not in r2.stdout, r2.stdout
        assert cfg.read_text() == after, "a second run was not a no-op"
        assert added == ["PostToolUseFailure/witness.py"], added


def test_ensure_adds_the_feature_flag_when_absent():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text('approval_policy = "on-request"\n')     # no [features], no hooks at all
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0, r.stdout + r.stderr
        text = cfg.read_text()
        assert re.search(r"^\[features\]\n\ncodex_hooks = true|^\[features\]\ncodex_hooks = true", text, re.M) or \
            "codex_hooks = true" in text, text
        assert "ensure [features] codex_hooks = true" in r.stdout, r.stdout
        for base in ("pre_tool_use.py", "observe.sh", "witness.py", "hydrate.sh"):
            assert base in _installer_reader(cfg), base
        try:
            import tomllib
            tomllib.loads(text)
        except ImportError:
            pass


def test_json_member_merges_without_disturbing_other_keys():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        # claude-code ships no hooks.json template in this repo: give the fixture one, in the
        # same shape codex's has, so the JSON path is exercised end to end.
        tpl = {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
                "command": "python3 @HESTIA_PLUGIN_ROOT@/claude-code/hooks/pre_tool_use.py", "timeout": 15}]}],
                         "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
                "command": "python3 @HESTIA_PLUGIN_ROOT@/claude-code/hooks/witness.py", "timeout": 10}]}]}}
        (plugins / "claude-code" / "hooks" / "hooks.json").write_text(json.dumps(tpl))
        cfg = tmp / ".claude" / "settings.json"
        cfg.parent.mkdir()
        existing = {"permissions": {"allow": ["Bash(ls:*)"]},
                    "hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [
                        {"type": "command", "command": "python3 /somewhere/else/pre_tool_use.py"}]}],
                              "PreCompact": [{"hooks": [{"type": "command", "command": "node /x/pre-compact.js"}]}]}}
        cfg.write_text(json.dumps(existing, indent=2))
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 0, r.stdout + r.stderr
        data = json.loads(cfg.read_text())
        assert data["permissions"] == existing["permissions"]
        assert data["hooks"]["PreCompact"] == existing["hooks"]["PreCompact"]
        # the gate was already registered (by basename, at a different path): left alone
        assert data["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
        assert "PreToolUse/pre_tool_use.py" not in r.stdout
        posts = [h["command"] for g in data["hooks"]["PostToolUse"] for h in g["hooks"]]
        assert posts == ["python3 " + str(tmp / ".claude" / "hooks" / "hestia" / "witness.py")], posts
        r2 = _run(tmp, plugins, "--member", "claude-code")
        assert "ok    claude-code" in r2.stdout and json.loads(cfg.read_text()) == data


def test_a_harness_not_on_this_host_is_not_minted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)          # no ~/.codex here
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0 and "skip  codex" in r.stdout and "not on this host" in r.stdout, r.stdout
        assert not (tmp / ".codex").exists()


def test_unrendered_placeholder_refuses():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        t = json.loads((plugins / "codex" / "hooks" / "hooks.json").read_text())
        t["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = "@SOMEONE_FORGOT@/observe.sh"
        (plugins / "codex" / "hooks" / "hooks.json").write_text(json.dumps(t))
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML)
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 7 and "REFUSED codex" in r.stdout, (r.returncode, r.stdout)
        assert cfg.read_text() == CODEX_TOML


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML)
        r = _run(tmp, plugins, "--member", "codex", env={"DRY_RUN": "1"})
        assert r.returncode == 0 and "would codex: would add PostToolUse/witness.py" in r.stdout, r.stdout
        assert cfg.read_text() == CODEX_TOML
        assert not (tmp / ".codex" / "config.toml.pre-register.bak").exists()
        assert not (tmp / ".codex" / "hooks").exists(), "DRY_RUN made a directory"


def test_workspace_placeholder_renders_from_env_or_drops():
    dest = "/home/u/.codex/hooks"
    c = "HESTIA_WORKSPACE=@HESTIA_WORKSPACE@ python3 @HESTIA_PLUGIN_ROOT@/codex/hooks/pre_tool_use.py"
    saved = os.environ.pop("HESTIA_WORKSPACE", None)
    try:
        assert RM.render_command(c, "codex", dest) == f"python3 {dest}/pre_tool_use.py"
        os.environ["HESTIA_WORKSPACE"] = "/w"
        assert RM.render_command(c, "codex", dest) == f"HESTIA_WORKSPACE=/w python3 {dest}/pre_tool_use.py"
    finally:
        os.environ.pop("HESTIA_WORKSPACE", None)
        if saved is not None:
            os.environ["HESTIA_WORKSPACE"] = saved


def test_a_member_without_a_template_is_named_as_still_a_hand_edit():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        (plugins / "codex" / "hooks" / "hooks.json").unlink()
        (tmp / ".codex").mkdir()
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0 and "ships no hooks/hooks.json template" in r.stdout, r.stdout



def test_a_failed_write_restores_what_this_run_read_not_the_first_backup():
    """The restore used to copy `.pre-register.bak`, which is written only on the FIRST run ever:
    a failure later would roll the harness config back past every edit made since."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML)
        (tmp / ".codex" / "config.toml.pre-register.bak").write_text("# STALE: the config of weeks ago\n")
        spec = json.loads((plugins / "codex" / "expects.json").read_text())["install"]
        template = json.loads((plugins / "codex" / "hooks" / "hooks.json").read_text())
        calls = []
        orig = RM.validate_toml
        RM.validate_toml = lambda text: calls.append(1) or (None if len(calls) == 1 else "forced: after-write parse failure")
        try:
            verdict, changes = RM.register_member("codex", spec, template, str(tmp), False)
        finally:
            RM.validate_toml = orig
        assert verdict == "failed" and "restored as it was" in changes[0], (verdict, changes)
        assert cfg.read_text() == CODEX_TOML, "restored something other than what this run read"
        assert not list(cfg.parent.glob(".config.toml.register-tmp")), "a temp file was left behind"


def test_a_write_keeps_the_config_file_mode():
    """~/.codex/config.toml is 0600; an atomic replace from a fresh temp file must not loosen it."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML)
        os.chmod(cfg, 0o600)
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0 and "REGISTERED codex" in r.stdout, r.stdout + r.stderr
        assert (os.stat(cfg).st_mode & 0o777) == 0o600, oct(os.stat(cfg).st_mode & 0o777)

def test_the_hooks_dir_it_registers_into_is_made():
    """HUB, 2026-09-28: ~/.codex existed, ~/.codex/hooks never had. The script registered every
    hook there and install-members.sh then died — "registered at … but … does not exist" — which
    stopped the WHOLE members' install, so the manifest was never written on any cycle after."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text('[projects."/w"]\ntrust_level = "trusted"\n')
        hooks = tmp / ".codex" / "hooks"
        assert not hooks.exists()
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0, r.stdout + r.stderr
        assert hooks.is_dir(), "registered into a directory nobody made: " + r.stdout
        # every path the installer will now read resolves to a directory that exists
        for b in _installer_reader(cfg):
            assert (hooks / b).parent.is_dir(), b


def test_a_host_already_left_registered_without_the_dir_repairs():
    """The state the bug left behind: registration present (so the merge is a no-op) and the
    directory still absent. The `ok` arm must make it too, or the host never recovers."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text("")
        assert _run(tmp, plugins, "--member", "codex").returncode == 0
        registered = cfg.read_text()
        shutil.rmtree(tmp / ".codex" / "hooks", ignore_errors=True)
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0 and (tmp / ".codex" / "hooks").is_dir(), r.stdout
        assert "made  codex" in r.stdout, r.stdout
        assert cfg.read_text() == registered, "a repair rewrote the registration"
        # and once it exists, the run is the plain no-op again
        again = _run(tmp, plugins, "--member", "codex").stdout
        assert "ok    codex" in again and "made" not in again, again


TESTS = [
    test_thor_case_registers_only_the_missing_witness,
    test_kimi_flat_layout_registers_the_failure_witness_only,
    test_ensure_adds_the_feature_flag_when_absent,
    test_json_member_merges_without_disturbing_other_keys,
    test_a_harness_not_on_this_host_is_not_minted,
    test_unrendered_placeholder_refuses,
    test_dry_run_writes_nothing,
    test_workspace_placeholder_renders_from_env_or_drops,
    test_a_member_without_a_template_is_named_as_still_a_hand_edit,
    test_a_failed_write_restores_what_this_run_read_not_the_first_backup,
    test_a_write_keeps_the_config_file_mode,
    test_the_hooks_dir_it_registers_into_is_made,
    test_a_host_already_left_registered_without_the_dir_repairs,
]

if __name__ == "__main__":
    # the explicit list is compared against what the module defines, so a test added and not listed is
    # RED here rather than a silently smaller run (tools/ci_selfexec_test.py, the idiom from claimable_test)
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"TESTS list is stale: defined-not-listed {sorted(defined - listed)}, listed-not-defined {sorted(listed - defined)}")
        sys.exit(1)
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"ok    {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
