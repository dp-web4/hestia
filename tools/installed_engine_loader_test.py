"""Every seat executes installed shared law, never an implicit worktree fallback.

Written for codex's loader; since one-gate stage C the four seats share one certified loader
(`_authority_dir` + `_load_gate`, copied byte-for-byte from plugins/_template/shim_template.py),
so every arm runs against all four shims. The authority is the common gate,
`hestia_single_gate.py`: an explicit HESTIA_SHARED_DIR (the projection renders it), else
`$HESTIA_HOME/shared`. Never a checkout, never a module some earlier import left in sys.modules.

Staging seam (unset in the repo and in CI): HESTIA_CONTRACT_SHIMS ({seat: path}).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
SEAT_SHIM = {"claude-code": "plugins/claude-code/hooks/pre_tool_use.py",
             "codex": "plugins/codex/hooks/pre_tool_use.py",
             "kimi": "plugins/kimi/hooks/pre_tool_use.py",
             "gemini": "plugins/gemini/hooks/before_tool.py"}
MEMBER = {"claude-code": "claude-code", "codex": "codex", "kimi": "kimi-code", "gemini": "gemini"}
EVENT = {"claude-code": "PreToolUse", "codex": "PreToolUse", "kimi": "PreToolUse",
         "gemini": "BeforeTool"}
_OVERRIDE = json.loads(os.getenv("HESTIA_CONTRACT_SHIMS") or "{}")
API = "decide/2"


def hook(seat: str) -> Path:
    return Path(_OVERRIDE.get(seat) or REPO / SEAT_SHIM[seat])


def write_engine(root: Path, sentinel: str, body: str = "") -> None:
    root.mkdir(parents=True)
    (root / "hestia_single_gate.py").write_text(
        f"GATE_API_VERSION = {API!r}\nSENTINEL = {sentinel!r}\n{body}", encoding="utf-8")


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("HESTIA_SHARED_DIR", "HESTIA_HOME", "HESTIA_WORKSPACE", "HESTIA_ENDPOINT")}
    env.update(extra)
    return env


def load_probe(seat: str, env: dict, preamble: str = "") -> subprocess.CompletedProcess:
    code = (
        "import importlib.util, os, sys, types; " + preamble +
        f"s=importlib.util.spec_from_file_location('gate_under_test', {str(hook(seat))!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "g=m._load_gate(); print(g.SENTINEL); print(os.path.realpath(g.__file__))"
    )
    return subprocess.run([sys.executable, "-I", "-c", code], env=env,
                          text=True, capture_output=True, check=False, timeout=60)


def run_hook(seat: str, env: dict, workspace: Path) -> subprocess.CompletedProcess:
    event = {"hook_event_name": EVENT[seat], "tool_name": "Read",
             "tool_input": {"file_path": str(workspace / "ordinary.txt")},
             "cwd": str(workspace), "session_id": "installed-loader-test"}
    return subprocess.run([sys.executable, "-I", str(hook(seat))], env=env,
                          input=json.dumps(event), text=True, capture_output=True,
                          check=False, timeout=60)


def projection(home: Path, seat: str, extra: str = "") -> None:
    (home / "seats").mkdir(parents=True, exist_ok=True)
    (home / "seats" / f"{MEMBER[seat]}.env").write_text(
        f"# member: {MEMBER[seat]}\nHESTIA_HOME={home}\n{extra}", encoding="utf-8")


def test_installed_engine_wins_over_workspace_decoy() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "hestia-home/shared"
            write_engine(installed, "installed")
            write_engine(root / "workspace/hestia/plugins/_shared", "working-tree-decoy")
            run = load_probe(seat, clean_env(HESTIA_HOME=str(root / "hestia-home"),
                                             HESTIA_WORKSPACE=str(root / "workspace")))
            assert run.returncode == 0, (seat, run.stderr)
            assert run.stdout.splitlines() == [
                "installed", str((installed / "hestia_single_gate.py").resolve())], (seat, run.stdout)


def test_explicit_shared_dir_is_the_selected_authority() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_engine(root / "reviewed-fixture", "explicit")
            write_engine(root / "hestia-home/shared", "home")
            run = load_probe(seat, clean_env(HESTIA_SHARED_DIR=str(root / "reviewed-fixture"),
                                             HESTIA_HOME=str(root / "hestia-home")))
            assert run.returncode == 0, (seat, run.stderr)
            assert run.stdout.splitlines()[0] == "explicit", (seat, run.stdout)


def test_missing_install_never_falls_back_and_hook_fails_closed() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = root / "workspace"
            write_engine(workspace / "hestia/plugins/_shared", "working-tree-decoy")
            home = root / "hestia-home-without-shared"
            projection(home, seat)
            run = run_hook(seat, clean_env(HESTIA_HOME=str(home),
                                           HESTIA_WORKSPACE=str(workspace)), workspace)
            assert run.returncode == 2, (seat, run.stdout, run.stderr)
            assert "gate.bootstrap_unavailable" in run.stderr, (seat, run.stderr)
            assert "working-tree-decoy" not in run.stdout + run.stderr, seat


def test_preloaded_wrong_origin_modules_cannot_become_authority() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "hestia-home/shared"
            write_engine(installed, "installed")
            preamble = ("d=types.ModuleType('hestia_single_gate'); "
                        "d.__file__='/tmp/worktree-decoy/hestia_single_gate.py'; "
                        "d.SENTINEL='decoy'; d.GATE_API_VERSION='decide/2'; "
                        "sys.modules['hestia_single_gate']=d; ")
            run = load_probe(seat, clean_env(HESTIA_HOME=str(root / "hestia-home")), preamble)
            assert run.returncode == 0, (seat, run.stderr)
            assert run.stdout.splitlines() == [
                "installed", str((installed / "hestia_single_gate.py").resolve())], (seat, run.stdout)


def test_an_api_mismatch_is_not_an_authority() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "hestia-home"
            (home / "shared").mkdir(parents=True)
            (home / "shared" / "hestia_single_gate.py").write_text(
                "GATE_API_VERSION = 'decide/1'\n", encoding="utf-8")
            projection(home, seat)
            run = run_hook(seat, clean_env(HESTIA_HOME=str(home)), root)
            assert run.returncode == 2, (seat, run.stderr)
            assert "API mismatch" in run.stderr and "gate.bootstrap_unavailable" in run.stderr, (
                seat, run.stderr)


def test_selected_module_baseexception_fails_closed() -> None:
    for seat in SEAT_SHIM:
        for raised in ("SystemExit(0)", "KeyboardInterrupt()"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                home = root / "hestia-home"
                (home / "shared").mkdir(parents=True)
                (home / "shared" / "hestia_single_gate.py").write_text(
                    f"raise {raised}\n", encoding="utf-8")
                projection(home, seat)
                run = run_hook(seat, clean_env(HESTIA_HOME=str(home)), root)
                assert run.returncode == 2, (seat, raised, run.stdout, run.stderr)
                assert "gate.bootstrap_unavailable" in run.stderr, (seat, raised, run.stderr)
                assert "Traceback" not in run.stderr, (seat, raised, run.stderr)


def test_no_implicit_workspace_loader_spelling_remains() -> None:
    for seat in SEAT_SHIM:
        src = hook(seat).read_text(encoding="utf-8")
        assert '"hestia", "plugins", "_shared"' not in src, seat
        assert 'os.environ.get("HESTIA_SHARED_DIR")' in src, seat
        assert '"~/.hestia"' not in src, f"{seat}: HESTIA_HOME has no default, by design"


TESTS = [
    test_installed_engine_wins_over_workspace_decoy,
    test_explicit_shared_dir_is_the_selected_authority,
    test_missing_install_never_falls_back_and_hook_fails_closed,
    test_preloaded_wrong_origin_modules_cannot_become_authority,
    test_an_api_mismatch_is_not_an_authority,
    test_selected_module_baseexception_fails_closed,
    test_no_implicit_workspace_loader_spelling_remains,
]

if __name__ == "__main__":
    for t in TESTS:
        t()
    print("ok: every seat's loader is pinned to the selected installed common gate")
