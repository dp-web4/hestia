#!/usr/bin/env python3
"""claude-code must execute the INSTALLED shared law, never a cached, checkout or crashing copy.

Review of #747 (GPT, item 2, then the 15:14Z hold): `sys.path.insert(0, ...)` is not
sufficient, because a same-named module already present in `sys.modules` wins; inserting
only when the literal string is absent leaves a decoy AHEAD of an installed path that is
already later in `sys.path`; and `except Exception` at module initialisation lets a
`SystemExit(0)` raised by an installed module end the hook rc=0, an allow, before `main()`
can refuse. A claude seat measured the first shape live on build 561: `~/.claude/_shared`, a
2026-08-14 engine, reached through `parents[2]/_shared` on marker-mentioning commands,
producing floor-less denies whose text read as policy.

Arms, all subprocess (`-I`) so nothing leaks between them:
  1. decoy dir + preloaded wrong-origin modules -> every shared module resolves installed
  2. decoy FIRST on sys.path, installed path already LATER -> a sibling bare import binds
     installed bytes (the loader must put the selected dir first, not merely insert if absent)
  3. an installed module raises SystemExit(0) / KeyboardInterrupt at import -> the REAL hook
     exits 2 naming an unavailable authority, never 0, never a traceback
  4. the source carries no implicit checkout/parents[N] spelling
  (missing_shared_authority_blocks_test.py: no installed engine at all -> exit 2)
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
HOOK = REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"
SHARED = REPO / "plugins" / "_shared"
MODULES = [ln.strip() for ln in (SHARED / "RUNTIME_MANIFEST.txt").read_text().splitlines()
           if ln.strip() and not ln.startswith("#")]
NAMES = [m[:-3] for m in MODULES]

WRITE_EVENT = {"tool_name": "Bash", "tool_input": {"command": "echo hi > /tmp/hestia-loader-test"},
               "cwd": "/tmp"}

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    """Under pytest each test_* returns normally after appending to FAILURES, so without
    this the accumulator is never consumed and a red arm reads as green (ci_selfexec_test).
    The __main__ path below asserts the same list; this is the pytest spelling of it."""
    assert not FAILURES, FAILURES


def stage(dst: Path, sentinel: str | None, poison: dict[str, str] | None = None) -> None:
    dst.mkdir(parents=True)
    for name in MODULES:
        text = (SHARED / name).read_text(encoding="utf-8")
        if sentinel:
            text += f"\nSENTINEL = {sentinel!r}\n"
        if poison and name in poison:
            # APPENDED, not prepended: a raise placed before `from __future__` is a
            # SyntaxError, an ordinary Exception, and the first draft of this arm passed
            # against a loader that did NOT catch BaseException for exactly that reason.
            # At the end of the module the raise runs during initialisation proper.
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
    "s = importlib.util.spec_from_file_location('claude_gate', {hook!r})\n"
    "g = importlib.util.module_from_spec(s); s.loader.exec_module(g)\n"
)


def test_preloaded_decoy_modules_are_evicted() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home" / "shared"
        decoy = root / "decoy" / "_shared"
        stage(installed, None)
        stage(decoy, "decoy")
        code = f"""
import importlib.util, os, sys, json
decoy = {str(decoy)!r}
sys.path.insert(0, decoy)
for n in {NAMES!r}:
    s = importlib.util.spec_from_file_location(n, os.path.join(decoy, n + '.py'))
    m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m)
""" + LOAD_HOOK.format(hook=str(HOOK)) + """
mech = g._load_mechanism()
print(json.dumps({
  'classifier': os.path.realpath(g._classifier.__file__),
  'classifier_sentinel': getattr(g._classifier, 'SENTINEL', None),
  'mechanism': os.path.realpath(mech.__file__),
  'mechanism_sentinel': getattr(mech, 'SENTINEL', None),
  'closure': os.path.realpath(sys.modules['hestia_governance_closure'].__file__),
  'core': os.path.realpath(g._load_shared_module('hestia_gate_core').__file__),
  'unavailable': g._CLASSIFIER_UNAVAILABLE,
}))
"""
        env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"), HESTIA_ENDPOINT="http://127.0.0.1:1")
        env.pop("HESTIA_SHARED_DIR", None)
        got = probe(code, env)
        if not got:
            return
        inst = os.path.realpath(str(installed))
        for key in ("classifier", "mechanism", "closure", "core"):
            check(got[key].startswith(inst + os.sep), f"[1] {key} bound to the installed engine: {got[key]}")
        check(got["classifier_sentinel"] is None and got["mechanism_sentinel"] is None,
              "[1] no decoy sentinel survives in a bound module")
        check(got["unavailable"] is None, "[1] the classifier guard did not fire with the engine present")


def test_decoy_first_with_installed_already_later_on_sys_path() -> None:
    """The shape the first loader draft missed: the selected dir is ALREADY on sys.path, so an
    insert-if-absent leaves the decoy ahead of it and a sibling's bare import binds the decoy."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home" / "shared"
        decoy = root / "decoy" / "_shared"
        stage(installed, None)
        stage(decoy, "decoy")
        code = f"""
import importlib.util, os, sys, json
decoy, installed = {str(decoy)!r}, {str(installed)!r}
sys.path[:] = [decoy, *sys.path, installed]          # decoy first, installed already present, later
""" + LOAD_HOOK.format(hook=str(HOOK)) + """
mech = g._load_mechanism()
import hestia_gate_core as sibling                    # a bare sibling import, as the mechanism does
print(json.dumps({
  'path0': os.path.realpath(sys.path[0]),
  'installed_positions': [i for i, p in enumerate(sys.path) if os.path.realpath(p) == os.path.realpath(installed)],
  'sibling': os.path.realpath(sibling.__file__),
  'sibling_sentinel': getattr(sibling, 'SENTINEL', None),
  'mechanism_sentinel': getattr(mech, 'SENTINEL', None),
}))
"""
        env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"), HESTIA_ENDPOINT="http://127.0.0.1:1")
        env.pop("HESTIA_SHARED_DIR", None)
        got = probe(code, env)
        if not got:
            return
        inst = os.path.realpath(str(installed))
        check(got["path0"] == inst, f"[2] the selected dir is FIRST on sys.path: {got['path0']}")
        check(got["installed_positions"] == [0], f"[2] and occupies exactly one position: {got['installed_positions']}")
        check(got["sibling"].startswith(inst + os.sep), f"[2] a bare sibling import binds installed bytes: {got['sibling']}")
        check(got["sibling_sentinel"] is None and got["mechanism_sentinel"] is None, "[2] no decoy sentinel survives")


def test_installed_module_raising_at_import_fails_closed() -> None:
    """A BaseException at module initialisation must become a refusal, not an exit code."""
    for victim in ("hestia_shell_classifier.py", "hestia_gate_core.py"):
        for raised in ("raise SystemExit(0)", "raise KeyboardInterrupt()"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                installed = root / "hestia-home" / "shared"
                stage(installed, None, poison={victim: raised})
                env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"),
                           HESTIA_ENDPOINT="http://127.0.0.1:1")
                env.pop("HESTIA_SHARED_DIR", None)
                run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(WRITE_EVENT),
                                     env=env, text=True, capture_output=True, check=False, timeout=60)
                label = f"[3] {victim} `{raised}` at import"
                check(run.returncode == 2, f"{label} -> rc 2 (got {run.returncode}); rc 0 would be an ALLOW")
                check("Traceback" not in run.stderr, f"{label} -> no traceback")
                check("no-shared-authority" in run.stderr or "core_unavailable" in run.stderr,
                      f"{label} -> stderr names the unavailable authority: {run.stderr[:160]!r}")


def test_no_implicit_checkout_spelling_remains() -> None:
    src = HOOK.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in src.splitlines()
           if re.search(r"parents\[\d\]\s*/\s*['\"]_shared|_LEGACY_SHARED_DIR\s*=", ln)]
    check(not bad, f"[4] no parents[N]/_shared or legacy-dir resolution remains: {bad}")


if __name__ == "__main__":
    test_preloaded_decoy_modules_are_evicted()
    test_decoy_first_with_installed_already_later_on_sys_path()
    test_installed_module_raising_at_import_fails_closed()
    test_no_implicit_checkout_spelling_remains()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: claude-code binds every shared module to the installed engine, and a crashing one refuses")
