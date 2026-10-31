#!/usr/bin/env python3
"""Drive a RELEASE-installed claude-code gate once each way, and prove the daemon decided (#1443).

Run after `deploy/fleet/install.sh` on a fresh host (CI: .github/workflows/install-smoke.yml, the
gate arm). It reads the PreToolUse gate line install.sh registered in ~/.claude/settings.json and
runs it the way Claude Code does (the line through /bin/sh, the event on stdin, the settings `env`
plus CLAUDECODE=1, cwd = the workspace):

  1. a Read inside HESTIA_WORKSPACE, before any grant -> refused narrowly (mrh): a fresh seat
     holds no scope, because the installer grants nothing (scope is the operator's act)
  2. `touch <the installed gate itself>`              -> refused FOR THE LAW (its governance
     surface), not for an infrastructure reason: a gate that cannot load its engine or
     projection refuses everything, and that deny proves nothing
  3. the operator grants the seat its workspace (POST /api/scope/grant, operator-signed)
  4. the same Read                                    -> allowed

Witnessed: the daemon's chain length (operator-authenticated /api/dashboard, signed with the
operator key the daemon minted at genesis) must grow across the two decisions.

argv: --src <the tag's source dir, for tools/seed_seat_config.py's operator client>
env:  HESTIA_HOME, HESTIA_WORKSPACE (both required; nothing is guessed)
Exit 0 pass, 1 fail. Prints one line per check.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GATE = "pre_tool_use.py"
SH = "/bin/sh"  # how Claude Code runs a hook line
LAW_REASON = re.compile(r"gate-self|governance surface|self-access", re.I)


def gate_line(settings: dict) -> str | None:
    found: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k, c in v.items():
                if k == "command" and isinstance(c, str):
                    found.append(c)
                else:
                    walk(c)
        elif isinstance(v, list):
            for c in v:
                walk(c)

    walk((settings.get("hooks") or {}).get("PreToolUse") or [])
    for cmd in found:
        if any(t.startswith("/") and Path(t).name == GATE for t in cmd.split()):
            return cmd
    return None


def target(cmd: str) -> str:
    return next(t for t in cmd.split() if t.startswith("/") and Path(t).name == GATE)


def denies(rc: int, out: str) -> bool:
    if rc != 0:
        return True
    try:
        v = json.loads(out)
    except ValueError:
        return False
    if not isinstance(v, dict):
        return False
    hso = v.get("hookSpecificOutput") if isinstance(v.get("hookSpecificOutput"), dict) else {}
    return (v.get("permissionDecision") == "deny" or v.get("decision") in ("deny", "block")
            or hso.get("permissionDecision") == "deny")


def said(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tagged = [ln for ln in lines if re.search(r"\bdeny \[", ln)]
    return (tagged[0] if tagged else lines[-1] if lines else "")[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    a = ap.parse_args()
    home = Path(os.environ["HESTIA_HOME"])
    ws = Path(os.environ["HESTIA_WORKSPACE"])
    settings_path = Path(os.path.expanduser("~")) / ".claude" / "settings.json"
    fails = []

    settings = json.loads(settings_path.read_text())
    cmd = gate_line(settings)
    if not cmd:
        print(f"FAIL no PreToolUse {GATE} line in {settings_path}")
        return 1
    print(f"ok   registered: {cmd}")
    if "HESTIA_HOME=" not in cmd:
        fails.append("the gate line carries no HESTIA_HOME")
    if not (home / "shared").exists():
        fails.append(f"no shared engine at {home / 'shared'}")
    else:
        print(f"ok   shared engine: {home / 'shared'} -> {os.readlink(home / 'shared') if (home / 'shared').is_symlink() else 'dir'}")

    spec = importlib.util.spec_from_file_location("seed_seat_config", Path(a.src) / "tools" / "seed_seat_config.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    endpoint = (home / "endpoint").read_text().strip()
    op = seed.Operator(endpoint.rsplit("/mcp", 1)[0], home / "operator.key")
    op.open_session()

    def chain_length() -> int:
        status, body = op.call("GET", "/api/dashboard")
        if status != 200:
            raise SystemExit(f"FAIL /api/dashboard answered {status} to the operator session")
        return int(body["society"]["chain_length"])

    before = chain_length()

    env = dict(os.environ)
    env.update({k: v for k, v in (settings.get("env") or {}).items() if isinstance(v, str)})
    env["CLAUDECODE"] = "1"
    env.pop("HESTIA_ROLE", None)
    probe = ws / "hestia-gate-smoke.txt"
    probe.write_text("read me\n")
    def run(event):
        r = subprocess.run([SH, "-c", cmd], input=json.dumps(event), env=env, cwd=str(ws),
                           capture_output=True, text=True, timeout=60)
        return denies(r.returncode, r.stdout), r.returncode, (said(r.stderr) or said(r.stdout))

    read_ev = {"hook_event_name": "PreToolUse", "session_id": "hestia-install-smoke",
               "tool_name": "Read", "tool_input": {"file_path": str(probe)}}
    self_ev = {"hook_event_name": "PreToolUse", "session_id": "hestia-install-smoke",
               "tool_name": "Bash", "tool_input": {"command": f"touch {target(cmd)}"}}

    # 1. A fresh seat holds NO scope: the installer grants nothing (scope is the operator's), so
    #    even a read inside the workspace is refused, narrowly (mrh), and files a scope request.
    d, rc, why = run(read_ev)
    ok = d and "mrh" in why
    print(f"{'ok  ' if ok else 'FAIL'} fresh seat, no grant: Read inside the workspace -> {'denied' if d else 'ALLOWED'} (rc={rc}) {why}")
    if not ok:
        fails.append("fresh-seat read was not a narrow scope refusal")

    # 2. The law: a write to the gate's own file is refused as a governance-surface write.
    d, rc, why = run(self_ev)
    ok = d and bool(LAW_REASON.search(why))
    print(f"{'ok  ' if ok else 'FAIL'} deny: self-write of the gate -> {'denied' if d else 'ALLOWED'} (rc={rc}) {why}")
    if not ok:
        fails.append("self-write probe")

    # 3. The operator grants the seat its workspace (what an operator does on the dashboard).
    status, body = op.call("POST", "/api/scope/grant", {
        "plugin_id": "claude-code", "path": str(ws), "recursive": True,
        "reason": "install smoke (#1443): the operator grants the seat its workspace"})
    ok = status == 200
    print(f"{'ok  ' if ok else 'FAIL'} operator grant of the workspace -> {status} {json.dumps(body)[:200]}")
    if not ok:
        fails.append("operator grant")

    # 4. Now the same read is allowed: the gate decides by the daemon's grant.
    d, rc, why = run(read_ev)
    ok = not d
    print(f"{'ok  ' if ok else 'FAIL'} granted: Read inside the workspace -> {'denied' if d else 'allowed'} (rc={rc}) {why}")
    if not ok:
        fails.append("granted read was refused")

    after = chain_length()
    grew = after > before
    print(f"{'ok  ' if grew else 'FAIL'} witnessed: chain {before} -> {after}")
    if not grew:
        fails.append("the chain did not grow across the gate decisions")
    if fails:
        print("FAIL: " + "; ".join(fails))
        return 1
    print("PASS: the release-installed gate decides through the daemon and the daemon witnesses it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
