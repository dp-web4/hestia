#!/usr/bin/env python3
"""#1389 C: a print-only watcher's journal line is the only trace a seat can read, so it must carry the notice id
(and the id it answers), with `from <sender>:` kept adjacent for line readers.

Runs the EXACT `python3 -c` snippet from hestia-watch-member.sh's print-only branch on a fixture primer."""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "hestia-watch-member.sh")).read()
lines = [l for l in SRC.splitlines() if "print(f\\\"  id=" in l and "d['notices']" in l]
assert len(lines) == 1, f"expected one print-only line, found {len(lines)}"
m = re.search(r'python3 -c "(.*)"\s*$', lines[0].strip())
assert m, lines[0]
code = m.group(1).replace('\\"', '"')

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    fails += (not ok)

with tempfile.TemporaryDirectory() as d:
    primer = os.path.join(d, "notice-x.json")
    json.dump({"notices": [
        {"id": 1379, "kind": "reply", "from_plugin": "codex", "in_reply_to": 1378, "pointer_uri": "file:///m/a.md"},
        {"id": 1380, "kind": "coordination", "from_plugin": "claude-code", "pointer_uri": "file:///m/b.md"},
        {"kind": "ack", "from_plugin": "kimi-code", "pointer_uri": "file:///m/c.md"},
    ]}, open(primer, "w"))
    out = subprocess.run([sys.executable, "-c", code.replace("$PRIMER", primer)],
                         capture_output=True, text=True).stdout.splitlines()
check("one line per notice", len(out) == 3, out)
check("bound reply carries id and re", out[0] == "  id=1379 reply re=1378 from codex: file:///m/a.md", out[0] if out else "")
check("unbound notice carries id, no re", out[1] == "  id=1380 coordination from claude-code: file:///m/b.md", out[1] if len(out) > 1 else "")
check("a notice without an id says ?", out[2].startswith("  id=? ack from kimi-code:"), out[2] if len(out) > 2 else "")
check("`from <sender>:` stays adjacent", all(re.search(r"\bfrom [\w-]+: ", l) for l in out))
print(f"{'OK' if not fails else 'FAILED'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
