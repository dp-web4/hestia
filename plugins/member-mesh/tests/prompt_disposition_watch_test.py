#!/usr/bin/env python3
"""The prompt-time disposition sweep (#366), upstreamed from kimi-code's own hook.

WHY. SessionStart reads the mesh inbox once, and a live session never looks again. An
approval sat unread while its 600 s claim window burned. kimi-code built
prompt-disposition-watch.sh for itself on 2026-08-27, and hestia shipped nothing
(findings/per-harness-witness-drift-2026-09-28.md, rec. 5). This pins the shipped copy's
behaviour against a stub `hestia-mesh.py peek`, running the REAL script:

  A. first run adopts the present as the baseline and prints NOTHING (no retro-surfacing);
  B. a newer disposition prints once, naming its pointer;
  C. the same inbox on the next prompt is silent (the watermark advanced);
  D. a newer NON-disposition notice is ignored;
  E. a failing peek, garbage output, or an unset member id exits 0 silently (fail-open, never
     breaks a prompt);
  F. the watermark is per MEMBER: another member's first run adopts its own baseline instead
     of inheriting this one's;
  G. the advice does not tell the reader to `gate poll`, which arms a co-seat's claim fuse on
     a shared plugin id (#732). Asserted on the OUTPUT, since that is what a member reads.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
WATCH = os.path.join(SRC, "prompt-disposition-watch.sh")

failures = []


def check(cond, label, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(label)


# The stub CLI prints whatever $STUB_PEEK holds and exits $STUB_RC, like the real peek.
STUB = '''#!/usr/bin/env python3
import os, sys
if sys.argv[1:] != ["peek"]:
    sys.exit(9)
sys.stdout.write(open(os.environ["STUB_PEEK"]).read())
sys.exit(int(os.environ.get("STUB_RC", "0")))
'''

hooks = tempfile.mkdtemp(prefix="dispwatch-hooks-")
state = tempfile.mkdtemp(prefix="dispwatch-state-")
script = os.path.join(hooks, "prompt-disposition-watch.sh")
with open(WATCH) as a, open(script, "w") as b:
    b.write(a.read())
with open(os.path.join(hooks, "hestia-mesh.py"), "w") as fh:
    fh.write(STUB)
peek_file = os.path.join(state, "peek.json")


def inbox(*notices, raw=None):
    with open(peek_file, "w") as fh:
        fh.write(raw if raw is not None else json.dumps(
            {"total": len(notices), "notices": list(notices), "peeked": True}))


def n(i, kind, ptr="hestia://escalation/abc"):
    return {"id": i, "kind": kind, "from_plugin": "hestia", "pointer_uri": ptr}


def run(member="kimi-code", rc=0):
    env = {**os.environ, "HESTIA_MESH_STATE": state, "STUB_PEEK": peek_file, "STUB_RC": str(rc)}
    env.pop("HESTIA_MESH_PLUGIN", None)
    if member is not None:
        env["HESTIA_MESH_PLUGIN"] = member
    return subprocess.run(["sh", script], capture_output=True, text=True, timeout=30, env=env)


print("A. first run adopts the baseline")
inbox(n(5, "disposition", "hestia://escalation/old"), n(7, "reply"))
p = run()
check(p.returncode == 0 and p.stdout == "", "A1. prints nothing on first run", repr(p.stdout))
wm = os.path.join(state, "disposition-watermark", "kimi-code")
check(os.path.exists(wm) and open(wm).read().strip() == "7",
      "A2. watermark adopts the max id over ALL notices", repr(open(wm).read() if os.path.exists(wm) else None))

print("B. a newer disposition prints once")
inbox(n(5, "disposition", "hestia://escalation/old"), n(7, "reply"),
      n(9, "disposition", "hestia://escalation/new9"))
p = run()
check(p.returncode == 0, "B1. exits 0", str(p.returncode))
check("hestia://escalation/new9" in p.stdout, "B2. names the new disposition's pointer", repr(p.stdout))
check("hestia://escalation/old" not in p.stdout, "B3. does not re-surface the baseline one", repr(p.stdout))
check("1 new disposition" in p.stdout, "B4. counts only the new one", repr(p.stdout))

print("C. the next prompt over the same inbox is silent")
p = run()
check(p.returncode == 0 and p.stdout == "", "C1. silent once surfaced", repr(p.stdout))

print("D. a newer non-disposition notice is ignored")
inbox(n(9, "disposition", "hestia://escalation/new9"), n(12, "review_request"))
p = run()
check(p.returncode == 0 and p.stdout == "", "D1. a review_request does not print", repr(p.stdout))

print("E. every failure is silent and exits 0")
p = run(rc=1)
check(p.returncode == 0 and p.stdout == "", "E1. a failing peek", repr(p.stdout))
inbox(raw="not json {")
p = run()
check(p.returncode == 0 and p.stdout == "", "E2. unparseable peek output", repr(p.stdout))
inbox(n(20, "disposition"))
p = run(member=None)
check(p.returncode == 0 and p.stdout == "", "E3. unset HESTIA_MESH_PLUGIN", repr(p.stdout))
wm_dir = os.path.join(state, "disposition-watermark")
wms = sorted(os.listdir(wm_dir)) if os.path.isdir(wm_dir) else []
check(wms == ["kimi-code"], "E4. and writes no watermark under an empty member name", repr(wms))

print("F. the watermark is per member")
inbox(n(20, "disposition", "hestia://escalation/n20"))
p = run(member="codex")
check(p.returncode == 0 and p.stdout == "",
      "F1. another member's first run adopts its own baseline", repr(p.stdout))
p = run(member="kimi-code")
check("hestia://escalation/n20" in p.stdout,
      "F2. while this member still sees the ruling as new", repr(p.stdout))

print("G. the advice is safe on a shared plugin id")
inbox(n(20, "disposition"), n(25, "disposition", "hestia://escalation/n25"))
p = run(member="claude-code")      # first run: baseline
p = run(member="claude-code")
inbox(n(25, "disposition"), n(26, "disposition", "hestia://escalation/n26"))
p = run(member="claude-code")
check("hestia://escalation/n26" in p.stdout, "G1. fires for claude-code", repr(p.stdout))
out = p.stdout
check("co-seat" in out, "G2. says the ruling may belong to a co-seat", repr(out))
check("gate poll <" not in out and "poll: hestia gate poll" not in out,
      "G3. never tells the reader to check with gate poll", repr(out))
check("#732" in out, "G4. and names why not", repr(out))

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nall prompt-disposition-watch checks pass")
