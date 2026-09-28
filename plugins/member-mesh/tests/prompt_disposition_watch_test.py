#!/usr/bin/env python3
"""The prompt-time disposition sweep (#366), upstreamed from kimi-code's own hook.

WHY. SessionStart reads the mesh inbox once, and a live session never looks again. An
approval sat unread while its 600 s claim window burned. kimi-code built
prompt-disposition-watch.sh for itself on 2026-08-27, and hestia shipped nothing
(findings/per-harness-witness-drift-2026-09-28.md, rec. 5). This pins the shipped copy's
behaviour against a stub `hestia-mesh.py peek`, running the REAL script with a real hook
event on stdin:

  A. a new session's first prompt: history older than the look-back stays silent; a ruling
     queued inside the look-back is shown (it may have landed before the watch looked);
  B. a newer disposition prints once, and the next prompt in that session is silent;
  C. a newer NON-disposition notice is ignored;
  D. GPT's hold on #1148, reproduced: two sessions, ONE member id, the sibling prompts first.
     The asker must still be shown its ruling. Under the first cut (one watermark per member)
     the sibling's prompt advanced it and the asker saw nothing;
  E. no usable session id: shows the recent ruling, records NOTHING (a later session still
     sees it), and says the line will repeat;
  F. every failure (failing peek, garbage output, unset member id) exits 0 silently;
  G. the advice never tells the reader to `gate poll` (#732). Asserted on the OUTPUT, since
     that is what a member reads;
  H. per-session files past the TTL are pruned, and a session id never becomes a path.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
WATCH = os.environ.get("DISPWATCH_UNDER_TEST") or os.path.join(SRC, "prompt-disposition-watch.sh")

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


def stamp(age_s):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")      # the daemon's nanosecond RFC3339


def inbox(*notices, raw=None):
    with open(peek_file, "w") as fh:
        fh.write(raw if raw is not None else json.dumps(
            {"total": len(notices), "notices": list(notices), "peeked": True}))


def n(i, kind, ptr=None, age=30):
    return {"id": i, "kind": kind, "from_plugin": "hestia",
            "pointer_uri": ptr or f"hestia://escalation/e{i}", "queued_at": stamp(age)}


def run(member="kimi-code", session="s-main", rc=0, event=None):
    env = {**os.environ, "HESTIA_MESH_STATE": state, "STUB_PEEK": peek_file, "STUB_RC": str(rc)}
    env.pop("HESTIA_MESH_PLUGIN", None)
    if member is not None:
        env["HESTIA_MESH_PLUGIN"] = member
    if event is None:
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "go"}
        if session is not None:
            event["session_id"] = session
    return subprocess.run(["sh", script], input=json.dumps(event), capture_output=True,
                          text=True, timeout=30, env=env)


OLD = 3 * 3600      # well outside the look-back

print("A. a new session's first prompt")
inbox(n(5, "disposition", age=OLD), n(7, "reply", age=OLD))
p = run(session="s-a")
check(p.returncode == 0 and p.stdout == "", "A1. history outside the look-back is not retro-surfaced",
      repr(p.stdout))
inbox(n(5, "disposition", age=OLD), n(8, "disposition", age=120))
p = run(session="s-a2")
check("hestia://escalation/e8" in p.stdout and "e5" not in p.stdout,
      "A2. a ruling queued inside the look-back IS shown on a session's first prompt", repr(p.stdout))

print("B. a newer disposition prints once per session")
inbox(n(5, "disposition", age=OLD), n(7, "reply", age=OLD), n(9, "disposition", age=10))
p = run(session="s-a")
check(p.returncode == 0, "B1. exits 0", str(p.returncode))
check("hestia://escalation/e9" in p.stdout, "B2. names the new disposition's pointer", repr(p.stdout))
check("e5" not in p.stdout, "B3. does not re-surface the baseline one", repr(p.stdout))
check("1 new disposition" in p.stdout, "B4. counts only the new one", repr(p.stdout))
p = run(session="s-a")
check(p.returncode == 0 and p.stdout == "", "B5. the next prompt in that session is silent", repr(p.stdout))

print("C. a newer non-disposition notice is ignored")
inbox(n(9, "disposition", age=10), n(12, "review_request", age=5))
p = run(session="s-a")
check(p.returncode == 0 and p.stdout == "", "C1. a review_request does not print", repr(p.stdout))

print("D. GPT's #1148 repro: two sessions, one member, the sibling prompts first")
inbox(n(40, "reply", age=OLD))
for s in ("asker", "sibling"):
    p = run(member="claude-code", session=s)        # both sessions exist before the ruling
check(p.stdout == "", "D0. both sessions start with nothing to show", repr(p.stdout))
inbox(n(40, "reply", age=OLD), n(41, "disposition", "hestia://escalation/asker-ruling", age=5))
sib = run(member="claude-code", session="sibling")
ask = run(member="claude-code", session="asker")
check("asker-ruling" in sib.stdout, "D1. the sibling is shown it (the id is shared)", repr(sib.stdout))
check("asker-ruling" in ask.stdout,
      "D2. and the ASKER is still shown it after the sibling looked", repr(ask.stdout))
ask2 = run(member="claude-code", session="asker")
check(ask2.stdout == "", "D3. once, for the asker too", repr(ask2.stdout))

print("E. no usable session id records nothing")
inbox(n(50, "disposition", "hestia://escalation/nosid", age=20))
for label, ev in (("no session_id", {"hook_event_name": "UserPromptSubmit"}),
                  ("blank session_id", {"hook_event_name": "UserPromptSubmit", "session_id": "  "}),
                  ("unparseable event", "not json")):
    env_ev = ev if isinstance(ev, dict) else None
    if env_ev is None:
        p = subprocess.run(["sh", script], input=ev, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "HESTIA_MESH_STATE": state, "STUB_PEEK": peek_file,
                                "HESTIA_MESH_PLUGIN": "codex"})
    else:
        p = run(member="codex", event=env_ev)
    check("nosid" in p.stdout and "nothing was recorded" in p.stdout,
          f"E1. {label}: shown, and says it was not recorded", repr(p.stdout))
p = run(member="codex", session=None)
check("nosid" in p.stdout, "E2. and it repeats (nothing marked it seen)", repr(p.stdout))
p = run(member="codex", session="later")
check("nosid" in p.stdout, "E3. a session with an id is not suppressed by the id-less runs",
      repr(p.stdout))
check(not os.path.exists(os.path.join(state, "disposition-watermark")),
      "E4. no shared per-member watermark exists anywhere")

print("F. every failure is silent and exits 0")
inbox(n(60, "disposition", age=5))
p = run(session="s-f", rc=1)
check(p.returncode == 0 and p.stdout == "", "F1. a failing peek", repr(p.stdout))
inbox(raw="not json {")
p = run(session="s-f")
check(p.returncode == 0 and p.stdout == "", "F2. unparseable peek output", repr(p.stdout))
inbox(n(61, "disposition", age=5))
p = run(member=None, session="s-f")
check(p.returncode == 0 and p.stdout == "", "F3. unset HESTIA_MESH_PLUGIN", repr(p.stdout))

print("G. the advice is safe on a shared plugin id")
out = ask.stdout
check("co-seat" in out, "G1. says the ruling may belong to a co-seat", repr(out))
check("gate poll <" not in out and "poll: hestia gate poll" not in out,
      "G2. never tells the reader to check with gate poll", repr(out))
check("#732" in out, "G3. and names why not", repr(out))

print("H. housekeeping")
seen = os.path.join(state, "disposition-seen", "claude-code")
names = os.listdir(seen) if os.path.isdir(seen) else []
check(len(names) == 2 and all(len(x) == 24 and x.isalnum() for x in names),
      "H1. one file per session, named by hash (an id never becomes a path)", repr(names))
p = run(member="claude-code", session="../../../escape")
after = os.listdir(seen) if os.path.isdir(seen) else []
check(not os.path.exists(os.path.join(state, "escape")) and len(after) == 3,
      "H2. a hostile session id stays inside the member's dir", repr(after))
# Age the SIBLING's file and prompt as the asker: the pruned file must not be the one this
# run rewrites.
stale = os.path.join(seen, hashlib.sha256(b"sibling").hexdigest()[:24])
if os.path.exists(stale):
    os.utime(stale, (time.time() - 8 * 86400,) * 2)
run(member="claude-code", session="asker")
check(bool(after) and not os.path.exists(stale), "H3. a per-session file past the 7-day TTL is pruned")

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nall prompt-disposition-watch checks pass")
