"""Codex must execute installed shared law, never an implicit worktree fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "plugins/codex/hooks/pre_tool_use.py"


def write_engine(root: Path, sentinel: str) -> None:
    root.mkdir(parents=True)
    (root / "hestia_gate_core.py").write_text(
        "SENTINEL = " + repr(sentinel) + "\n"
        "READ_CLASS = frozenset()\n"
        "class HarnessProfile:\n"
        "    def __init__(self, **kwargs): self.kwargs = kwargs\n",
        encoding="utf-8",
    )
    (root / "hestia_gate_mechanism.py").write_text(
        "SENTINEL = " + repr(sentinel) + "\n"
        "def peer_core_sentinel():\n"
        "    from hestia_gate_core import SENTINEL\n"
        "    return SENTINEL\n",
        encoding="utf-8",
    )
    (root / "hestia_governance_closure.py").write_text(
        "def classify(*args, **kwargs): return None\n", encoding="utf-8")


def load_probe(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    code = (
        "import importlib.util, sys; "
        f"s=importlib.util.spec_from_file_location('codex_gate', {str(HOOK)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(m._core.SENTINEL); print(m._load_mechanism().SENTINEL); "
        "print(m._closure_classify is not None); "
        "sys.modules.pop('hestia_gate_core', None); "
        "print(m._load_mechanism().peer_core_sentinel())"
    )
    return subprocess.run([sys.executable, "-I", "-c", code], env=env,
                          text=True, capture_output=True, check=False)


def test_installed_engine_wins_over_workspace_decoy() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home/shared"
        decoy = root / "workspace/hestia/plugins/_shared"
        write_engine(installed, "installed")
        write_engine(decoy, "working-tree-decoy")
        env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"),
                   HESTIA_WORKSPACE=str(root / "workspace"))
        env.pop("HESTIA_SHARED_DIR", None)
        run = load_probe(env)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == [
            "installed", "installed", "True", "installed"
        ], run.stdout


def test_explicit_shared_dir_is_the_selected_authority() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        explicit = root / "reviewed-fixture"
        installed = root / "hestia-home/shared"
        write_engine(explicit, "explicit")
        write_engine(installed, "home")
        env = dict(os.environ, HESTIA_SHARED_DIR=str(explicit),
                   HESTIA_HOME=str(root / "hestia-home"))
        run = load_probe(env)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == [
            "explicit", "explicit", "True", "explicit"
        ], run.stdout


def test_missing_install_never_falls_back_and_hook_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        workspace = root / "workspace"
        decoy = workspace / "hestia/plugins/_shared"
        write_engine(decoy, "working-tree-decoy")
        env = dict(os.environ, HESTIA_HOME=str(root / "missing-hestia-home"),
                   HESTIA_WORKSPACE=str(workspace), HESTIA_CODEX_GATE_MODE="enforce")
        env.pop("HESTIA_SHARED_DIR", None)
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": str(workspace / "ordinary.txt")},
            "cwd": str(workspace),
            "session_id": "installed-loader-test",
        }
        run = subprocess.run([sys.executable, "-I", str(HOOK)], env=env,
                             input=json.dumps(event), text=True, capture_output=True,
                             check=False)
        assert run.returncode == 2, (run.stdout, run.stderr)
        assert "shared gate core could not be loaded" in run.stderr, run.stderr
        assert "working-tree-decoy" not in run.stdout + run.stderr


def test_preloaded_wrong_origin_modules_cannot_become_authority() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home/shared"
        write_engine(installed, "installed")
        env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"))
        env.pop("HESTIA_SHARED_DIR", None)
        code = (
            "import importlib.util, os, sys, types; "
            "names=('hestia_gate_core','hestia_gate_mechanism','hestia_governance_closure'); "
            "[(lambda m,n: (setattr(m,'__file__','/tmp/worktree-decoy/'+n+'.py'), "
            "sys.modules.__setitem__(n,m)))(types.ModuleType(n),n) for n in names]; "
            f"s=importlib.util.spec_from_file_location('codex_gate', {str(HOOK)!r}); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m._core.SENTINEL); print(m._load_mechanism().SENTINEL); "
            "print(m._closure_classify is not None); "
            "print(os.path.realpath(sys.modules['hestia_governance_closure'].__file__))"
        )
        run = subprocess.run([sys.executable, "-I", "-c", code], env=env,
                             text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        lines = run.stdout.splitlines()
        assert lines[:3] == ["installed", "installed", "True"], run.stdout
        assert lines[3] == str((installed / "hestia_governance_closure.py").resolve()), run.stdout


def test_selected_module_baseexception_fails_closed() -> None:
    for raised in ("SystemExit(0)", "KeyboardInterrupt()"):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            selected = root / "selected-shared"
            workspace = root / "workspace"
            write_engine(selected, "selected")
            (selected / "hestia_gate_core.py").write_text(
                f"raise {raised}\n", encoding="utf-8")
            env = dict(os.environ, HESTIA_SHARED_DIR=str(selected),
                       HESTIA_WORKSPACE=str(workspace), HESTIA_CODEX_GATE_MODE="enforce")
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": str(workspace / "ordinary.txt")},
                "cwd": str(workspace),
                "session_id": "installed-loader-baseexception-test",
            }
            run = subprocess.run([sys.executable, "-I", str(HOOK)], env=env,
                                 input=json.dumps(event), text=True, capture_output=True,
                                 check=False)
            assert run.returncode == 2, (raised, run.stdout, run.stderr)
            assert "shared gate core could not be loaded" in run.stderr, (
                raised, run.stderr)
            assert "Traceback" not in run.stderr, (raised, run.stderr)


def test_no_implicit_workspace_loader_spelling_remains() -> None:
    src = HOOK.read_text(encoding="utf-8")
    assert 'os.path.join(WORKSPACE, "hestia", "plugins", "_shared")' not in src
    assert 'os.environ.get("HESTIA_SHARED_DIR")' in src
    assert 'os.environ.get("HESTIA_HOME", "~/.hestia")' in src


if __name__ == "__main__":
    test_installed_engine_wins_over_workspace_decoy()
    test_explicit_shared_dir_is_the_selected_authority()
    test_missing_install_never_falls_back_and_hook_fails_closed()
    test_preloaded_wrong_origin_modules_cannot_become_authority()
    test_selected_module_baseexception_fails_closed()
    test_no_implicit_workspace_loader_spelling_remains()
    print("ok: Codex loader is pinned to the selected installed shared engine")
