#!/usr/bin/env python3
"""#1389 A: a print-only watcher must not consume the inbox the member's live-session hooks peek.

1. Static: in hestia-watch-member.sh the loop drains ONLY when a fire command is set; print-only calls peek_new, and
   peek_new asks the daemon for a peek ({"peek": true}) through peek-new.py.
2. peek-new.py: each notice is reported once, stays reportable after a restart (seen ids persist), a notice without an
   id is never dropped, the seen file is bounded, and an unreadable response is reported as unknown (total 0 + error),
   never as a list."""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MM = os.path.join(HERE, "..")
SRC = open(os.path.join(MM, "hestia-watch-member.sh")).read()
PEEK = os.path.join(MM, "peek-new.py")

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    fails += (not ok)

# --- 1. static wiring
loop = re.search(r'\n  if \[ -n "\$FIRE" \]; then\n    OUT=\$\(drain \|\| echo \'\{"total":0\}\'\)\n  else\n    OUT=\$\(peek_new \|\| echo \'\{"total":0\}\'\)', SRC)
check("loop: drain only with a fire command, else peek_new", bool(loop))
check("no unconditional drain left in the loop", SRC.count("OUT=$(drain ||") == 1)
pn = re.search(r"^peek_new\(\) \{ mesh_rpc hestia_member_inbox '\{\"peek\": true\}' \| python3 \"\$WATCH_DIR/peek-new.py\" \"\$STATE/peeked-\$PLUGIN\.ids\"; \}$", SRC, re.M)
check("peek_new asks for a peek and filters through peek-new.py (per-member seen file)", bool(pn))

# --- 2. peek-new.py behaviour
def run(seen, payload):
    p = subprocess.run([sys.executable, PEEK, seen], input=payload if isinstance(payload, str) else json.dumps(payload),
                       capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)

with tempfile.TemporaryDirectory() as d:
    seen = os.path.join(d, "sub", "peeked-x.ids")
    inbox = {"notices": [{"id": 7, "kind": "reply", "from_plugin": "codex"}, {"id": 8, "kind": "coordination", "from_plugin": "codex"}],
             "total": 2, "peeked": True}
    rc, o = run(seen, inbox)
    check("first peek reports both", rc == 0 and o["total"] == 2 and [n["id"] for n in o["notices"]] == [7, 8], o)
    rc, o = run(seen, inbox)
    check("second peek of the same queue reports nothing new", rc == 0 and o["total"] == 0 and o["notices"] == [], o)
    inbox2 = dict(inbox, notices=inbox["notices"] + [{"id": 9, "kind": "ack", "from_plugin": "kimi-code"}], total=3)
    rc, o = run(seen, inbox2)
    check("a new arrival is reported alone", o["total"] == 1 and o["notices"][0]["id"] == 9, o)
    check("seen ids persist on disk (survive a watcher restart)", open(seen).read().split() == ["7", "8", "9"])
    noid = {"notices": [{"kind": "disposition", "from_plugin": "hestia", "pointer_uri": "hestia://scope/x"}], "total": 1}
    rc, o1 = run(seen, noid); rc, o2 = run(seen, noid)
    check("a notice without an id is reported every time, never dropped", o1["total"] == 1 and o2["total"] == 1)
    rc, o = run(seen, "not json")
    check("unreadable response -> total 0 with peek_error (unknown, not a list)", rc == 0 and o["total"] == 0 and "peek_error" in o, o)
    big = os.path.join(d, "big.ids")
    open(big, "w").write("\n".join(str(i) for i in range(6000)) + "\n")
    rc, o = run(big, {"notices": [{"id": 999999, "kind": "reply", "from_plugin": "codex"}], "total": 1})
    kept = open(big).read().split()
    check("seen file bounded to the newest 5000", len(kept) == 5000 and kept[-1] == "999999", len(kept))

print(f"{'OK' if not fails else 'FAILED'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
