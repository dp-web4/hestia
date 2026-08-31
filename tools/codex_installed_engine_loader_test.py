#!/usr/bin/env python3
"""Codex must execute the installed, attested shared engine - never branch-local law.

The 2026-08-31 one-gate audit found Codex's installed hook falling through an incomplete
~/.codex/_shared directory into the mutable repository working tree. A branch checkout
could therefore reopen classifier defects for Codex alone while Claude and Kimi continued
using $HESTIA_HOME/shared. These tests pin the authority boundary, not merely today's bytes.
"""

from __future__ import annotations

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
        "SENTINEL = " + repr(sentinel) + "\n", encoding="utf-8")
    (root / "hestia_governance_closure.py").write_text(
        "def classify(*args, **kwargs): return None\n", encoding="utf-8")


def test_installed_engine_wins_over_workspace_decoy() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home/shared"
        decoy = root / "workspace/hestia/plugins/_shared"
        write_engine(installed, "installed")
        write_engine(decoy, "working-tree-decoy")
        env = dict(
            os.environ,
            HESTIA_HOME=str(root / "hestia-home"),
            HESTIA_WORKSPACE=str(root / "workspace"),
        )
        env.pop("HESTIA_SHARED_DIR", None)
        code = (
            "import importlib.util; "
            f"s=importlib.util.spec_from_file_location('codex_gate', {str(HOOK)!r}); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m._core.SENTINEL); print(m._load_mechanism().SENTINEL)"
        )
        run = subprocess.run([sys.executable, "-I", "-c", code], env=env,
                             text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == ["installed", "installed"], run.stdout


def test_missing_install_never_falls_back_to_workspace() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        decoy = root / "workspace/hestia/plugins/_shared"
        write_engine(decoy, "working-tree-decoy")
        env = dict(
            os.environ,
            HESTIA_HOME=str(root / "missing-hestia-home"),
            HESTIA_WORKSPACE=str(root / "workspace"),
        )
        env.pop("HESTIA_SHARED_DIR", None)
        code = (
            "import importlib.util; "
            f"s=importlib.util.spec_from_file_location('codex_gate', {str(HOOK)!r}); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m._core is None); "
            "\ntry: m._load_mechanism()\n"
            "except ImportError: print('fail-closed-misdeployment')\n"
            "else: raise SystemExit('workspace fallback remained reachable')"
        )
        run = subprocess.run([sys.executable, "-I", "-c", code], env=env,
                             text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == ["True", "fail-closed-misdeployment"], run.stdout


def test_no_implicit_workspace_loader_spelling_remains() -> None:
    src = HOOK.read_text(encoding="utf-8")
    assert 'os.path.join(WORKSPACE, "hestia", "plugins", "_shared")' not in src
    assert 'os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),\n                              "_shared")' not in src
    assert 'os.environ.get("HESTIA_SHARED_DIR")' in src
    assert 'os.environ.get("HESTIA_HOME", "~/.hestia")' in src


if __name__ == "__main__":
    test_installed_engine_wins_over_workspace_decoy()
    test_missing_install_never_falls_back_to_workspace()
    test_no_implicit_workspace_loader_spelling_remains()
    print("ok: Codex loader is pinned to the installed shared engine")
