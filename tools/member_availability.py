#!/usr/bin/env python3
"""Which members of this box can actually act right now, and what is owed to and by them.

dp, 2026-09-03: "maintain status of cbp members." This is that status, computed rather than
remembered, because every part of it rots within hours: usage resets, watchers get stopped,
and a member that answered this morning may be out of credits by lunch.

WHAT MAKES THIS MORE THAN `systemctl is-active`. A running watcher is not an available member.
The watcher drains the member's mailbox CONSUME-ONCE and then launches its CLI; if that CLI
dies on quota, the mail has already left the queue and lands in a primer file that no session
will open. So a watcher running for an out-of-usage member is worse than a stopped one: it
converts queued mail into a private pile while the sender is told delivery failed. Measured
2026-09-03: kimi fired 110 times, 88 died on quota; codex fired 74 while out of credits.

The verdicts, and each is a different remedy:

  AVAILABLE        watcher up, recent fires ran
  OUT              recent fires died on quota or credits. STOP THE WATCHER: mail should
                   queue as dormant, which is the honest state, rather than be drained into
                   an unreadable primer
  PARKED           watcher stopped and the member is out. Correct: this is what OUT wants
  IDLE             watcher stopped, member not known to be out. Someone stopped it; say so
  UNKNOWN          no fire log to read. Absence of evidence, reported as such

Read-only: log stats, primer counts, and one `unanswered` call per member. No writes, no
watcher control. Stopping a watcher is an operator act and this only recommends it.

    python3 tools/member_availability.py [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

# (member id, seat home suffix, fire-log prefix). Members are named, not discovered, because
# a missing member must read as UNKNOWN rather than vanish from the table.
MEMBERS = (("claude-code", ".claude", "claude"),
           ("kimi-code", ".kimi-code", "kimi"),
           ("codex", ".codex", "codex"))
OUT_OF_USAGE = re.compile(r"quota|usage limit|upgrade your plan|out of credits|rate.?limit", re.I)
LOGS = os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh", "logs")
MESH = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "member-mesh", "hestia-mesh.py")


def watcher_state(prefix: str) -> str:
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", f"hestia-watch-{prefix}.service"],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "unknown").strip()
    except Exception:
        return "unknown"


def fires(prefix: str, hours: int = 24):
    """(fires, deaths, newest_tail) over the window, from the fire logs."""
    cutoff = time.time() - hours * 3600
    n = deaths = 0
    newest, newest_mtime = "", 0.0
    for f in glob.glob(os.path.join(LOGS, f"{prefix}-*.log")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        n += 1
        try:
            tail = open(f, encoding="utf-8", errors="replace").read()[-2000:]
        except OSError:
            continue
        if OUT_OF_USAGE.search(tail):
            deaths += 1
        if st.st_mtime > newest_mtime:
            newest, newest_mtime = tail.strip().replace("\n", " ")[-160:], st.st_mtime
    return n, deaths, newest


def primers(home_suffix: str):
    """(primer files, notices inside them). A retained primer holds mail already drained."""
    d = os.path.join(os.path.expanduser("~"), home_suffix, "hestia-mesh-primers")
    files = glob.glob(os.path.join(d, "*.json"))
    notices = 0
    for f in files:
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        notices += len(p.get("notices") or [])
    return len(files), notices


def owed(member: str, timeout: int = 90):
    if not os.path.isfile(MESH):
        return None, None
    env = dict(os.environ, HESTIA_MESH_PLUGIN=member,
               HESTIA_ROLE=os.environ.get("HESTIA_ROLE", "role:constellation:member"))
    try:
        r = subprocess.run([sys.executable, MESH, "unanswered"], capture_output=True,
                           text=True, timeout=timeout, env=env)
        d = json.loads(r.stdout[r.stdout.find("{"):])
        return len(d.get("i_owe") or []), len(d.get("owed_to_me") or [])
    except Exception:
        return None, None


def verdict(watcher: str, n: int, deaths: int) -> str:
    out = deaths > 0 and deaths >= max(1, n // 4)
    if watcher == "active":
        if n == 0:
            return "UNKNOWN"
        return "OUT" if out else "AVAILABLE"
    if n == 0:
        return "UNKNOWN"
    return "PARKED" if out else "IDLE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    rows = []
    for member, home, prefix in MEMBERS:
        w = watcher_state(prefix)
        n, deaths, tail = fires(prefix, args.hours)
        pf, pn = primers(home)
        i_owe, owed_to = owed(member)
        rows.append({"member": member, "watcher": w, "fires": n, "out_of_usage_deaths": deaths,
                     "verdict": verdict(w, n, deaths), "retained_primers": pf,
                     "notices_in_primers": pn, "i_owe": i_owe, "owed_to_me": owed_to,
                     "last_fire_tail": tail})
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    print(f"CBP MEMBER AVAILABILITY   window {args.hours}h   {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}")
    print(f"{'member':<12}{'verdict':<11}{'watcher':<10}{'fires':>6}{'out':>5}"
          f"{'primers':>9}{'notices':>9}{'i_owe':>7}{'owed_me':>9}")
    for r in rows:
        print(f"{r['member']:<12}{r['verdict']:<11}{r['watcher']:<10}{r['fires']:>6}"
              f"{r['out_of_usage_deaths']:>5}{r['retained_primers']:>9}{r['notices_in_primers']:>9}"
              f"{str(r['i_owe']):>7}{str(r['owed_to_me']):>9}")
    for r in rows:
        if r["verdict"] == "OUT":
            print(f"\n{r['member']}: OUT with its watcher still running. Every fire drains its mailbox\n"
                  f"  before the CLI dies, so queued mail becomes an unread primer and the sender is\n"
                  f"  told delivery failed. Remedy:  systemctl --user stop hestia-watch-"
                  f"{dict((m, p) for m, _, p in MEMBERS)[r['member']]}.service")
    print("\nA retained primer holds mail that was already drained consume-once. The count is not\n"
          "a loss figure on its own: the sender receives a non-delivery report, and a notice may\n"
          "have been answered by another route. `i_owe` is the obligation that survives either way.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
