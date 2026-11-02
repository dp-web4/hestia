"""hestia #1450 phase 0 step A, over git HEAD (never the working file): the gate's policy-snapshot fetch sends the
session it already holds to hestia_scope_status. Two lines earlier it passes the same session to hestia_operating_law;
scope_status took `plugin_id` on trust. Behaviour is unchanged on a daemon without step B (it ignores the field); on one
with step B the read is caller-bound, and step C (refusing reads with no session) becomes possible once every machine's
hooks carry this. Writes source-1450a.diff beside this file. argv: <worktree>"""
import difflib
import pathlib
import subprocess
import sys

wt = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
rel = "plugins/_shared/hestia_gate_mechanism.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()
old = '''        stage = "scope_status"
        scope = _unwrap_tool_result(
            client.call_tool("hestia_scope_status", {"plugin_id": plugin_id}))
'''
new = '''        stage = "scope_status"
        # The session goes with the read (hestia #1450 phase 0): scope_status returns this member's grants
        # and request history, and a daemon that binds the read to its caller answers only for the member
        # whose session asks. This is the session hestia_operating_law was just sent.
        scope = _unwrap_tool_result(
            client.call_tool("hestia_scope_status", {"plugin_id": plugin_id, "session_id": session_id}))
'''
assert src.count(old) == 1, src.count(old)
out = src.replace(old, new)
diff = "".join(difflib.unified_diff(src.splitlines(True), out.splitlines(True), f"a/{rel}", f"b/{rel}"))
(here / "source-1450a.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("source diff lines:", diff.count("\n"))
