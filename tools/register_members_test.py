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
import shutil
import os
import re
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


DEST = {"codex": (".codex", "hooks"), "claude-code": (".claude", "hooks", "hestia"), "kimi": (".kimi-code", "hooks")}


def _install(tmp: Path, member: str, *bases: str) -> Path:
    """Stand in for install-members.sh's file install: put the named hook files at the member's
    declared dest, so the registrar -- which never registers a target that is not on disk -- will."""
    d = tmp.joinpath(*DEST[member])
    d.mkdir(parents=True, exist_ok=True)
    for b in bases:
        (d / b).write_text(f"# installed {b}\n")
    return d


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
        _install(tmp, "codex", "witness.py")

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
        # the seat's hooks are installed (the registrar registers nothing that is not on disk, #1142)
        _install(tmp, "kimi", "observe.sh", "hydrate.sh", "witness.py", "pre_tool_use.py")
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
        _install(tmp, "codex", "pre_tool_use.py", "observe.sh", "witness.py", "hydrate.sh")
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
        _install(tmp, "claude-code", "witness.py")
        r = _run(tmp, plugins, "--member", "claude-code")
        # One-gate stage C: the gate's existing registration declares NO timeout, which the
        # registrar now reports SHORT (exit 10) — the gate's bound should be explicit. It is a
        # report: nothing about the registration is rewritten without --raise-timeouts.
        assert r.returncode == 10, r.stdout + r.stderr
        assert "SHORT claude-code: PreToolUse/pre_tool_use.py is registered with timeout None" in r.stdout
        data = json.loads(cfg.read_text())
        assert data["permissions"] == existing["permissions"]
        assert data["hooks"]["PreCompact"] == existing["hooks"]["PreCompact"]
        # the gate was already registered (by basename, at a different path): left alone
        assert data["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
        assert "REGISTERED claude-code: PreToolUse/pre_tool_use.py" not in r.stdout
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
        _install(tmp, "codex", "witness.py")
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
        _install(tmp, "codex", "witness.py")
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0 and "REGISTERED codex" in r.stdout, r.stdout + r.stderr
        assert (os.stat(cfg).st_mode & 0o777) == 0o600, oct(os.stat(cfg).st_mode & 0o777)

def test_claude_code_template_registers_the_gate_and_law_inject_beside_an_existing_witness():
    """thor 2026-09-28: settings.json carried only the PostToolUse witness (the daemon's merge) plus the
    inventory on SessionStart; the gate and law_inject were hand edits. The shipped template must add
    exactly those two, by basename, and leave the witness, the inventory line and unrelated keys alone."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)          # copies the REAL claude-code template
        assert (plugins / "claude-code" / "hooks" / "hooks.json").exists(), "the claude-code template must ship"
        cfg = tmp / ".claude" / "settings.json"
        cfg.parent.mkdir()
        existing = {"permissions": {"allow": ["Bash(ls:*)"]},
                    "hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
                                  {"type": "command", "command": "python3 /elsewhere/hestia/witness.py", "timeout": 3}]}],
                              "SessionStart": [{"hooks": [
                                  {"type": "command", "command": "/home/u/.local/bin/hestia-agent-inventory --workspace /w --brief", "timeout": 20}]}]}}
        cfg.write_text(json.dumps(existing, indent=2))
        _install(tmp, "claude-code", "pre_tool_use.py", "law_inject.py")
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "REGISTERED claude-code: PreToolUse/pre_tool_use.py" in r.stdout, r.stdout
        assert "REGISTERED claude-code: SessionStart/law_inject.py" in r.stdout, r.stdout
        assert "PostToolUse/witness.py" not in r.stdout, "the witness was already registered (at another path) and must not be duplicated"
        data = json.loads(cfg.read_text())
        assert data["permissions"] == existing["permissions"]
        dest = tmp / ".claude" / "hooks" / "hestia"
        pre = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
        assert pre == [f"python3 {dest}/pre_tool_use.py"], pre
        assert data["hooks"]["PreToolUse"][0]["matcher"] == "*"
        posts = [h["command"] for g in data["hooks"]["PostToolUse"] for h in g["hooks"]]
        assert posts == ["python3 /elsewhere/hestia/witness.py"], posts
        starts = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
        assert starts[0].startswith("/home/u/.local/bin/hestia-agent-inventory") and starts[1] == f"python3 {dest}/law_inject.py", starts
        assert "@HESTIA" not in cfg.read_text()
        r2 = _run(tmp, plugins, "--member", "claude-code")
        assert "ok    claude-code" in r2.stdout and json.loads(cfg.read_text()) == data


def test_claude_code_template_on_an_empty_settings_registers_all_three_once_installed():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        (tmp / ".claude").mkdir()
        _install(tmp, "claude-code", "pre_tool_use.py", "witness.py", "law_inject.py")
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 0, r.stdout + r.stderr
        data = json.loads((tmp / ".claude" / "settings.json").read_text())
        got = {ev: [h["command"].split("/")[-1] for g in gs for h in g["hooks"]] for ev, gs in data["hooks"].items()}
        assert got == {"PreToolUse": ["pre_tool_use.py"], "PostToolUse": ["witness.py"], "SessionStart": ["law_inject.py"]}, got


def test_a_target_not_on_disk_is_pending_never_registered():
    """#1142 review, case 1: registration used to write commands into ~/.claude/hooks/hestia on a
    host where nothing had created it, and install-members.sh then died on the missing directory,
    leaving live registrations pointing at nothing. A target that is not on disk is PENDING."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        (tmp / ".claude").mkdir()
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 9, (r.returncode, r.stdout)
        assert r.stdout.count("PENDING claude-code") == 3 and "REGISTERED" not in r.stdout, r.stdout
        assert "every templated hook is registered" not in r.stdout
        assert not (tmp / ".claude" / "settings.json").exists(), "a registration was written for files that do not exist"


def test_plan_names_every_hook_to_add_with_its_target():
    """install-members.sh reads this to install BEFORE registering: member<TAB>basename<TAB>target."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        (tmp / ".claude").mkdir()
        r = _run(tmp, plugins, "--member", "claude-code", "--plan")
        assert r.returncode == 0, r.stdout + r.stderr
        rows = [ln.split("\t") for ln in r.stdout.splitlines() if ln.strip()]
        dest = str(tmp / ".claude" / "hooks" / "hestia")
        want = [["claude-code", b, f"{dest}/{b}"] for b in ("pre_tool_use.py", "witness.py", "law_inject.py")]
        assert sorted(rows) == sorted(want), rows
        assert not (tmp / ".claude" / "settings.json").exists() and not (tmp / ".claude" / "hooks").exists(), "--plan wrote something"


def test_a_read_only_gate_is_reported_narrow_not_registered():
    """#1142 review, case 2: an existing PreToolUse gate with matcher 'Read' was reported as 'every
    templated hook is registered' and left as it was. The all-tools gate is NOT wired; say so."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        dest = _install(tmp, "claude-code", "pre_tool_use.py", "witness.py", "law_inject.py")
        cfg = tmp / ".claude" / "settings.json"
        narrow = {"hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [
            {"type": "command", "command": f"python3 {dest}/pre_tool_use.py", "timeout": 10}]}]}}
        cfg.write_text(json.dumps(narrow, indent=2))
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 8, (r.returncode, r.stdout)
        assert "NARROW claude-code: PreToolUse/pre_tool_use.py is registered only for matcher 'Read'" in r.stdout, r.stdout
        assert "every templated hook is registered" not in r.stdout, r.stdout
        data = json.loads(cfg.read_text())
        assert data["hooks"]["PreToolUse"] == narrow["hooks"]["PreToolUse"], "the narrow gate was silently rewritten"
        # the other two hooks, which are not narrow, still register
        assert "REGISTERED claude-code: PostToolUse/witness.py" in r.stdout, r.stdout
        assert "REGISTERED claude-code: SessionStart/law_inject.py" in r.stdout, r.stdout


def test_a_narrow_toml_matcher_is_read_from_its_group():
    """The TOML reader takes the matcher from the GROUP header, not the `.hooks` entry header."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML.replace('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\nmatcher = "shell"'))
        _install(tmp, "codex", "witness.py")
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 8, (r.returncode, r.stdout)
        assert "NARROW codex: PreToolUse/pre_tool_use.py is registered only for matcher 'shell'" in r.stdout, r.stdout
        assert "REGISTERED codex: PostToolUse/witness.py" in r.stdout, r.stdout


def test_an_inline_comment_on_a_narrow_toml_matcher_is_still_narrow():
    """#1142 re-review P1: `matcher = "shell" # deliberately narrow` was not recognised by the line scan,
    the matcher stayed None (all tools), and the second run certified 'every templated hook is registered'."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(CODEX_TOML.replace('[[hooks.PreToolUse]]\nmatcher = ".*"',
                                          '[[hooks.PreToolUse]]\nmatcher = "shell" # deliberately narrow'))
        _install(tmp, "codex", "witness.py")
        for run in (1, 2):
            r = _run(tmp, plugins, "--member", "codex")
            assert r.returncode == 8, (run, r.returncode, r.stdout)
            assert "NARROW codex: PreToolUse/pre_tool_use.py is registered only for matcher 'shell'" in r.stdout, r.stdout
            assert "every templated hook is registered" not in r.stdout, (run, r.stdout)
        assert 'matcher = "shell" # deliberately narrow' in cfg.read_text(), "the narrow gate was rewritten"


def test_the_fallback_line_scan_cannot_widen_a_matcher():
    """The line scan (hosts without tomllib) reads inline comments and escapes, and a matcher line it
    cannot decode is UNPARSED -- which covers nothing, never all tools."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        body = ('[[hooks.PreToolUse]]\n{m}\n\n[[hooks.PreToolUse.hooks]]\ntype = "command"\n'
                'command = "python3 /x/pre_tool_use.py" # the gate\n')
        old = RM.FORCE_LINE_SCAN
        RM.FORCE_LINE_SCAN = True
        try:
            cases = {
                'matcher = "shell" # narrow': "shell",
                "matcher = 'Read'   # literal string": "Read",
                'matcher = "sh\\"ell"': 'sh"ell',
                'matcher = ".*"': ".*",
            }
            for line, want in cases.items():
                p.write_text(body.format(m=line))
                got = RM.registered_toml(str(p))
                assert got == {"PreToolUse": {"pre_tool_use.py": [want]}}, (line, got)
            p.write_text(body.format(m="matcher = shell"))               # not a TOML string: undecodable
            try:
                RM.registered_toml(str(p))
                raise AssertionError("an undecodable matcher was read instead of refused")
            except RM.TomlUnsupported:
                pass
            assert not RM.covers(RM.UNPARSED, "*") and not RM.covers(RM.UNPARSED, "Read")
        finally:
            RM.FORCE_LINE_SCAN = old
        # the structural reader agrees on every decodable case
        for line, want in cases.items():
            p.write_text(body.format(m=line))
            assert RM.registered_toml(str(p)) == {"PreToolUse": {"pre_tool_use.py": [want]}}, (line, "structural")


def test_quoted_keys_are_read_through_the_fallback_path():
    """#1142 third review: `"matcher" = "shell"` is valid TOML; the fallback recorded [None] (all tools)
    and certified the narrow gate. Through the COMPOSED registration path with the fallback forced
    (--toml-line-scan), both quoted-key spellings and a quoted header segment are NARROW on every run,
    and the structural reader agrees."""
    variants = {
        "double-quoted key": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\n"matcher" = "shell"'),
        "literal-quoted key": ('[[hooks.PreToolUse]]\nmatcher = ".*"', "[[hooks.PreToolUse]]\n'matcher' = 'shell'"),
        "quoted header": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks."PreToolUse"]]\nmatcher = "shell"'),
    }
    for name, (a, b) in variants.items():
        for scan in (["--toml-line-scan"], []):
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                plugins = _plugins(tmp)
                cfg = tmp / ".codex" / "config.toml"
                cfg.parent.mkdir()
                text = CODEX_TOML.replace(a, b)
                if name == "quoted header":
                    text = text.replace("[[hooks.PreToolUse.hooks]]", '[[hooks."PreToolUse".hooks]]', 1)
                assert text != CODEX_TOML, name
                cfg.write_text(text)
                _install(tmp, "codex", "witness.py")
                for run in (1, 2):
                    r = _run(tmp, plugins, "--member", "codex", *scan)
                    assert r.returncode == 8, (name, scan, run, r.returncode, r.stdout)
                    assert "is registered only for matcher 'shell'" in r.stdout, (name, scan, r.stdout)
                    assert "every templated hook is registered" not in r.stdout, (name, scan, r.stdout)


def test_the_fallback_refuses_toml_it_cannot_verify():
    """Anything outside the fallback's grammar that could bear on hooks is REFUSED (rc 7), never read as
    absence -- absence is all-tools. The config is left untouched and nothing is certified."""
    entry = '[[hooks.PreToolUse.hooks]]\ntype          = "command"'
    forms = {
        "inline array of hook entries": CODEX_TOML.replace(
            '[[hooks.PreToolUse]]\nmatcher = ".*"\n',
            '[[hooks.PreToolUse]]\nmatcher = "shell"\nhooks = [ { type = "command", command = "python3 /x/pre_tool_use.py" } ]\n'),
        "dotted key in a hooks table": CODEX_TOML.replace('matcher = ".*"', 'matcher.x = "shell"', 1),
        "multi-line string anywhere": CODEX_TOML + '\n[notes]\ntext = """\n[[hooks.PreToolUse]]\nmatcher = "*"\n"""\n',
        "a [hooks] table": CODEX_TOML + '\n[hooks]\nPreToolUse = []\n',
    }
    for name, text in forms.items():
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            plugins = _plugins(tmp)
            cfg = tmp / ".codex" / "config.toml"
            cfg.parent.mkdir()
            cfg.write_text(text)
            _install(tmp, "codex", "witness.py")
            r = _run(tmp, plugins, "--member", "codex", "--toml-line-scan")
            assert r.returncode == 7 and "REFUSED codex" in r.stdout, (name, r.returncode, r.stdout)
            assert "every templated hook is registered" not in r.stdout and "REGISTERED" not in r.stdout, (name, r.stdout)
            assert cfg.read_text() == text, name


def test_the_left_behind_repair_also_works_through_the_fallback():
    """registered_targets() reads targets with the scan when there is no tomllib, so a host left
    registered without its files is PENDING (not ok) through the fallback too."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text("")
        rows = _plan_rows(tmp, plugins, "codex")
        _install(tmp, "codex", *[b for b, _ in rows])
        assert _run(tmp, plugins, "--member", "codex", "--toml-line-scan").returncode == 0
        shutil.rmtree(tmp / ".codex" / "hooks")
        r = _run(tmp, plugins, "--member", "codex", "--toml-line-scan")
        assert r.returncode == 9 and r.stdout.count("is registered but") == len(rows), r.stdout


def test_a_narrow_kimi_flat_matcher_is_narrow_in_both_readers():
    """#1149's flat reader kept no matchers, so a kimi `[[hooks]]` gate with `matcher = "Shell"` read as
    all-tools -- the same false completeness as #1142's reviews. Flat tables carry their matcher now,
    in the structural reader and in the fallback, quoted key or not."""
    for spelling in ('matcher = "Shell"', '"matcher" = "Shell" # narrow'):
        for scan in (["--toml-line-scan"], []):
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                plugins = _plugins(tmp)
                (plugins / "kimi" / "hooks").mkdir(parents=True)
                (plugins / "kimi" / "expects.json").write_text((REPO / "plugins" / "kimi" / "expects.json").read_text())
                (plugins / "kimi" / "hooks" / "hooks.json").write_text(
                    (REPO / "plugins" / "kimi" / "hooks" / "hooks.json").read_text())
                cfg = tmp / ".kimi-code" / "config.toml"
                cfg.parent.mkdir()
                text = KIMI_TOML.replace("/HOME", str(tmp)).replace(
                    'event = "PreToolUse"', 'event = "PreToolUse"\n' + spelling)
                cfg.write_text(text)
                _install(tmp, "kimi", "observe.sh", "hydrate.sh", "witness.py", "pre_tool_use.py")
                r = _run(tmp, plugins, "--member", "kimi", *scan)
                assert r.returncode == 8, (spelling, scan, r.returncode, r.stdout)
                assert "PreToolUse/pre_tool_use.py is registered only for matcher 'Shell'" in r.stdout, (spelling, scan, r.stdout)


def test_escaped_toml_spellings_are_decoded_or_refused():
    r"""#1142 fourth review: `"\U0000006datcher" = "shell"` is valid TOML for `matcher`. The fallback decoded
    basic strings with JSON (no \U escape), got the raw spelling back, and certified the narrow gate on the
    second run. Every escaped spelling of the key or of a header segment must come out NARROW (rc 8) on every
    run, through the composed path with the fallback forced AND with tomllib, and an escape TOML does not
    define must be REFUSED (rc 7) by both readers -- never a false `ok`."""
    narrow = {
        "U escape in key": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\n"\\U0000006datcher" = "shell"', None),
        "u escape in key": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\n"\\u006datcher" = "shell"', None),
        "escape in value": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\nmatcher = "s\\u0068ell"', None),
        "escaped header segment": ('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks."\\u0050reToolUse"]]\nmatcher = "shell"',
                                   ("[[hooks.PreToolUse.hooks]]", '[[hooks."\\U00000050reToolUse".hooks]]')),
    }
    for name, (a, b, extra) in narrow.items():
        for scan in (["--toml-line-scan"], []):
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                plugins = _plugins(tmp)
                cfg = tmp / ".codex" / "config.toml"
                cfg.parent.mkdir()
                text = CODEX_TOML.replace(a, b, 1)
                if extra:
                    text = text.replace(extra[0], extra[1], 1)
                assert text != CODEX_TOML, name
                cfg.write_text(text)
                _install(tmp, "codex", "witness.py")
                for run in (1, 2):
                    r = _run(tmp, plugins, "--member", "codex", *scan)
                    assert r.returncode == 8, (name, scan, run, r.returncode, r.stdout)
                    assert "is registered only for matcher 'shell'" in r.stdout, (name, scan, run, r.stdout)
                    assert "every templated hook is registered" not in r.stdout, (name, scan, run, r.stdout)
    refused = {
        "x escape (not TOML)": '"\\x6datcher" = "shell"',
        "surrogate code point": '"\\uD800atcher" = "shell"',
        "truncated u escape": '"\\u6d" = "shell"',
    }
    for name, line in refused.items():
        for scan in (["--toml-line-scan"], []):
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                plugins = _plugins(tmp)
                cfg = tmp / ".codex" / "config.toml"
                cfg.parent.mkdir()
                text = CODEX_TOML.replace('[[hooks.PreToolUse]]\nmatcher = ".*"', '[[hooks.PreToolUse]]\n' + line, 1)
                cfg.write_text(text)
                _install(tmp, "codex", "witness.py")
                r = _run(tmp, plugins, "--member", "codex", *scan)
                assert r.returncode == 7 and "REFUSED codex" in r.stdout, (name, scan, r.returncode, r.stdout)
                assert "every templated hook is registered" not in r.stdout and "REGISTERED" not in r.stdout, (name, scan, r.stdout)
                assert cfg.read_text() == text, (name, scan)


def test_the_strict_decoder_agrees_with_tomllib():
    """Every basic-string body TOML defines decodes as tomllib decodes it; every other one is refused."""
    import tomllib
    for body in (r"\U0000006datcher", r"\u006datcher", r"sh\"ell", r"a\tb\n", "plain", r"\\back", r"\u00e9"):
        want = next(iter(tomllib.loads('"' + body + '" = 1')))
        assert RM._toml_basic(body) == want, (body, RM._toml_basic(body), want)
    for bad in (r"\x6d", r"\U0000d800", r"\U00110000", r"\u12", "ctl\x01", "x\\"):
        try:
            RM._toml_basic(bad)
            raise AssertionError(f"not refused: {bad!r}")
        except RM.TomlUnsupported:
            pass


def test_mixed_installed_and_missing_targets_exit_pending():
    """#1142 re-review P2: with only witness.py installed, the registrar registered it, printed PENDING
    for the other two, and exited 0. The additions are reported AND the run exits 9."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        _install(tmp, "claude-code", "witness.py")
        r = _run(tmp, plugins, "--member", "claude-code")
        assert r.returncode == 9, (r.returncode, r.stdout)
        assert "REGISTERED claude-code: PostToolUse/witness.py" in r.stdout, r.stdout
        assert r.stdout.count("PENDING claude-code") == 2, r.stdout
        assert "every templated hook is registered" not in r.stdout
        data = json.loads((tmp / ".claude" / "settings.json").read_text())
        assert list(data["hooks"]) == ["PostToolUse"], data


def _plan_rows(tmp: Path, plugins: Path, member: str) -> list[tuple[str, str]]:
    r = _run(tmp, plugins, "--member", member, "--plan")
    assert r.returncode == 0, r.stdout + r.stderr
    return [tuple(ln.split("\t")[1:]) for ln in r.stdout.splitlines() if ln.startswith(member + "\t")]


def test_the_hooks_dir_it_registers_into_is_made():
    """HUB, 2026-09-28 (#1153, hub-claude): ~/.codex existed, ~/.codex/hooks never had. The registrar
    registered every hook there and install-members.sh died -- "registered at ... but ... does not exist" --
    which stopped the WHOLE members' install. Under plan -> install -> register the registrar alone
    registers NOTHING that is not on disk; the plan names every target; once the installer has put them
    there, all register and every path the installer reads resolves to a file."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        before = '[projects."/w"]\ntrust_level = "trusted"\n'
        cfg.write_text(before)
        hooks = tmp / ".codex" / "hooks"
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 9 and "REGISTERED codex: " not in r.stdout.replace("REGISTERED codex: ensure", ""), r.stdout
        assert not _installer_reader(cfg), "registered hooks that are not installed: " + cfg.read_text()
        rows = _plan_rows(tmp, plugins, "codex")
        assert rows and all(tg == str(hooks / b) for b, tg in rows), rows
        _install(tmp, "codex", *[b for b, _ in rows])            # what install-members.sh does next
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 0, r.stdout + r.stderr
        assert hooks.is_dir()
        for b in _installer_reader(cfg):
            assert (hooks / b).is_file(), b


def test_a_host_already_left_registered_without_the_dir_repairs():
    """The state #1153's bug left behind: registrations present, hooks dir gone. That is not `ok` -- a
    registration is only as good as the file it names -- so it is PENDING (rc 9) with the config left
    byte-identical, the plan lists every missing target (the installer's repair rows), and once they are
    installed the run is the plain `ok` again."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _plugins(tmp)
        cfg = tmp / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text("")
        rows = _plan_rows(tmp, plugins, "codex")
        _install(tmp, "codex", *[b for b, _ in rows])
        assert _run(tmp, plugins, "--member", "codex").returncode == 0
        registered = cfg.read_text()
        shutil.rmtree(tmp / ".codex" / "hooks")
        r = _run(tmp, plugins, "--member", "codex")
        assert r.returncode == 9, (r.returncode, r.stdout)
        assert r.stdout.count("is registered but") == len(rows), r.stdout
        assert "every templated hook is registered" not in r.stdout, r.stdout
        assert cfg.read_text() == registered, "a repair rewrote the registration"
        assert sorted(_plan_rows(tmp, plugins, "codex")) == sorted(rows), "the plan did not list the repair"
        _install(tmp, "codex", *[b for b, _ in rows])
        again = _run(tmp, plugins, "--member", "codex")
        assert again.returncode == 0 and "ok    codex" in again.stdout, again.stdout
        assert cfg.read_text() == registered


def test_install_publishes_hestia_home_as_an_exact_path():
    """#1186 (dp 2026-09-30): "that has to be part of the install globally" and "it has to be an exact
    path for the machine, hestia won't recognise $HOME". The shared witness records nothing unless
    HESTIA_HOME is in the SEAT's environment, and nothing set it: kimi and codex witnessed nothing all day.
    The installer now writes the RESOLVED absolute path to environment.d and to a marked block in
    ~/.profile (and ~/.bashrc when present), idempotently; a changed path updates the block in place."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        (home / ".bashrc").write_text("# user bashrc\nalias ll='ls -l'\n")
        want = str(Path(env["HESTIA_HOME"]).resolve())

        def run():
            p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                               text=True, env=env)
            assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
            return p.stdout + p.stderr

        run()
        envd = home / ".config" / "environment.d" / "50-hestia.conf"
        assert envd.read_text() == f"HESTIA_HOME={want}\n", envd.read_text()
        for f in (home / ".profile", home / ".bashrc"):
            text = f.read_text()
            assert f'export HESTIA_HOME="{want}"' in text, (f, text)
            assert "$HOME" not in text.split(">>> hestia")[-1] and "~/" not in text.split(">>> hestia")[-1], text
        assert "alias ll='ls -l'" in (home / ".bashrc").read_text(), "the user's own bashrc lines were lost"
        before = {f: f.read_text() for f in (home / ".profile", home / ".bashrc", envd)}
        run()                                                    # idempotent: nothing changes
        for f, b in before.items():
            assert f.read_text() == b, f"a second install changed {f}"
            assert f.read_text().count(">>> hestia") <= 1, f
        # a moved home updates the block in place (still exactly one block, the new exact path)
        moved = tmp / "hestia-home-2"
        moved.mkdir()
        env2 = dict(env, HESTIA_HOME=str(moved))
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                           text=True, env=env2)
        assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
        prof = (home / ".profile").read_text()
        assert prof.count(">>> hestia") == 1 and f'export HESTIA_HOME="{moved.resolve()}"' in prof, prof
        assert envd.read_text() == f"HESTIA_HOME={moved.resolve()}\n"


def test_install_without_a_bashrc_does_not_create_one():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                           text=True, env=env)
        assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
        assert not (home / ".bashrc").exists(), "the installer created a .bashrc the user never had"
        assert (home / ".profile").exists()


def _stub_bin(tmp: Path, os_name: str) -> tuple[Path, Path]:
    """A PATH dir whose `uname` reports `os_name` and whose `launchctl` / `systemctl` RECORD their argv, so a test
    can prove the live-session publication runs without ever touching a real session manager."""
    stub = tmp / "stub-bin"
    stub.mkdir()
    rec = tmp / "manager-calls.txt"
    real_uname = shutil.which("uname") or "/usr/bin/uname"
    (stub / "uname").write_text(
        f'#!/bin/sh\nif [ "$1" = "-s" ]; then echo {os_name}; else exec {real_uname} "$@"; fi\n')
    for tool in ("launchctl", "systemctl"):
        (stub / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{rec}"\n')
    for f in stub.iterdir():
        f.chmod(0o755)
    return stub, rec


def test_install_publishes_to_the_live_session_on_darwin_and_linux():
    """#1188 review (HOLD): the account-home lookup used `getent`, absent on macOS, so `launchctl setenv` could never
    run on the platform it exists for. With a portable lookup, and the real-home condition made true through the
    test-only seam, each OS's live-session call must be INVOKED with the exact path, against stubs, never a real
    manager."""
    for os_name, want in (("Darwin", "launchctl setenv HESTIA_HOME "), ("Linux", "systemctl --user set-environment HESTIA_HOME=")):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            root, home, env = _e2e_root(tmp)
            stub, rec = _stub_bin(tmp, os_name)
            env = dict(env, PATH=f"{stub}:{env.get('PATH', '')}", _HESTIA_TEST_ACCOUNT_HOME=str(home))
            p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                               text=True, env=env)
            assert p.returncode == 0, (os_name, (p.stdout + p.stderr)[-3000:])
            calls = rec.read_text() if rec.exists() else ""
            exact = str(Path(env["HESTIA_HOME"]).resolve())
            assert f"{want}{exact}" in calls, (os_name, calls)


def test_install_without_the_seam_never_touches_a_session_manager():
    """The safety invariant: an isolated-HOME run (HOME is not the account's real home) must not call
    launchctl or systemctl at all, even when they are on PATH."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        stub, rec = _stub_bin(tmp, "Darwin")
        env = dict(env, PATH=f"{stub}:{env.get('PATH', '')}")
        env.pop("_HESTIA_TEST_ACCOUNT_HOME", None)
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                           text=True, env=env)
        assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
        assert not rec.exists(), f"a session manager was called from an isolated HOME: {rec.read_text()}"


def test_install_refuses_a_home_path_with_shell_special_characters():
    """#1188 review: the path is written into a sourced ~/.profile and into environment.d; a `$` would be
    re-expanded when sourced. Refused explicitly, and nothing is written."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        odd = tmp / "hestia$HOME"
        odd.mkdir()
        env = dict(env, HESTIA_HOME=str(odd))
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                           text=True, env=env)
        out = p.stdout + p.stderr
        assert p.returncode != 0 and "will not write" in out, out[-2000:]
        assert not (home / ".profile").exists() or ">>> hestia" not in (home / ".profile").read_text()


def test_covers():
    assert RM.covers("*", "*") and RM.covers(None, ".*") and RM.covers(".*", "*") and RM.covers("", None)
    assert not RM.covers("Read", "*") and not RM.covers("shell", ".*")
    assert RM.covers("Read", "Read") and RM.covers("*", "Read") and not RM.covers("Write", "Read")


_SESSION_KEYS = ("CLAUDECODE", "HESTIA_ROLE", "DRY_RUN", "HESTIA_WORKSPACE", "HESTIA_SKIP_REGISTER")


def _e2e_root(tmp: Path):
    """A throwaway repo root with the REAL installer, registrar, shared engine and claude-code plugin,
    and a throwaway HOME holding only ~/.claude/ -- the reviewer's case."""
    root = tmp / "repo"
    (root / "deploy").mkdir(parents=True)
    for f in ("install-members.sh", "register-members.py"):
        shutil.copy(REPO / "deploy" / f, root / "deploy" / f)
    shutil.copytree(REPO / "plugins" / "_shared", root / "plugins" / "_shared")
    shutil.copytree(REPO / "plugins" / "claude-code", root / "plugins" / "claude-code",
                    ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
    home = tmp / "home"
    (home / ".claude").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_KEYS}
    env["HOME"] = str(home)
    env["HESTIA_HOME"] = str(tmp / "hestia-home")
    return root, home, env


def test_install_members_end_to_end_in_an_isolated_home():
    """#1142 review: 'add an end-to-end isolated-home install test.' HOME holds only ~/.claude/. The
    installer must plan, create ~/.claude/hooks/hestia, install the three files, and only then register
    them -- every registered target on disk with the plugin's bytes -- and a second run changes nothing."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True, text=True, env=env)
        out = p.stdout + p.stderr
        assert p.returncode == 0, out[-3000:]
        assert "FATAL" not in out, out[-3000:]
        dest = home / ".claude" / "hooks" / "hestia"
        for b in ("pre_tool_use.py", "witness.py", "law_inject.py"):
            assert (dest / b).read_bytes() == (REPO / "plugins" / "claude-code" / "hooks" / b).read_bytes(), b
        data = json.loads((home / ".claude" / "settings.json").read_text())
        targets = [RM.target_path(h["command"]) for gs in data["hooks"].values() for g in gs for h in g["hooks"]]
        assert sorted(os.path.basename(x) for x in targets) == ["law_inject.py", "pre_tool_use.py", "witness.py"], targets
        assert all(os.path.isfile(x) for x in targets), "a registration points at a file that is not on disk"
        assert data["hooks"]["PreToolUse"][0]["matcher"] == "*"
        assert out.index("PLAN") < out.index("wrote pre_tool_use.py") < out.index("REGISTERED claude-code"), "not plan -> install -> register"
        p2 = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True, text=True, env=env)
        out2 = p2.stdout + p2.stderr
        assert p2.returncode == 0 and "ok    claude-code — every templated hook is registered" in out2, out2[-2000:]
        assert json.loads((home / ".claude" / "settings.json").read_text()) == data


def test_install_members_reports_a_narrow_gate_and_leaves_it():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        dest = home / ".claude" / "hooks" / "hestia"
        dest.mkdir(parents=True)
        narrow = {"hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [
            {"type": "command", "command": f"python3 {dest}/pre_tool_use.py", "timeout": 10}]}]}}
        (home / ".claude" / "settings.json").write_text(json.dumps(narrow, indent=2))
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True, text=True, env=env)
        out = p.stdout + p.stderr
        assert "NARROW claude-code: PreToolUse/pre_tool_use.py" in out and "narrower than its template" in out, out[-3000:]
        assert "every templated hook is registered" not in out
        got = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
        assert got == narrow["hooks"]["PreToolUse"], got


def test_install_names_the_seat_document_step_and_never_fails_on_it():
    """#1186: the installer runs the seeder's --add-missing after the hooks, so a seat installed after the
    first seed gets its document without the operator knowing the step exists. Without an operator key it
    cannot write; it says so, prints the exact repair command, and the install still succeeds."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root, home, env = _e2e_root(tmp)
        (root / "tools").mkdir()
        shutil.copy(REPO / "tools" / "seed_seat_config.py", root / "tools" / "seed_seat_config.py")
        p = subprocess.run(["bash", str(root / "deploy" / "install-members.sh")], capture_output=True,
                           text=True, env=env)
        out = p.stdout + p.stderr
        assert p.returncode == 0, out[-3000:]
        assert "SEATS (tools/seed_seat_config.py --add-missing)" in out, out[-3000:]
        assert "no operator key at" in out and "--add-missing --apply" in out, out[-3000:]
        assert out.index("REGISTERED claude-code") < out.index("SEATS ("), "seat step must follow the hooks"


# ---- one-gate stage C: the registered timeout is the gate's bound -----------------------------
# Fixture members with NEUTRAL hook names (`gate_hook.py`): the registrar locates hooks by the
# basename its template renders, so nothing here needs a governed filename.

def _neutral_plugins(tmp: Path) -> Path:
    """Three fixture members, one per registration reader/layout, each templating gate_hook.py
    on PreToolUse at a 10 s floor."""
    p = tmp / "plugins"
    shapes = {"jseat": ([".jseat", "settings.json"], "json-hook-commands", None),
              "nseat": ([".nseat", "config.toml"], "toml-hook-commands", None),
              "fseat": ([".fseat", "config.toml"], "toml-hook-commands", "flat")}
    for m, (segs, reader, layout) in shapes.items():
        (p / m / "hooks").mkdir(parents=True)
        reg = {"reader": reader, "path": segs}
        if layout:
            reg["layout"] = layout
        (p / m / "expects.json").write_text(json.dumps({"install": {
            "member": m, "dest": f"~/{segs[0]}/hooks", "registration": reg,
            "files": ["hooks/gate_hook.py"]}}))
        (p / m / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "timeout": 10,
                                        "command": f"python3 @HESTIA_PLUGIN_ROOT@/{m}/hooks/gate_hook.py"}]}]}}))
        (tmp / segs[0] / "hooks").mkdir(parents=True)
        (tmp / segs[0] / "hooks" / "gate_hook.py").write_text("# fixture\n")
    return p


def _neutral_configs(tmp: Path, timeout: int, stray: str = "") -> None:
    h = lambda seat: f"{tmp}/.{seat}/hooks/gate_hook.py"  # noqa: E731
    (tmp / ".jseat" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": f"{stray}python3 {h('jseat')}",
                                    "timeout": timeout}]}]}}))
    (tmp / ".nseat" / "config.toml").write_text(
        f'model = "x"\n\n[[hooks.PreToolUse]]\nmatcher = "*"\n\n[[hooks.PreToolUse.hooks]]\n'
        f'type = "command"\ncommand = "{stray}python3 {h("nseat")}"\ntimeout = {timeout}\n')
    (tmp / ".fseat" / "config.toml").write_text(
        f'[[hooks]]\nevent = "PreToolUse"\ncommand = "{stray}python3 {h("fseat")}"\ntimeout = {timeout}\n'
        f'\n[[hooks]]\nevent = "SessionStart"\ncommand = "/x/other.sh"\ntimeout = 3\n')


def test_a_short_registered_timeout_is_reported_in_every_reader():
    """A templated hook registered BELOW its template's timeout is SHORT (exit 10) in JSON, nested
    TOML and flat TOML; at or above it, nothing is reported."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _neutral_plugins(tmp)
        _neutral_configs(tmp, 5)
        before = {s: (tmp / f".{s}" / n).read_text() for s, n in
                  (("jseat", "settings.json"), ("nseat", "config.toml"), ("fseat", "config.toml"))}
        r = _run(tmp, plugins)
        for seat in ("jseat", "nseat", "fseat"):
            assert f"SHORT {seat}: PreToolUse/gate_hook.py is registered with timeout 5" in r.stdout, r.stdout
        assert r.returncode == 10, (r.returncode, r.stdout)
        for s, n in (("jseat", "settings.json"), ("nseat", "config.toml"), ("fseat", "config.toml")):
            assert (tmp / f".{s}" / n).read_text() == before[s], f"{s}: a report must write nothing"
        _neutral_configs(tmp, 10)
        r = _run(tmp, plugins)
        assert "SHORT" not in r.stdout and r.returncode == 0, (r.returncode, r.stdout)


def test_raise_timeouts_raises_only_the_short_hook_and_never_lowers():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _neutral_plugins(tmp)
        _neutral_configs(tmp, 5)
        r = _run(tmp, plugins, "--raise-timeouts")
        assert r.returncode == 0, (r.returncode, r.stdout)
        j = json.loads((tmp / ".jseat" / "settings.json").read_text())
        assert j["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 10, j
        n = (tmp / ".nseat" / "config.toml").read_text()
        assert "timeout = 10" in n and "timeout = 5" not in n and 'model = "x"' in n, n
        f = (tmp / ".fseat" / "config.toml").read_text()
        assert "timeout = 10" in f and "timeout = 3" in f, f"only the gate's table moves: {f}"
        assert _run(tmp, plugins).returncode == 0
        # never lowered: a registration above the template's value is left exactly as it is
        _neutral_configs(tmp, 30)
        before = (tmp / ".nseat" / "config.toml").read_text()
        _run(tmp, plugins, "--raise-timeouts")
        assert (tmp / ".nseat" / "config.toml").read_text() == before


def test_an_untimed_registration_is_short_and_an_inert_override_is_named():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        plugins = _neutral_plugins(tmp)
        _neutral_configs(tmp, 10, stray="HESTIA_PRE_TOTAL_BUDGET_MS=14000 ")
        (tmp / ".fseat" / "config.toml").write_text(
            f'[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {tmp}/.fseat/hooks/gate_hook.py"\n')
        r = _run(tmp, plugins)
        assert "SHORT fseat: PreToolUse/gate_hook.py is registered with timeout None" in r.stdout, r.stdout
        assert "INERT jseat" in r.stdout and "HESTIA_PRE_TOTAL_BUDGET_MS=14000" in r.stdout, r.stdout
        assert "INERT nseat" in r.stdout, r.stdout
        _run(tmp, plugins, "--raise-timeouts")
        assert "timeout = 10" in (tmp / ".fseat" / "config.toml").read_text()


TESTS = [
    test_a_short_registered_timeout_is_reported_in_every_reader,
    test_raise_timeouts_raises_only_the_short_hook_and_never_lowers,
    test_an_untimed_registration_is_short_and_an_inert_override_is_named,
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
    test_claude_code_template_registers_the_gate_and_law_inject_beside_an_existing_witness,
    test_claude_code_template_on_an_empty_settings_registers_all_three_once_installed,
    test_a_target_not_on_disk_is_pending_never_registered,
    test_plan_names_every_hook_to_add_with_its_target,
    test_a_read_only_gate_is_reported_narrow_not_registered,
    test_a_narrow_toml_matcher_is_read_from_its_group,
    test_an_inline_comment_on_a_narrow_toml_matcher_is_still_narrow,
    test_the_fallback_line_scan_cannot_widen_a_matcher,
    test_quoted_keys_are_read_through_the_fallback_path,
    test_the_fallback_refuses_toml_it_cannot_verify,
    test_the_left_behind_repair_also_works_through_the_fallback,
    test_a_narrow_kimi_flat_matcher_is_narrow_in_both_readers,
    test_escaped_toml_spellings_are_decoded_or_refused,
    test_the_strict_decoder_agrees_with_tomllib,
    test_mixed_installed_and_missing_targets_exit_pending,
    test_the_hooks_dir_it_registers_into_is_made,
    test_a_host_already_left_registered_without_the_dir_repairs,
    test_install_publishes_hestia_home_as_an_exact_path,
    test_install_without_a_bashrc_does_not_create_one,
    test_install_publishes_to_the_live_session_on_darwin_and_linux,
    test_install_without_the_seam_never_touches_a_session_manager,
    test_install_refuses_a_home_path_with_shell_special_characters,
    test_covers,
    test_install_members_end_to_end_in_an_isolated_home,
    test_install_members_reports_a_narrow_gate_and_leaves_it,
    test_install_names_the_seat_document_step_and_never_fails_on_it,
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
