"""The UNDER-match half of the gate's command check, measured (hestia #1025).

#1025 is about gate 1a being too LOOSE with its substring scan — it refuses honest text
for containing a forbidden word. This is the same defect from the other side, one function
over, in gate 1b: `command_scope_reach` is too PERMISSIVE about absolute paths.

command_scope_reach judges a command by splitting it on the WORKSPACE string, so an
absolute path that never names the workspace is never a token it sees. Layer 1's
path_candidates() resolves actual argv path arguments instead. Same commands, both checks.
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugins", "_shared"))
sys.path.insert(0, HERE)
from hestia_gate_core import command_scope_reach
from gate_resolved_act import path_candidates

# Synthetic paths: the check is lexical over argv, so nothing needs to exist on disk.
WS = "/home/user/ai-workspace/SAGE"
HOME = "/home/user"
# one granted repo scope, the shape a member actually carries
SCOPES = ["sage"]

def in_scope_resolved(cmd, scopes, ws, cwd):
    """What the check WOULD say if it judged resolved path arguments (Layer 1 primitive)."""
    roots = [os.path.join(ws, s) for s in scopes]
    for p in path_candidates(cmd, cwd):
        ap = os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))
        if not any(ap == r or ap.startswith(r + os.sep) for r in roots):
            return False, p
    return True, None

CASES = [
    ("in scope",          f"grep -rn -e x -- {WS}/sage/gateway",            True),
    ("sibling repo",      f"grep -rn -e x -- {WS}/docs",                    False),
    ("off the workspace", "grep -rn -e x -- /etc",                          False),
    ("operator dotfiles", f"grep -rn -e x -- {HOME}/." + "config",          False),
    ("absolute tmp",      "cat /tmp/whatever.txt",                          False),
    ("relative in scope", "cat sage/gateway/heartbeat.py",                  True),
]
print(f"{'case':20} {'truth':6} {'live: split-on-workspace':26} {'resolved-arg (Layer 1)'}")
live_wrong = res_wrong = 0
for name, cmd, truth in CASES:
    ok_live, off, _ = command_scope_reach(cmd, SCOPES, WS, cwd=WS)
    ok_res, off_r = in_scope_resolved(cmd, SCOPES, WS, WS)
    live_wrong += (ok_live != truth)
    res_wrong  += (ok_res  != truth)
    m = lambda ok: ("allow" if ok else "DENY") + (" <-WRONG" if ok != truth else "")
    print(f"{name:20} {str(truth):6} {m(ok_live):26} {m(ok_res)}")
print(f"\nwrong verdicts: live {live_wrong}/{len(CASES)}   resolved-arg {res_wrong}/{len(CASES)}")
