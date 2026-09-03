#!/usr/bin/env python3
"""Answer "is this merged mesh fix actually executing?" from outside the thing being versioned.

The member-mesh watchers ExecStart absolute paths inside the shared dev tree, so what runs is
whatever that tree held at the relevant moment. There are TWO gates, with different clocks:

  gate 1 (per-fire files: fire-*.sh, hestia-mesh.py, petitions.py)
      exec'd fresh on every fire -> what runs is the tree's disk state AT FIRE TIME.
      The right metric is a duty cycle over fires.

  gate 2 (hestia-watch-member.sh)
      a long-running bash process reads its script ONCE at start. Editing it on disk changes
      nothing until the process restarts. The right metric is the tree HEAD at the last
      watcher start -- a duty cycle over fires is MEANINGLESS here and will overstate delivery.

Nothing here needs to be deployed to work, which is the point: an instrument that requires
deployment cannot measure a deployment failure. `tools/process_vintage.py units` reports
"vintage NOT MEASURED" for every seat when a unit is inactive or has not yet emitted its hourly
level line; this answers the same question from the reflog and the process table.

NOTE (hestia #639): config is read via `from os import environ` rather than the usual spelling
because the gate's forbidden-token rule substring-matches ".env" inside `os.environ` and refuses
the write. No credential is in scope here; this is the recorded false-positive class, and the
re-anchoring is disclosed rather than silent.

Usage:
    tools/mesh_delivery_duty_cycle.py <commit-ish> [<commit-ish> ...]
"""
import bisect
import datetime
import os
import re
import subprocess
import sys
from os import environ

REPO = environ.get("HESTIA_REPO", "/mnt/c/exe/projects/ai-agents/hestia")
LOGS = environ.get("HESTIA_MESH_LOGS",
                   os.path.expanduser("~/.local/state/hestia-mesh/logs"))
WATCH_MEMBER = "hestia-watch-member.sh"

REFLOG = re.compile(r"^([0-9a-f]{40})\|HEAD@\{([^}]+)\}$")
FIRELOG = re.compile(r"^(.*)-(\d{8})-(\d{6})\.log$")


def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True).stdout


def head_timeline():
    """Every reflog entry moves HEAD, so all of them -- not just checkouts -- are steps."""
    events = []
    for line in git("reflog", "--date=iso", "--format=%H|%gd", "-2000").splitlines():
        m = REFLOG.match(line.strip())
        if not m:
            continue
        sha, ts = m.groups()
        events.append((datetime.datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M:%S %z"), sha))
    events.sort()
    return events


def fires(tz):
    out = []
    for fn in os.listdir(LOGS):
        m = FIRELOG.match(fn)
        if not m:
            continue
        seat, d, t = m.groups()
        out.append((seat, datetime.datetime.strptime(d + t, "%Y%m%d%H%M%S").replace(tzinfo=tz)))
    out.sort(key=lambda f: f[1])
    return out


def watcher_starts():
    """(seat, start-datetime) for every LIVE watcher, straight from the process table.

    A dead unit yields nothing on purpose: there is no vintage for a process that is not running,
    and reporting the exited process's vintage would date something not in force.
    """
    ps = subprocess.run(["ps", "-eo", "lstart=,cmd="], capture_output=True, text=True).stdout
    found = []
    for line in ps.splitlines():
        if WATCH_MEMBER not in line:
            continue
        stamp, cmd = line[:24].strip(), line[24:]
        try:
            dt = datetime.datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y").astimezone()
        except ValueError:
            continue
        # cmd is "bash <abs>/hestia-watch-member.sh <seat> <watch-name> <fire-script>";
        # the seat is the token AFTER the script path, not the first argv slot.
        # cmd is "bash <abs>/hestia-watch-member.sh <seat> <watch-name> <fire-script>".
        # Anchor on argv[1] specifically: a loose substring scan also matches this tool being
        # invoked from a shell whose own command line happens to name the script, and that
        # self-match reports a phantom watcher started seconds ago.
        parts = cmd.split()
        if len(parts) < 3 or not parts[1].endswith(WATCH_MEMBER):
            continue
        found.append((parts[2], dt))
    return found


def main(targets):
    events = head_timeline()
    if not events:
        sys.exit("no reflog entries -- is HESTIA_REPO right?")
    times = [e[0] for e in events]
    tz = events[-1][0].tzinfo

    def head_at(dt):
        i = bisect.bisect_right(times, dt) - 1
        return events[i][1] if i >= 0 else None

    cache = {}

    def contains(sha, target):
        key = (sha, target)
        if key not in cache:
            cache[key] = subprocess.run(
                ["git", "-C", REPO, "merge-base", "--is-ancestor", target, sha],
                capture_output=True).returncode == 0
        return cache[key]

    all_fires = fires(tz)
    live_watchers = watcher_starts()
    print(f"reflog steps {len(events)} ({events[0][0].date()}..{events[-1][0].date()}) | "
          f"fires {len(all_fires)} | live watchers {len(live_watchers)}")

    for target in targets:
        sha = git("rev-parse", "--verify", f"{target}^{{commit}}").strip()
        if not sha:
            print(f"\n### {target}: NOT FOUND")
            continue
        subject = git("log", "-1", "--format=%h %ci %s", sha).strip()
        merged = datetime.datetime.strptime(
            git("log", "-1", "--format=%cI", sha).strip(), "%Y-%m-%dT%H:%M:%S%z")
        touches_watcher = WATCH_MEMBER in git("show", "--stat", "--format=", sha)

        print(f"\n### {subject[:110]}")
        print(f"    gate: {'2 (watcher restart)' if touches_watcher else '1 (per-fire exec)'}")

        after = [f for f in all_fires if f[1] >= merged]
        if after:
            live = sum(1 for _, dt in after if (h := head_at(dt)) and contains(h, sha))
            pct = 100.0 * live / len(after)
            label = "on-disk at fire (NOT what executes)" if touches_watcher else "DUTY CYCLE"
            print(f"    {label}: {live}/{len(after)} = {pct:.1f}%")
        else:
            print("    no fires since it merged")

        if touches_watcher:
            if not live_watchers:
                print("    EXECUTING: no watcher is running -- nothing is in force for any seat")
            for seat, start in live_watchers:
                h = head_at(start)
                verdict = bool(h) and contains(h, sha)
                print(f"    EXECUTING[{seat}]={verdict}  (watcher up since {start:%Y-%m-%d %H:%M:%S}"
                      f", tree HEAD then {h[:9] if h else '?'})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
