#!/usr/bin/env python3
"""probe_forlist_3647 — replicate claude-code notice-3647 finding 1 on the kimi seat.

Claude's seat (2026-08-19, forum/claude-code/reply-3640): a `for` value list naming
closure markers was REFUSED while a `python3 -c` body naming the same markers ran —
"the command HEAD selects the matcher, the marker's presence does not."

This drives the INSTALLED kimi shim hook (same payload shape the harness sends, same
env the config.toml hook line sets) over three arms:
  ctl-write : redirect into the closure (must REFUSE — positive control)
  for-loop  : for-list naming closure markers, grep read body (claude seat: REFUSED)
  python-c  : python3 -c body naming the same markers (claude seat: ALLOWED)

The probe itself never executes the refused commands; it asks the gate for a verdict.
Exit codes from the hook: 0 = allow, 2 = block (stderr = reason).
"""
import json
import os
import subprocess

HOOK = "/home/dp/.kimi-code/hooks/pre_tool_use.py"
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hestia repo
ROOT = os.path.dirname(WS)                                        # workspace root

ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.path.expanduser("~"),
    "HESTIA_WORKSPACE": ROOT,
    "HESTIA_PRE_TOTAL_BUDGET_MS": "14000",
    "HESTIA_SOCIETY_GATE": "/home/dp/.kimi-code/hooks/society_pre_tool_use.py",
    "HESTIA_ROLE": "role:constellation:interactive-dev",
}

ARMS = [
    ("ctl-write", "echo x > plugins/_shared/hestia_gate_core.py"),
    ("for-loop",
     'for f in plugins/_shared/hestia_gate_core.py plugins/kimi/hooks/pre_tool_use.py; '
     'do grep -n marker "$f"; done'),
    ("python-c",
     "python3 -c \"print(open('plugins/_shared/hestia_gate_core.py').read()"
     ".count('plugins/_shared'))\""),
]


def probe(cmd: str):
    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
        "session_id": "probe-3647",
        "cwd": WS,
    })
    r = subprocess.run(["/usr/bin/python3", HOOK], input=payload,
                       capture_output=True, text=True, timeout=60, env=ENV)
    reason = (r.stderr.strip().splitlines() or [""])[0][:200]
    if os.environ.get("PROBE_VERBOSE"):
        print(f"  [rc={r.returncode}] stdout={r.stdout[:400]!r}")
        print(f"  stderr={r.stderr[:600]!r}")
    return r.returncode, reason


def main():
    for name, cmd in ARMS:
        rc, reason = probe(cmd)
        verdict = "REFUSED" if rc == 2 else ("ALLOW" if rc == 0 else f"rc={rc}")
        print(f"{name:10s} {verdict:8s} {reason}")


if __name__ == "__main__":
    main()
