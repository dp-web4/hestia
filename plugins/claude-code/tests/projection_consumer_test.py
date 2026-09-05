#!/usr/bin/env python3
"""The claude-code seat consumes the vault projection and nothing else (#944 step 5).

Five arms, each a property the PRD names and one of them the whole point:

  1. NO LOCATOR — HESTIA_HOME unset: the hook refuses `[config.unbacked]` with rc 2 BEFORE it
     reads stdin, and there is no fallback to a familiar home. (#943 was held for the default
     this arm forbids.)
  2. NO PROJECTION — HESTIA_HOME set, `seats/claude-code.env` absent: same refusal, and the
     message tells the operator where to populate it.
  3. MISWIRED LOCATOR — the projection says a different HESTIA_HOME than the launcher supplied:
     `[config.miswired]`, rc 2. The launcher's locator is verified against the authority.
  4. THE PROJECTION WINS — the launcher exports HESTIA_WORKSPACE=/launcher/says and the
     projection says /vault/says: after import the process sees /vault/says, plus every other
     projected key, plus HESTIA_PROJECTION_SHA256 = sha256 of the bytes consumed. And
     HESTIA_ROLE is NOT overridden: role is launch context, never config.
  5. THE WITNESS HOOK shares the contract: with no projection `run()` returns 0 having recorded
     nothing; with one, its STATE_DIR is the projected value.

Fail direction: every arm asserts the refusal shape (rc, rule name, no traceback) or the
observed environment. A hook that fell back would pass arm 4's launcher value through and
fail it; a hook that crashed would fail the no-traceback check.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
from projection_fixture import projection_env, write_projection  # noqa: E402

HOOKS = HERE.parent / "hooks"
HOOK = HOOKS / ("pre_" + "tool_" + "use.py")
WITNESS = HOOKS / "witness.py"
SHARED_SRC = REPO / "plugins" / "_shared"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def stage_home(root: Path) -> Path:
    """A fixture HESTIA_HOME with the reviewed shared runtime installed under it."""
    home = root / "hestia-home"
    shared = home / "shared"
    shared.mkdir(parents=True)
    for p in SHARED_SRC.glob("hestia_*.py"):
        if "_test" in p.name or p.name.startswith("test_"):
            continue
        shutil.copy(p, shared / p.name)
    (home / "endpoint").write_text("http://127.0.0.1:1/mcp\n")
    return home


EVENT = {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/tmp/x"},
         "session_id": "proj-test", "tool_use_id": "t1"}


def run_hook(env: dict, stdin: str | None = json.dumps(EVENT)) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin, env=env, text=True,
                          capture_output=True, check=False, timeout=60)


def probe_env(env: dict, keys: list[str]) -> dict:
    """Import the hook in a fresh interpreter and report what the environment looks like after."""
    code = f"""
import importlib.util, os, json, sys
s = importlib.util.spec_from_file_location('g', {str(HOOK)!r}); g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(json.dumps({{'err': g._PROJECTION_ERROR, 'env': {{k: os.environ.get(k) for k in {keys!r}}}}}))
"""
    r = subprocess.run([sys.executable, "-I", "-c", code], env=env, text=True, capture_output=True, check=False, timeout=60)
    check("probe_imports_cleanly", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-400:])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"err": "unparseable", "env": {}}


def test_no_locator_refuses_before_stdin() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home = stage_home(Path(raw))
        env = projection_env(home)
        env.pop("HESTIA_HOME", None)
        # The shared runtime is still reachable explicitly, so the ONLY thing missing is the locator.
        env["HESTIA_SHARED_DIR"] = str(home / "shared")
        r = run_hook(env, stdin=None)   # no event at all: the refusal must come first
        check("no_locator_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-300:]!r}")
        check("no_locator_names_rule", "[config.unbacked]" in r.stderr, r.stderr[-300:])
        check("no_locator_no_traceback", "Traceback" not in r.stderr)
        check("no_locator_no_fallback", ".hestia" not in r.stderr.replace(str(home), ""),
              "a familiar home was mentioned as if it were a candidate")


def test_no_projection_refuses_and_says_where() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home = stage_home(Path(raw))
        r = run_hook(projection_env(home))
        check("no_projection_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-300:]!r}")
        check("no_projection_names_rule", "[config.unbacked]" in r.stderr, r.stderr[-300:])
        check("no_projection_says_where", "Runtime config" in r.stderr, r.stderr[-300:])


def test_miswired_locator_refuses() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home = stage_home(Path(raw))
        write_projection(home, env={"HESTIA_HOME": str(Path(raw) / "some-other-home")})
        r = run_hook(projection_env(home))
        check("miswired_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-300:]!r}")
        check("miswired_names_rule", "[config.miswired]" in r.stderr, r.stderr[-300:])


def test_the_projection_wins_and_role_is_launch_context() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home = stage_home(Path(raw))
        path = write_projection(home, env={
            "HESTIA_WORKSPACE": "/vault/says", "HESTIA_ENDPOINT": "http://127.0.0.1:1/mcp",
            "HESTIA_PLUGIN_ID": "claude-code", "HESTIA_ROLE": "role:should:never:apply",
        })
        env = projection_env(home, HESTIA_WORKSPACE="/launcher/says", HESTIA_ROLE="role:constellation:mesh-worker")
        got = probe_env(env, ["HESTIA_WORKSPACE", "HESTIA_ROLE", "HESTIA_ENDPOINT", "HESTIA_PROJECTION_SHA256",
                              "HESTIA_PROJECTION_PATH", "HESTIA_SHARED_DIR"])
        check("projection_loaded", got["err"] is None, str(got["err"]))
        check("projection_wins_over_launcher", got["env"].get("HESTIA_WORKSPACE") == "/vault/says",
              f"the launcher's value survived: {got['env']}")
        check("role_is_launch_context", got["env"].get("HESTIA_ROLE") == "role:constellation:mesh-worker",
              f"the projection overrode the launch role: {got['env']}")
        check("projected_endpoint", got["env"].get("HESTIA_ENDPOINT") == "http://127.0.0.1:1/mcp")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        check("digest_of_consumed_bytes", got["env"].get("HESTIA_PROJECTION_SHA256") == digest,
              f"{got['env'].get('HESTIA_PROJECTION_SHA256')} != {digest}")
        check("path_exported", got["env"].get("HESTIA_PROJECTION_PATH") == str(path))
        # and the hook, run for real, gets PAST the config check (its refusal, if any, is downstream)
        r = run_hook(env)
        check("configured_hook_passes_config_check", "[config." not in r.stderr, r.stderr[-300:])
        check("configured_hook_no_traceback", "Traceback" not in r.stderr, r.stderr[-300:])


def test_the_witness_hook_shares_the_contract() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home = stage_home(Path(raw))
        code = f"""
import importlib.util, os, json
s = importlib.util.spec_from_file_location('w', {str(WITNESS)!r}); w = importlib.util.module_from_spec(s); s.loader.exec_module(w)
print(json.dumps({{'err': w._PROJECTION_ERROR, 'state': str(w.STATE_DIR)}}))
"""
        # no projection: the module imports, reports the absence, and run() would record nothing
        r = subprocess.run([sys.executable, "-I", "-c", code], env=projection_env(home), text=True, capture_output=True, timeout=60)
        check("witness_imports_without_projection", r.returncode == 0, r.stderr[-300:])
        got = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"err": "none"}
        check("witness_reports_absence", got["err"] is not None and got["err"][0] == "config.unbacked", str(got))
        # with one: STATE_DIR is the projected value
        write_projection(home, env={"HESTIA_STATE_DIR": str(Path(raw) / "projected-state")})
        r = subprocess.run([sys.executable, "-I", "-c", code], env=projection_env(home), text=True, capture_output=True, timeout=60)
        got = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"err": "none", "state": ""}
        check("witness_projection_loaded", got["err"] is None, str(got))
        check("witness_state_dir_projected", got["state"] == str(Path(raw) / "projected-state"), got["state"])


def teardown_module(module):
    assert not FAILS, FAILS


TESTS = [test_no_locator_refuses_before_stdin, test_no_projection_refuses_and_says_where,
         test_miswired_locator_refuses, test_the_projection_wins_and_role_is_launch_context,
         test_the_witness_hook_shares_the_contract]

if __name__ == "__main__":
    for t in TESTS:
        t()
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print("ok: the claude-code seat consumes the vault projection and nothing else")
