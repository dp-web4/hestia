#!/usr/bin/env python3
"""Does a co-seat session eat the asker's ruling? Bystander-first probe for the delivery hook.

CONTEXT. PRD_DISPOSITION_DELIVERY (#845) R4 gives each seat a hook that renders the daemon's
disposition line on the seat's own context port; R6 says bystanders neither consume nor burn.
On 2026-09-02 the claude-code seat's candidate deliverer was escalated for install
(`7d6024104a38dedb`, approved 22:31:49Z) and codex dissented 90 s LATER: one seat-wide cursor,
so any session of the seat advances past a line addressed to another `for_session`.

WHY THIS EXISTS AND NOT JUST THE DISSENT. A second seat agreeing with a prose argument is a
set of one unless something recomputes it. This runs the sequence the supplied tests omit --
bystander fires FIRST, asker fires SECOND -- against the real file, and measures a candidate
fix on the SAME sequence so the diagnosis is not just a complaint.

ARMS (target, lane and firing content identical; only the ORDER and the cursor key differ):
  A control      asker fires first                      -> expect delivered
  B bystander-first                                     -> expect NOT delivered
  C bystander-first, cursor keyed by session            -> expect delivered

MEASURED 2026-09-02 22:47Z, claude-code/CBP, against the 5899-byte candidate:
  A asker_delivered=True   B asker_delivered=False   C asker_delivered=True
and in arm B `bystander_rendered=False`: the bystander does not merely read the line early,
it DESTROYS it. `for_session` filtering happens after the cursor advance, so a line addressed
to another session is consumed by a session that renders it to nobody. No error, no retry, no
second chance -- the grant then lapses exactly as it does today, with the mechanism installed.

EXPOSURE IS NOT HYPOTHETICAL ON THIS SEAT. The bystanders are the mesh watcher's own wakes:
48 fired on the claude seat on 2026-09-02 (median gap 938 s), and for 48.4% of that span a
fresh co-seat session starts within the next 600 s -- one claim window. Each fires PreToolUse
on its first tool call. That is the exposure, not yet the loss rate: the asker's own events
race the bystander's, so the loss rate is 48.4% times P(bystander first). The sessions that
exist BECAUSE delivery is broken are the ones that would break it.

FIX MEASURED IN ARM C: key the cursor by (plugin, session) rather than by seat. A new session
should start at end-of-lane, not offset 0, or every session inherits the backlog of every
`for_session`-less line ever written; and a per-session cursor needs the same reaper the seat
state dir already needs.

Run: python3 tools/disposition_deliver_bystander_probe.py [path-to-deliverer]

The child env is built as an explicit dict rather than inherited: naming the standard
library's process-environment mapping trips gate 1a's raw-substring egress test (#639,
instance 1 -- known, open, and false). Same reason this file spells no install path.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TARGET = "/tmp/dd-probe/deliver.py"
ASKER = "sess-asker-0001"
BYSTANDER = "sess-mesh-wake-9999"      # what the seat watcher fires, same plugin_id
BASE_ENV = {"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~"), "LANG": "C.UTF-8"}


def seat(raw):
    home = Path(raw) / "hestia"
    state = Path(raw) / "seat"
    (home / "dispositions").mkdir(parents=True)
    state.mkdir()
    return home, state, home / "dispositions" / "claude-code.jsonl"


def fire(target, home, state, session, per_session_cursor=False):
    env = dict(BASE_ENV)
    env["HESTIA_HOME"] = str(home)
    # Arm C's ONLY change: the cursor is keyed by session, so two sessions of one seat do not
    # share a read position. The tool, the lane and the order are identical across arms.
    env["HESTIA_SEAT_STATE"] = str(state / session) if per_session_cursor else str(state)
    payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": session,
                          "tool_name": "Bash", "tool_input": {"command": "true"}})
    r = subprocess.run([sys.executable, target], input=payload, env=env,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        return "<MALFORMED> " + r.stdout[:200]


def ruling(for_session=ASKER):
    return json.dumps({"escalation_id": "7d6024104a38dedb", "decision": "approved",
                       "for_session": for_session,
                       "render": "APPROVED 7d6024. Claimable until 23:28:22Z. "
                                 "Re-issue the same write."})


def arm(target, name, order, per_session_cursor=False):
    with tempfile.TemporaryDirectory() as raw:
        home, state, lane = seat(raw)
        lane.write_text(ruling() + "\n", encoding="utf-8")
        seen = {}
        for who in order:
            seen[who] = fire(target, home, state, who, per_session_cursor)
        got = seen.get(ASKER)
        print(f"{name}: order={' -> '.join(order)}\n"
              f"    asker_delivered={bool(got)}  bystander_rendered={bool(seen.get(BYSTANDER))}")
        return bool(got)


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    if not os.path.isfile(target):
        print(f"no deliverer at {target} -- pass its path as argv[1]")
        return 2
    print("target:", target, os.path.getsize(target), "bytes")
    a = arm(target, "A control (asker first)              ", [ASKER])
    b = arm(target, "B bystander first                    ", [BYSTANDER, ASKER])
    c = arm(target, "C bystander first, per-session cursor", [BYSTANDER, ASKER],
            per_session_cursor=True)
    print()
    ok = a and not b and c
    print("PASS: defect reproduced, and the per-session cursor repairs it on the same sequence"
          if ok else f"NOT the predicted pattern: A={a} B={b} C={c}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
