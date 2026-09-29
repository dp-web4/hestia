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


DEST = {"codex": (".codex", "hooks"), "claude-code": (".claude", "hooks", "hestia")}


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


TESTS = [
    test_thor_case_registers_only_the_missing_witness,
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
    test_mixed_installed_and_missing_targets_exit_pending,
    test_the_hooks_dir_it_registers_into_is_made,
    test_a_host_already_left_registered_without_the_dir_repairs,
    test_covers,
    test_install_members_end_to_end_in_an_isolated_home,
    test_install_members_reports_a_narrow_gate_and_leaves_it,
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
