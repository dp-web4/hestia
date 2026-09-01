#!/usr/bin/env python3
"""claude-code must execute the INSTALLED shared law, never a cached or checkout copy.

Review of #747 (GPT, item 2): `sys.path.insert(0, ...)` is not sufficient, because a
same-named module already present in `sys.modules` wins. And a claude seat measured the
live consequence on build 561 (2026-09-01): `~/.claude/_shared`, a 3-module engine dated
2026-08-14, was reached through `parents[2]/_shared` on marker-mentioning commands and
produced floor-less denies whose text read as policy. So the sabotage here is the real
shape: a decoy engine beside the hook, AND the decoy's modules already imported before the
hook runs. The loader must evict them and bind every shared module to the installed file.

Three arms, all subprocess (`-I`) so nothing leaks between them:
  1. decoy dir + preloaded wrong-origin modules -> every shared module resolves installed
  2. the source carries no implicit checkout/parents[N] spelling
  3. (in missing_shared_authority_blocks_test.py) no installed engine -> exit 2
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"
SHARED = REPO / "plugins" / "_shared"
MODULES = [ln.strip() for ln in (SHARED / "RUNTIME_MANIFEST.txt").read_text().splitlines()
           if ln.strip() and not ln.startswith("#")]

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def stage(dst: Path, sentinel: str | None) -> None:
    dst.mkdir(parents=True)
    for name in MODULES:
        text = (SHARED / name).read_text(encoding="utf-8")
        if sentinel:
            text += f"\nSENTINEL = {sentinel!r}\n"
        (dst / name).write_text(text, encoding="utf-8")


def test_preloaded_decoy_modules_are_evicted() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        installed = root / "hestia-home" / "shared"
        decoy = root / "decoy" / "_shared"
        stage(installed, None)
        stage(decoy, "decoy")
        names = [m[:-3] for m in MODULES]
        code = f"""
import importlib.util, os, sys
decoy = {str(decoy)!r}
sys.path.insert(0, decoy)                       # the shadowing sys.path entry
for n in {names!r}:                             # AND the modules already imported from it
    s = importlib.util.spec_from_file_location(n, os.path.join(decoy, n + '.py'))
    m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m)
s = importlib.util.spec_from_file_location('claude_gate', {str(HOOK)!r})
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
mech = g._load_mechanism()
out = {{
  'classifier': os.path.realpath(g._classifier.__file__),
  'classifier_sentinel': getattr(g._classifier, 'SENTINEL', None),
  'mechanism': os.path.realpath(mech.__file__),
  'mechanism_sentinel': getattr(mech, 'SENTINEL', None),
  'closure': os.path.realpath(sys.modules['hestia_governance_closure'].__file__),
  'core': os.path.realpath(g._load_shared_module('hestia_gate_core').__file__),
  'unavailable': g._CLASSIFIER_UNAVAILABLE,
}}
import json; print(json.dumps(out))
"""
        env = dict(os.environ, HESTIA_HOME=str(root / "hestia-home"),
                   HESTIA_ENDPOINT="http://127.0.0.1:1")
        env.pop("HESTIA_SHARED_DIR", None)
        run = subprocess.run([sys.executable, "-I", "-c", code], env=env, text=True,
                             capture_output=True, check=False, timeout=60)
        check(run.returncode == 0, f"probe ran (rc={run.returncode}) {run.stderr[-300:]!r}")
        if run.returncode != 0:
            return
        import json
        got = json.loads(run.stdout.strip().splitlines()[-1])
        inst = os.path.realpath(str(installed))
        for key in ("classifier", "mechanism", "closure", "core"):
            check(got[key].startswith(inst + os.sep),
                  f"{key} resolved to the installed engine, not the decoy: {got[key]}")
        check(got["classifier_sentinel"] is None and got["mechanism_sentinel"] is None,
              "no decoy sentinel survives in a bound module")
        check(got["unavailable"] is None, "the classifier guard did not fire with the engine present")


def test_no_implicit_checkout_spelling_remains() -> None:
    src = HOOK.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in src.splitlines()
           if re.search(r"parents\[\d\]\s*/\s*['\"]_shared|_LEGACY_SHARED_DIR\s*=", ln)]
    check(not bad, f"no parents[N]/_shared or legacy-dir resolution remains: {bad}")


if __name__ == "__main__":
    test_preloaded_decoy_modules_are_evicted()
    test_no_implicit_checkout_spelling_remains()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: claude-code binds every shared module to the installed engine")
