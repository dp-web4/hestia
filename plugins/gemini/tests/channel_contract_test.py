#!/usr/bin/env python3
r"""Assert the TWO-CHANNEL deny contract of ../hooks/before_tool.py (CBP, 2026-07-28).

The gate blocks two different ways on purpose (see "TWO DENY CHANNELS" in the gate's docstring):

    POLICY deny  (the gate reached a verdict) -> exit 0 + stdout JSON  -> deny, no operator banner
    ANOMALY deny (the gate could not judge)   -> exit 2 + stderr text  -> deny, WITH the banner

gate_holes_test.py already asserts that each *case* lands on the right channel. This file asserts
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
# Since one-gate stage C the shim is the certified template over the common gate: it reads ONLY
# its vault projection under HESTIA_HOME, and the gate is loaded from the projection's
# HESTIA_SHARED_DIR. The fixture stages both, with a CLOSED endpoint, so no live daemon matters:
# with no policy snapshot every act is denied, and an innate egress refusal keeps its own rule
# (a real verdict, so the clean channel) while everything else is the infrastructure denial
# (an anomaly, so the banner). Sandbox not under /tmp (the gate grants /tmp as a root).
V = os.environ.get("HESTIA_GATETEST_DIR", os.path.expanduser("~/.cache/hestia-gemini-channeltest"))
shutil.rmtree(V, ignore_errors=True)
HOME = os.path.join(V, "hestia-home")
SHARED = os.path.join(V, "shared")
os.makedirs(os.path.join(V, "ws", "web4"))
os.makedirs(os.path.join(HOME, "seats"))
os.makedirs(SHARED)
_TREE_SHARED = os.path.join(HERE, "..", "..", "_shared")
# Staging seam (unset in the repo and in CI): {module: path} in place of the tree's copies.
_OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
for _name in os.listdir(_TREE_SHARED):
    if _name.startswith("hestia_") and _name.endswith(".py") and "_test" not in _name:
        shutil.copy(_OVERLAY.get(_name[:-3]) or os.path.join(_TREE_SHARED, _name),
                    os.path.join(SHARED, _name))
for _mod, _path in _OVERLAY.items():
    if _mod.startswith("hestia_"):
        shutil.copy(_path, os.path.join(SHARED, _mod + ".py"))
with open(os.path.join(HOME, "seats", "gemini.env"), "w") as f:
    f.write(f"# member: gemini\nHESTIA_HOME={HOME}\nHESTIA_SHARED_DIR={SHARED}\n"
            f"HESTIA_ENDPOINT=http://127.0.0.1:1/mcp\nHESTIA_WORKSPACE={os.path.join(V, 'ws')}\n")
ENV = {k: v for k, v in os.environ.items()
       if k not in ("HESTIA_SHARED_DIR", "HESTIA_ENDPOINT", "HESTIA_WORKSPACE", "HESTIA_GATE_MODE")}
# The test is the hook's invoker, so it declares the timeout it enforces (subprocess default
# below is none; 20 s is ample) and the gate decides inside it. HOME is the fixture: inheriting
# the operator's real home would leak the LIVE seat's registration (~/.gemini/settings.json),
# which names this hook's basename without binding this fixture shim exactly — MISWIRED
# (ambiguous hook ownership) under the critical-timeout protocol (#1262).
ENV.update(HESTIA_HOME=HOME, HESTIA_HOOK_TIMEOUT_S="20", HOME=HOME)
CWD = os.path.join(V, "ws", "web4")
FORBIDDEN = "sec" + "rets"   # assembled: this file's text must not carry the token the gate matches


def fire(event):
    r = subprocess.run([sys.executable, GATE], input=event, capture_output=True, text=True,
                       env=ENV, timeout=60)
    return r.returncode, r.stdout, r.stderr


# An innate egress refusal: a policy verdict, so it must take the clean channel.
code, out, err = fire(json.dumps({"hook_event_name": "BeforeTool", "cwd": CWD,
                                 "tool_name": "read_file",
                                 "tool_input": {"absolute_path": f"{CWD}/{FORBIDDEN}/token"}}))
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
      isinstance(payload, dict) and "[egress.secret]" in payload.get("reason", ""), True)

# Unreadable event: the gate never got to judge -> anomaly channel.
code, out, err = fire("not json at all")
check("live anomaly -> exit 2", code, 2)
check("live anomaly -> runner denies", decide(code, out, err)[0], "deny")
check("live anomaly -> raises the operator banner", decide(code, out, err)[2], True)
check("live anomaly -> nothing on fd 1 (the reason rides stderr)", out.strip(), "")

# An absent daemon is a malfunction, not a verdict: it must NOT be laundered into a clean deny.
code, out, err = fire(json.dumps({"hook_event_name": "BeforeTool", "cwd": CWD,
                                 "tool_name": "write_file",
                                 "tool_input": {"file_path": "main.py", "content": "x"}}))
check("absent daemon -> denies", decide(code, out, err)[0], "deny")
check("absent daemon -> banner raised (a missing daemon must be visible)",
      decide(code, out, err)[2], True)

shutil.rmtree(V, ignore_errors=True)
print(f"\nfailures={failures}")
sys.exit(1 if failures else 0)
