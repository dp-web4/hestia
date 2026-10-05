#!/usr/bin/env python3
"""Every seat executes the INSTALLED shared law, never a cached, checkout or crashing copy.

Review of #747 (GPT, item 2, then the 15:14Z hold): `sys.path.insert(0, ...)` is not
sufficient, because a same-named module already present in `sys.modules` wins; inserting
only when the literal string is absent leaves a decoy AHEAD of an installed path that is
already later in `sys.path`; and `except Exception` at module initialisation lets a
`SystemExit(0)` raised by an installed module end the hook rc=0, an allow, before `main()`
can refuse. A claude seat measured the first shape live on build 561.

Since one-gate stage C the four seats share one certified loader (`_load_gate`), which loads
the common gate (`hestia_single_gate`) from the selected authority; the gate's own bare imports
then bind its siblings. So every arm runs against all four shims, and arm 1 asks what the GATE
actually holds (`gate.core`, `gate.mechanism`, `gate.closure`), not what a seat-private
loader returned:

  1. decoy dir + preloaded wrong-origin modules -> the gate and every sibling it holds resolve
     installed
  2. decoy FIRST on sys.path, installed path already LATER -> the selected dir is first, once,
     and a bare sibling import binds installed bytes
  3. an installed module raises SystemExit(0) / KeyboardInterrupt at import -> the REAL hook
     exits 2 naming the unavailable gate, never 0, never a traceback
  4. the source carries no implicit checkout/parents[N] spelling
  (missing_shared_authority_blocks_test.py and installed_engine_loader_test.py: no engine at all)

Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_OVERLAY ({module: path}) supplies
module sources, HESTIA_CONTRACT_SHIMS ({seat: path}) the shims.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
SEAT_SHIM = {"claude-code": "plugins/claude-code/hooks/pre_tool_use.py",
             "codex": "plugins/codex/hooks/pre_tool_use.py",
             "kimi": "plugins/kimi/hooks/pre_tool_use.py",
             "gemini": "plugins/gemini/hooks/before_tool.py"}
MEMBER = {"claude-code": "claude-code", "codex": "codex", "kimi": "kimi-code", "gemini": "gemini"}
EVENT = {"claude-code": "PreToolUse", "codex": "PreToolUse", "kimi": "PreToolUse",
         "gemini": "BeforeTool"}
OVERLAY = json.loads(os.getenv("HESTIA_CONTRACT_OVERLAY") or "{}")
SHIMS = json.loads(os.getenv("HESTIA_CONTRACT_SHIMS") or "{}")
_MANIFEST = Path(OVERLAY.get("RUNTIME_MANIFEST") or SHARED / "RUNTIME_MANIFEST.txt")
MODULES = [ln.strip() for ln in _MANIFEST.read_text().splitlines()
           if ln.strip() and not ln.startswith("#")]
NAMES = [m[:-3] for m in MODULES]
HELD = ("core", "mechanism", "closure")   # the siblings the common gate binds at import

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    """Under pytest each test_* returns normally after appending to FAILURES, so without
    this the accumulator is never consumed and a red arm reads as green (ci_selfexec_test)."""
    assert not FAILURES, FAILURES


def hook(seat: str) -> str:
    return str(SHIMS.get(seat) or REPO / SEAT_SHIM[seat])


def write_event(seat: str) -> dict:
    return {"hook_event_name": EVENT[seat], "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/hestia-loader-test"}, "cwd": "/tmp",
            "session_id": "loader-binds-test"}


def project(home: Path, seat: str) -> None:
    """One missing thing at a time: a fixture with an engine but no projection tests the
    CONFIG refusal (`config.unbacked`) instead of the one this file is about (#944)."""
    seats = home / "seats"
    seats.mkdir(parents=True, exist_ok=True)
    (seats / (MEMBER[seat] + ".env")).write_text(
        f"# member: {MEMBER[seat]}\nHESTIA_HOME={home}\n", encoding="utf-8")


def stage(dst: Path, sentinel: str | None, poison: dict[str, str] | None = None) -> None:
    dst.mkdir(parents=True)
    for name in MODULES:
        src = Path(OVERLAY.get(name[:-3]) or SHARED / name)
        text = src.read_text(encoding="utf-8")
        if sentinel:
            text += f"\nSENTINEL = {sentinel!r}\n"
        if poison and name in poison:
            # APPENDED, not prepended: a raise before `from __future__` is a SyntaxError (an
            # ordinary Exception), and an arm built that way passes against a loader that
            # does NOT catch BaseException.
            text = text + "\n" + poison[name] + "\n"
        (dst / name).write_text(text, encoding="utf-8")


def probe(code: str, env: dict) -> dict:
    run = subprocess.run([sys.executable, "-I", "-c", code], env=env, text=True,
                         capture_output=True, check=False, timeout=60)
    check(run.returncode == 0, f"probe ran (rc={run.returncode}) {run.stderr[-300:]!r}")
    if run.returncode != 0:
        return {}
    return json.loads(run.stdout.strip().splitlines()[-1])


LOAD_HOOK = (
    "s = importlib.util.spec_from_file_location('gate_under_test', {hook!r})\n"
    "g = importlib.util.module_from_spec(s); s.loader.exec_module(g)\n"
    "gate = g._load_gate()\n"
)


def env_for(home: Path) -> dict:
    env = dict(os.environ, HESTIA_HOME=str(home), HESTIA_ENDPOINT="http://127.0.0.1:1")
    env.pop("HESTIA_SHARED_DIR", None)
    return env


def test_preloaded_decoy_modules_are_evicted() -> None:
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "hestia-home" / "shared"
            decoy = root / "decoy" / "_shared"
            stage(installed, None)
            project(root / "hestia-home", seat)
            stage(decoy, "decoy")
            code = f"""
import importlib.util, os, sys, json
decoy = {str(decoy)!r}
sys.path.insert(0, decoy)
for n in {NAMES!r}:
    s = importlib.util.spec_from_file_location(n, os.path.join(decoy, n + '.py'))
    m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m)
""" + LOAD_HOOK.format(hook=hook(seat)) + f"""
held = {{k: getattr(gate, k) for k in {HELD!r}}}
print(json.dumps({{
  'gate': os.path.realpath(gate.__file__),
  'held': {{k: os.path.realpath(v.__file__) for k, v in held.items()}},
  'sentinels': [k for k, v in [('gate', gate), *held.items()] if getattr(v, 'SENTINEL', None)],
}}))
"""
            got = probe(code, env_for(root / "hestia-home"))
            if not got:
                continue
            inst = os.path.realpath(str(installed))
            check(got["gate"].startswith(inst + os.sep), f"[1 {seat}] the gate is installed: {got['gate']}")
            for key, path in got["held"].items():
                check(path.startswith(inst + os.sep), f"[1 {seat}] gate.{key} is installed: {path}")
            check(not got["sentinels"], f"[1 {seat}] no decoy sentinel survives: {got['sentinels']}")


def test_decoy_first_with_installed_already_later_on_sys_path() -> None:
    """The shape the first loader draft missed: the selected dir is ALREADY on sys.path, so an
    insert-if-absent leaves the decoy ahead of it and a sibling's bare import binds the decoy."""
    for seat in SEAT_SHIM:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "hestia-home" / "shared"
            decoy = root / "decoy" / "_shared"
            stage(installed, None)
            project(root / "hestia-home", seat)
            stage(decoy, "decoy")
            code = f"""
import importlib.util, os, sys, json
decoy, installed = {str(decoy)!r}, {str(installed)!r}
sys.path[:] = [decoy, *sys.path, installed]          # decoy first, installed already present, later
""" + LOAD_HOOK.format(hook=hook(seat)) + """
import hestia_gate_core as sibling                    # a bare sibling import, as the gate does
print(json.dumps({
  'path0': os.path.realpath(sys.path[0]),
  'installed_positions': [i for i, p in enumerate(sys.path) if os.path.realpath(p) == os.path.realpath(installed)],
  'sibling': os.path.realpath(sibling.__file__),
  'sentinels': [n for n, v in (('sibling', sibling), ('mechanism', gate.mechanism)) if getattr(v, 'SENTINEL', None)],
}))
"""
            got = probe(code, env_for(root / "hestia-home"))
            if not got:
                continue
            inst = os.path.realpath(str(installed))
            check(got["path0"] == inst, f"[2 {seat}] the selected dir is FIRST on sys.path: {got['path0']}")
            check(got["installed_positions"] == [0], f"[2 {seat}] exactly one position: {got['installed_positions']}")
            check(got["sibling"].startswith(inst + os.sep), f"[2 {seat}] a bare sibling import binds installed bytes: {got['sibling']}")
            check(not got["sentinels"], f"[2 {seat}] no decoy sentinel survives: {got['sentinels']}")


def test_installed_module_raising_at_import_fails_closed() -> None:
    """A BaseException at module initialisation must become a refusal, not an exit code."""
    for seat in SEAT_SHIM:
        for victim in ("hestia_single_gate.py", "hestia_gate_core.py"):
            for raised in ("raise SystemExit(0)", "raise KeyboardInterrupt()"):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    stage(root / "hestia-home" / "shared", None, poison={victim: raised})
                    project(root / "hestia-home", seat)
                    run = subprocess.run([sys.executable, hook(seat)],
                                         input=json.dumps(write_event(seat)),
                                         env=env_for(root / "hestia-home"), text=True,
                                         capture_output=True, check=False, timeout=60)
                    label = f"[3 {seat}] {victim} `{raised}` at import"
                    check(run.returncode == 2, f"{label} -> rc 2 (got {run.returncode}); rc 0 would be an ALLOW")
                    check("Traceback" not in run.stderr, f"{label} -> no traceback")
                    check("gate.bootstrap_unavailable" in run.stderr,
                          f"{label} -> stderr names the unavailable gate: {run.stderr[:160]!r}")


def test_no_implicit_checkout_spelling_remains() -> None:
    for seat in SEAT_SHIM:
        src = Path(hook(seat)).read_text(encoding="utf-8")
        bad = [ln.strip() for ln in src.splitlines()
               if re.search(r"parents\[\d\]\s*/\s*['\"]_shared|_LEGACY_SHARED_DIR\s*=", ln)]
        check(not bad, f"[4 {seat}] no parents[N]/_shared or legacy-dir resolution remains: {bad}")


if __name__ == "__main__":
    test_preloaded_decoy_modules_are_evicted()
    test_decoy_first_with_installed_already_later_on_sys_path()
    test_installed_module_raising_at_import_fails_closed()
    test_no_implicit_checkout_spelling_remains()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: every seat binds the common gate and its siblings to the installed engine, "
          "and a crashing one refuses")
