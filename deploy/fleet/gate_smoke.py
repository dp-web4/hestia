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

Witnessed, PER STEP (GPT-6 review of #1448: one before/after count let the operator grant alone
satisfy "the daemon witnessed both decisions"). After each step the probe reads the chain entries
that step appended (operator-authenticated /api/chain, signed with the operator key the daemon
minted at genesis) and requires:
  1. a policy_decision DENY for the Read, under an mrh rule
  2. a policy_decision DENY for the Bash self-write, under the gate's governance rule
  3. new entries for the grant, and NO policy_decision among them (the grant is not a decision)
  4. a policy_decision ALLOW for the Read: affirmative evidence, not merely "not denied"

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

    def chain_tail() -> list[dict]:
        status, body = op.call("GET", "/api/chain?limit=200")
        if status != 200 or not isinstance(body, dict) or body.get("read_error"):
            raise SystemExit(f"FAIL /api/chain answered {status}: {json.dumps(body)[:200]}")
        return sorted(body.get("entries") or [], key=lambda e: e["chain_position"])

    mark = [max((e["chain_position"] for e in chain_tail()), default=-1)]

    def appended() -> list[dict]:
        """The entries appended since the last call (the previous step's mark)."""
        new = [e for e in chain_tail() if e["chain_position"] > mark[0]]
        if new:
            mark[0] = new[-1]["chain_position"]
        return new

    def decisions(entries, tool, verdict):
        return [e for e in entries if e.get("event_type") == "policy_decision"
                and e.get("tool_name") == tool and (e.get("decision") or "").lower() == verdict]

    def show(entries) -> str:
        return ", ".join(f"#{e['chain_position']} {e.get('event_type')}"
                         + (f" {e.get('decision')}/{e.get('rule_name')}" if e.get("decision") else "")
                         for e in entries) or "nothing"

    def witnessed(label, entries, ok):
        print(f"{'ok  ' if ok else 'FAIL'}   chain for {label}: {show(entries)}")
        if not ok:
            fails.append(f"chain evidence for {label}")

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
    new = appended()
    witnessed("the fresh-seat Read", new,
              any("mrh" in (e.get("rule_name") or "") for e in decisions(new, "Read", "deny")))

    # 2. The law: a write to the gate's own file is refused as a governance-surface write.
    d, rc, why = run(self_ev)
    ok = d and bool(LAW_REASON.search(why))
    print(f"{'ok  ' if ok else 'FAIL'} deny: self-write of the gate -> {'denied' if d else 'ALLOWED'} (rc={rc}) {why}")
    if not ok:
        fails.append("self-write probe")
    new = appended()
    witnessed("the self-write", new, any(LAW_REASON.search((e.get("rule_name") or "") + " " + (e.get("reason") or ""))
                                         for e in decisions(new, "Bash", "deny")))

    # 3. The operator grants the seat its workspace (what an operator does on the dashboard).
    status, body = op.call("POST", "/api/scope/grant", {
        "plugin_id": "claude-code", "path": str(ws), "recursive": True,
        "reason": "install smoke (#1443): the operator grants the seat its workspace"})
    ok = status == 200
    print(f"{'ok  ' if ok else 'FAIL'} operator grant of the workspace -> {status} {json.dumps(body)[:200]}")
    if not ok:
        fails.append("operator grant")
    new = appended()
    witnessed("the operator grant (no policy_decision may count it)", new,
              bool(new) and not any(e.get("event_type") == "policy_decision" for e in new))

    # 4. Now the same read is allowed: the gate decides by the daemon's grant.
    d, rc, why = run(read_ev)
    ok = not d
    print(f"{'ok  ' if ok else 'FAIL'} granted: Read inside the workspace -> {'denied' if d else 'allowed'} (rc={rc}) {why}")
    if not ok:
        fails.append("granted read was refused")
    new = appended()
    witnessed("the granted Read (an ALLOW decision)", new, bool(decisions(new, "Read", "allow")))
    if fails:
        print("FAIL: " + "; ".join(fails))
        return 1
    print("PASS: each gate decision (deny, deny, allow) is its own policy_decision on the daemon's chain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
