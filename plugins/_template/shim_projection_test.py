#!/usr/bin/env python3
"""Every certified shim consumes the vault projection and nothing else (#944; dp ruling
2026-09-05: seats have shims, not gates; env vars except the one unavoidable locator).

Run against all four thin shims, because the loader is byte-identical by certification and a
behaviour that holds on one must hold on all:

  1. NO LOCATOR: the shim refuses `[config.unbacked]` with rc 2 before it reads the harness
     event, and names no familiar home.
  2. NO PROJECTION under a supplied locator: same rule, and the message says where to populate.
  3. MISWIRED: the projection names a different HESTIA_HOME than the launcher -> `[config.miswired]`.
  4. THE PROJECTION WINS and the profile READS it: after import, identity_path / home_markers /
     observe_dir are the projected values, HESTIA_ROLE is untouched, and the digest matches.
  5. CERTIFIER: a PROFILE value written as `os.environ.get("KEY", "default")` is refused as
     not-data (a default is a hardcoded path), while the one-argument form is admitted.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HOOK = "pre_" + "tool_" + "use.py"
SHIMS = {
    "claude-code": (REPO / "plugins" / "claude-code" / "hooks" / HOOK, "HESTIA_CLAUDE_IDENTITY"),
    "codex": (REPO / "plugins" / "codex" / "hooks" / HOOK, "HESTIA_CODEX_IDENTITY"),
    "kimi-code": (REPO / "plugins" / "kimi" / "hooks" / HOOK, "HESTIA_KIMI_IDENTITY"),
    "gemini": (REPO / "plugins" / "gemini" / "hooks" / ("before_" + "tool.py"), "HESTIA_GEMINI_IDENTITY"),
}
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def env_for(home: Path | None, **extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("HESTIA_HOME", "HESTIA_SHARED_DIR", "HESTIA_WORKSPACE", "HESTIA_ENDPOINT")}
    if home is not None:
        env["HESTIA_HOME"] = str(home)
    env.update(extra)
    return env


def write_projection(home: Path, member: str, env: dict) -> Path:
    seats = home / "seats"
    seats.mkdir(parents=True, exist_ok=True)
    p = seats / (member + "." + "env")
    lines = [f"# member: {member}"] + [f"{k}={v}" for k, v in sorted({"HESTIA_HOME": str(home), **env}.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run(shim: Path, env: dict, stdin: str | None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(shim)], input=stdin, env=env, text=True,
                          capture_output=True, check=False, timeout=60)


def probe(shim: Path, env: dict) -> dict:
    code = f"""
import importlib.util, os, json
s = importlib.util.spec_from_file_location('g', {str(shim)!r}); g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(json.dumps({{'err': g._PROJECTION_ERROR, 'profile': {{k: (list(v) if isinstance(v, tuple) else v) for k, v in g.PROFILE.items() if k != 'gate_path'}},
  'role': os.environ.get('HESTIA_ROLE'), 'sha': os.environ.get('HESTIA_PROJECTION_SHA256')}}))
"""
    r = subprocess.run([sys.executable, "-I", "-c", code], env=env, text=True, capture_output=True, check=False, timeout=60)
    check("probe_imports", r.returncode == 0 and "Traceback" not in r.stderr, r.stderr[-300:])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"err": "unparseable", "profile": {}}


def test_every_shim_consumes_the_projection() -> None:
    for member, (shim, ident_key) in SHIMS.items():
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "hestia-home"
            home.mkdir()
            # 1. no locator, no event: the refusal comes first and names no familiar home
            r = run(shim, env_for(None), stdin=None)
            check(f"[{member}] no_locator_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-200:]!r}")
            check(f"[{member}] no_locator_rule", "[config.unbacked]" in r.stderr, r.stderr[-200:])
            check(f"[{member}] no_locator_no_familiar_home", ".hestia" not in r.stderr.replace(str(home), ""), r.stderr[-200:])
            # 2. locator, no projection
            r = run(shim, env_for(home), stdin="{}")
            check(f"[{member}] no_projection_rule", r.returncode == 2 and "[config.unbacked]" in r.stderr, r.stderr[-200:])
            check(f"[{member}] no_projection_says_where", "Runtime config" in r.stderr, r.stderr[-200:])
            # 3. miswired locator
            write_projection(home, member, {"HESTIA_HOME": str(Path(raw) / "elsewhere")})
            r = run(shim, env_for(home), stdin="{}")
            check(f"[{member}] miswired_rule", r.returncode == 2 and "[config.miswired]" in r.stderr, r.stderr[-200:])
            # 4. the projection wins; the profile reads it; role is launch context
            p = write_projection(home, member, {
                ident_key: f"/vault/{member}/identity.json", "HESTIA_HARNESS_HOME": f"/vault/{member}/home",
                "HESTIA_OBSERVE_DIR": f"/vault/{member}/observe", "HESTIA_ROLE": "role:never:applies",
            })
            got = probe(shim, env_for(home, HESTIA_OBSERVE_DIR="/launcher/observe", HESTIA_ROLE="role:constellation:mesh-worker"))
            check(f"[{member}] loaded", got["err"] is None, str(got["err"]))
            prof = got.get("profile", {})
            check(f"[{member}] identity_from_projection", prof.get("identity_path") == f"/vault/{member}/identity.json", str(prof))
            check(f"[{member}] home_markers_from_projection", prof.get("home_markers") == [f"/vault/{member}/home"], str(prof))
            check(f"[{member}] observe_projection_wins", prof.get("observe_dir") == f"/vault/{member}/observe", str(prof))
            check(f"[{member}] role_is_launch_context", got.get("role") == "role:constellation:mesh-worker", str(got.get("role")))
            check(f"[{member}] digest", got.get("sha") == hashlib.sha256(p.read_bytes()).hexdigest())


def test_the_certifier_refuses_a_profile_default() -> None:
    sys.path.insert(0, str(REPO / "plugins" / "_shared"))
    import importlib
    cert = importlib.import_module("shim_certification_test")
    ok_node = ast.parse('os.environ.get("HESTIA_X")', mode="eval").body
    bad_node = ast.parse('os.environ.get("HESTIA_X", "~/.hestia")', mode="eval").body
    tup = ast.parse('(os.environ.get("HESTIA_X"),)', mode="eval").body
    check("certifier_admits_env_read", cert.profile_value_is_data(ok_node))
    check("certifier_admits_env_read_in_tuple", cert.profile_value_is_data(tup))
    check("certifier_refuses_default", not cert.profile_value_is_data(bad_node),
          "a two-argument env read is a hardcoded default, the #943 class")


def teardown_module(module):
    assert not FAILS, FAILS


TESTS = [test_every_shim_consumes_the_projection, test_the_certifier_refuses_a_profile_default]

if __name__ == "__main__":
    for t in TESTS:
        t()
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print("ok: every certified shim consumes the vault projection and nothing else")
