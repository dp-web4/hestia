#!/usr/bin/env python3
"""Plumbing tests for tools/one_gate_census.py. No daemon, no gate, no live port.

What is pinned here is what the census's safety and verdicts rest on:
  - the sitecustomize guard REFUSES and logs a connect to a guarded port (raw socket and urllib),
    and leaves every other port alone. The guarded port is a free one this test binds, never the
    live daemon's;
  - the guard refuses a write outside the throwaway dir, allows one inside, and redirects the
    engine's hard-coded /tmp/hestia-actions cache under the throwaway (here: a stand-in path);
  - the census's MCP client refuses to speak to a live port;
  - a harness whose config directory is absent is reported "absent" (no probe runs, no failure);
  - session evidence decides "in use" vs "installed, not in use";
  - the self-write ratchet: a known-open entry that starts passing is STALE.

Run: python3 tools/one_gate_census_test.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import one_gate_census as census  # noqa: E402

REPO = HERE.parent


def _listener() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s


def _guard_dir(tmp: Path) -> Path:
    g = tmp / "guard"
    g.mkdir()
    (g / "sitecustomize.py").write_text(census.GUARD_SOURCE)
    return g


def _env(tmp: Path, guard: Path, ports: str, root: Path, redirect: str = "") -> dict:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "HOME")}
    env.update({"PYTHONPATH": str(guard), "PYTHONDONTWRITEBYTECODE": "1",
                "ONE_GATE_CENSUS_GUARD_PORTS": ports,
                "ONE_GATE_CENSUS_GUARD_LOG": str(tmp / "blocked.log"),
                "ONE_GATE_CENSUS_ARMED_LOG": str(tmp / "armed.log"),
                "ONE_GATE_CENSUS_WRITE_ROOT": str(root),
                "ONE_GATE_CENSUS_RUN": "t", "ONE_GATE_CENSUS_REDIRECT": redirect})
    return env


def test_guard_refuses_the_guarded_port_and_only_it():
    tmp = Path(tempfile.mkdtemp(prefix="ogc-test-", dir="/tmp"))
    guarded, open_ = _listener(), _listener()
    try:
        gp, op = guarded.getsockname()[1], open_.getsockname()[1]
        assert census.LIVE_DEFAULT_PORT not in (gp, op)
        probe = tmp / "probe.py"
        probe.write_text(
            "import socket, sys, urllib.request\n"
            "gp, op = int(sys.argv[1]), int(sys.argv[2])\n"
            "out = []\n"
            "try:\n"
            "    socket.create_connection(('127.0.0.1', gp), timeout=2); out.append('raw-connected')\n"
            "except ConnectionRefusedError: out.append('raw-refused')\n"
            "try:\n"
            "    urllib.request.urlopen('http://127.0.0.1:%d/mcp' % gp, timeout=2); out.append('url-connected')\n"
            "except OSError as e: out.append('url-refused')\n"
            "socket.create_connection(('127.0.0.1', op), timeout=2).close(); out.append('other-ok')\n"
            "print(' '.join(out))\n")
        env = _env(tmp, _guard_dir(tmp), str(gp), tmp)
        out = subprocess.run([sys.executable, str(probe), str(gp), str(op)], env=env,
                             capture_output=True, text=True, timeout=30)
        assert out.stdout.split() == ["raw-refused", "url-refused", "other-ok"], (out.stdout, out.stderr)
        log = (tmp / "blocked.log").read_text().splitlines()
        assert len(log) == 2 and all(f":{gp}" in ln for ln in log), log
        assert "armed run=t" in (tmp / "armed.log").read_text()
    finally:
        guarded.close()
        open_.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_guard_refuses_writes_outside_the_throwaway_and_redirects():
    tmp = Path(tempfile.mkdtemp(prefix="ogc-test-", dir="/tmp"))
    outside = Path(tempfile.mkdtemp(prefix="ogc-test-outside-", dir="/tmp"))
    try:
        root = tmp / "root"
        root.mkdir()
        target = root / "redirected"
        target.mkdir()
        hard_coded = outside / "hard-coded-cache"      # stands in for /tmp/hestia-actions
        probe = tmp / "probe.py"
        probe.write_text(
            "import sys\nfrom pathlib import Path\n"
            "root, outside, hard = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])\n"
            "out = []\n"
            "(root / 'in.txt').write_text('x'); out.append('inside-ok')\n"
            "try:\n"
            "    (outside / 'out.txt').write_text('x'); out.append('outside-written')\n"
            "except PermissionError: out.append('outside-refused')\n"
            "hard.mkdir(parents=True, exist_ok=True)\n"
            "(hard / 'k.json').write_text('{}')\n"
            "out.append('redirect-read=' + (hard / 'k.json').read_text())\n"
            "(hard / 'k.json').unlink(); out.append('redirect-unlink-ok')\n"
            "print(' '.join(out))\n")
        env = _env(tmp, _guard_dir(tmp), "", root, redirect=f"{hard_coded}=>{target}")
        out = subprocess.run([sys.executable, str(probe), str(root), str(outside), str(hard_coded)],
                             env=env, capture_output=True, text=True, timeout=30)
        assert out.stdout.split() == ["inside-ok", "outside-refused", "redirect-read={}",
                                      "redirect-unlink-ok"], (out.stdout, out.stderr)
        assert not (outside / "out.txt").exists()
        assert not hard_coded.exists(), "the redirected path must never be created on the host"
        log = (tmp / "blocked.log").read_text().splitlines()
        assert len(log) == 1 and "out.txt" in log[0], log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_mcp_client_refuses_a_live_port():
    try:
        census.Mcp("http://127.0.0.1:7711/mcp", {7711})
    except census.SetupError:
        return
    raise AssertionError("the census client must refuse the live daemon's port")


def _census(home: Path) -> census.Census:
    args = argparse.Namespace(home=str(home), hestia_home=str(home / ".hestia"), deploy_repo=str(REPO),
                              in_use_days=30.0, workspace=None, member=None, keep=False,
                              daemon_bin="/nonexistent", json_path=None)
    c = census.Census(args)
    c.registrar = census.load_module(REPO / "deploy" / "register-members.py", "t_register_members")
    return c


def test_an_absent_harness_is_absent_not_a_failure():
    home = Path(tempfile.mkdtemp(prefix="ogc-test-home-", dir="/tmp"))
    c = _census(home)
    try:
        rows = [c.seat(e, {"HESTIA_HOME": str(home / ".hestia")}, {}, None)
                for e in sorted((REPO / "plugins").glob("*/expects.json"))]
        rows = [r for r in rows if r is not None]
        assert {r["seat"] for r in rows} >= {"claude-code", "codex", "gemini", "kimi-code"}, rows
        assert all(r["state"] == "absent" for r in rows), [(r["seat"], r["state"]) for r in rows]
        assert c.runs == [], "no probe may run for an absent harness"
    finally:
        shutil.rmtree(c.root, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


def test_session_evidence_decides_use():
    home = Path(tempfile.mkdtemp(prefix="ogc-test-home-", dir="/tmp"))
    try:
        chats = home / ".gemini" / "tmp" / "workspace" / "chats"
        chats.mkdir(parents=True)
        old = chats / "session-old.jsonl"
        old.write_text("{}")
        long_ago = time.time() - 90 * 86400
        os.utime(old, (long_ago, long_ago))
        ev = census.session_evidence(home, "gemini", 30)
        assert ev["files"] == 1 and ev["files_in_window"] == 0, ev
        (chats / "session-new.jsonl").write_text("{}")
        ev = census.session_evidence(home, "gemini", 30)
        assert ev["files"] == 2 and ev["files_in_window"] == 1, ev
        assert census.session_evidence(home, "no-such-harness", 30)["files"] == 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_self_write_ratchet():
    law = {"denied": True, "said": "hestia: deny [gate.self_access] — 'Bash' would WRITE the governance surface"}
    infra = {"denied": True, "said": "hestia: deny [config.unbacked] — HESTIA_HOME is not set"}
    allowed = {"denied": False, "said": ""}
    known = next(iter(census.KNOWN_OPEN))[0]
    assert census.judge_self_write(known, allowed)[0] == "known-open"
    assert census.judge_self_write(known, law)[0] == "stale"
    assert census.judge_self_write("no-such-member", law)[0] == "pass"
    assert census.judge_self_write("no-such-member", allowed)[0] == "fail"
    assert census.judge_self_write("no-such-member", infra)[0] == "fail"


def test_unit_file_env_follows_drop_ins_like_systemd():
    # HUB's layout (hestia#1252): the base unit empties HESTIA_WORKSPACE, a drop-in sets it. Read
    # without the drop-in, the census rendered codex without HESTIA_WORKSPACE and reported a false drift.
    with tempfile.TemporaryDirectory() as d:
        unit = Path(d) / "hestia-deploy.service"
        unit.write_text("[Unit]\nEnvironment=HESTIA_WORKSPACE=/not/service/section\n[Service]\n"
                        "Environment=HESTIA_HOME=%h/.hestia\nEnvironment=HESTIA_WORKSPACE=\n"
                        "Environment=\"PATH=/a b\" OTHER=1\n")
        assert census.unit_file_env(unit, Path("/home/x")) == {"HESTIA_HOME": "/home/x/.hestia",
                                                              "HESTIA_WORKSPACE": ""}
        drop = Path(d) / "hestia-deploy.service.d"
        drop.mkdir()
        (drop / "20-late.conf").write_text("[Service]\nEnvironment=HESTIA_WORKSPACE=/w/late\n")
        (drop / "10-workspace.conf").write_text("[Service]\nEnvironment=HESTIA_WORKSPACE=/w/early\n")
        assert census.unit_file_env(unit, Path("/home/x"))["HESTIA_WORKSPACE"] == "/w/late", "lexical, last wins"
        (drop / "30-reset.conf").write_text("[Service]\nEnvironment=\nEnvironment=HESTIA_HOME=/h%%\n")
        assert census.unit_file_env(unit, Path("/home/x")) == {"HESTIA_HOME": "/h%"}, "empty Environment= resets"
        assert census.unit_file_env(Path(d) / "absent.service") == {}


def test_fallback_env_marks_a_drift_unverified():
    reg = {"status": "drift", "changes": ["codex PreToolUse: drop HESTIA_WORKSPACE"], "notes": [],
           "unverified": "rendered against fallback (--hestia-home/--workspace), not the deploy unit's env"}
    assert "UNVERIFIED" in census.cell({"registration": reg}, "registration")
    reg.pop("unverified")
    assert "UNVERIFIED" not in census.cell({"registration": reg}, "registration")


TESTS = [
    test_guard_refuses_the_guarded_port_and_only_it,
    test_guard_refuses_writes_outside_the_throwaway_and_redirects,
    test_mcp_client_refuses_a_live_port,
    test_an_absent_harness_is_absent_not_a_failure,
    test_session_evidence_decides_use,
    test_self_write_ratchet,
    test_unit_file_env_follows_drop_ins_like_systemd,
    test_fallback_env_marks_a_drift_unverified,
]


def main() -> int:
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: {sorted(defined ^ listed)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
