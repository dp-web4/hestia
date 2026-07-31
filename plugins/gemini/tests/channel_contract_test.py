#!/usr/bin/env python3
r"""Assert the TWO-CHANNEL deny contract of ../hooks/before_tool.py (CBP, 2026-07-28).

The gate blocks two different ways on purpose (see "TWO DENY CHANNELS" in the gate's docstring):

    POLICY deny  (the gate reached a verdict) -> exit 0 + stdout JSON  -> deny, no operator banner
    ANOMALY deny (the gate could not judge)   -> exit 2 + stderr text  -> deny, WITH the banner

gate_holes_repro.sh already asserts that each *case* lands on the right channel. This file asserts
the thing that makes the split correct in the first place - the property that would silently rot if
someone later "simplified" both channels back into one:

    the SAME corrupted payload is an ALLOW at exit 0 and a DENY at exit 2.

That asymmetry is why policy denies (where the gate fully owns fd 1, and a corrupt payload is a bug
we can rule out) may use exit 0, while anomalies (crash, unreadable event, unreachable governor -
exactly the states where output is most likely to be truncated or interleaved) must not.

Part 2 checks the guard that keeps the exit-0 path's assumption true: on a policy deny, fd 1 carries
the decision object and NOTHING else, so there is no way for a stray write to shadow or corrupt it.

Usage: ./channel_contract_test.py [path/to/before_tool.py]
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "before_tool.py")
sys.path.insert(0, HERE)
from runner_decision import decide  # noqa: E402  the fidelity model of gemini's own parser

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  got={got!r} want={want!r}  {label}")


# --- Part 1: the asymmetry that justifies the split -------------------------------------------
# A well-formed deny blocks on either channel; a MANGLED one only blocks on the exit-2 channel.
GOOD = json.dumps({"decision": "deny", "reason": "hestia: deny [scope] - out of scope"})
TRUNCATED = GOOD[:len(GOOD) // 2]          # a short write / a crash mid-payload
PREFIXED = "some stray debug line\n" + GOOD  # a print() added by a future maintainer

check("policy channel: intact payload blocks", decide(0, GOOD, "")[0], "deny")
check("policy channel: intact payload is banner-free", decide(0, GOOD, "")[2], False)
check("policy channel: TRUNCATED payload FAILS OPEN (this is the risk being bounded)",
      decide(0, TRUNCATED, "")[0], "allow")
check("policy channel: PREFIXED payload FAILS OPEN (why fd 1 must be exclusive)",
      decide(0, PREFIXED, "")[0], "allow")
check("policy channel: empty stdout is an allow, so a deny must always emit",
      decide(0, "", "")[0], "allow")
check("anomaly channel: plain stderr text blocks", decide(2, "", "hestia: deny [gate] - x")[0], "deny")
check("anomaly channel: TRUNCATED text still blocks (fail-closed by exit code)",
      decide(2, TRUNCATED, "")[0], "deny")
check("anomaly channel: raises the operator banner", decide(2, "", "hestia: deny")[2], True)
check("exit 1 is an ALLOW+warning, never a deny (the gate must never exit 1)",
      decide(1, "", "hestia: deny [gate] - x")[0], "allow")

# --- Part 2: the live gate actually emits those shapes, and fd 1 is exclusive ------------------
# Sandbox must NOT be under /tmp: the gate grants /tmp as a root, which would make every
# out-of-scope path trivially contained (same constraint as gate_holes_repro.sh).
V = os.environ.get("HESTIA_GATETEST_DIR", os.path.expanduser("~/.cache/hestia-gemini-channeltest"))
shutil.rmtree(V, ignore_errors=True)
os.makedirs(os.path.join(V, "ws", "web4"))
os.makedirs(os.path.join(V, "ws", "private-context"))
with open(os.path.join(V, "ident.json"), "w") as f:
    f.write('{"mrh":{"in_scope":["repo:web4"]}}\n')
ENV = dict(os.environ, HESTIA_WORKSPACE=os.path.join(V, "ws"),
           HESTIA_GEMINI_IDENTITY=os.path.join(V, "ident.json"),
           HESTIA_GEMINI_LAUNCH_CWD=os.path.join(V, "ws", "web4"),
           HESTIA_SOCIETY_GATE="/nonexistent/governor.py",
           HESTIA_GEMINI_GATE_MODE="enforce")
CWD = os.path.join(V, "ws", "web4")


def fire(event):
    r = subprocess.run([sys.executable, GATE], input=event, capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout, r.stderr


# Gate-1b scope deny: a policy verdict, so it must take the clean channel.
code, out, err = fire(json.dumps({"hook_event_name": "BeforeTool", "cwd": CWD,
                                 "tool_name": "read_file",
                                 "tool_input": {"file_path": "../private-context/notes.md"}}))
check("live policy deny -> exit 0", code, 0)
check("live policy deny -> runner denies", decide(code, out, err)[0], "deny")
check("live policy deny -> no operator banner", decide(code, out, err)[2], False)
try:
    payload = json.loads(out)          # exclusivity: the WHOLE of stdout is the decision object
except Exception as exc:
    payload = f"unparseable ({exc})"
check("live policy deny -> fd 1 is exactly the decision object, nothing else",
      isinstance(payload, dict) and sorted(payload) == ["decision", "reason"], True)
check("live policy deny -> the reason still reaches the model",
      isinstance(payload, dict) and payload.get("reason", "").startswith("hestia: deny [scope]"), True)

# Unreadable event: the gate never got to judge -> anomaly channel.
code, out, err = fire("not json at all")
check("live anomaly -> exit 2", code, 2)
check("live anomaly -> runner denies", decide(code, out, err)[0], "deny")
check("live anomaly -> raises the operator banner", decide(code, out, err)[2], True)
check("live anomaly -> nothing on fd 1 (the reason rides stderr)", out.strip(), "")

# An absent governor is a malfunction, not a verdict: it must NOT be laundered into a clean deny.
# (`python3 /nonexistent/governor.py` exits 2 with stderr text - byte-identical to a real verdict.)
code, out, err = fire(json.dumps({"hook_event_name": "BeforeTool", "cwd": CWD,
                                 "tool_name": "write_file",
                                 "tool_input": {"file_path": "main.py", "content": "x"}}))
check("absent governor -> denies", decide(code, out, err)[0], "deny")
check("absent governor -> banner raised (a missing daemon must be visible)",
      decide(code, out, err)[2], True)

shutil.rmtree(V, ignore_errors=True)
print(f"\nfailures={failures}")
sys.exit(1 if failures else 0)
