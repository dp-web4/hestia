#!/usr/bin/env python3
"""Every member-wake path must route through with-member-lock.sh.

WHY THIS TEST EXISTS (notice 540 thread, 2026-07-31). The mesh's mutual-fire
serialization bound — at most one session per member at a time — was stated in
KINDS.md for six days as an emergent property of bash not backgrounding a
command ("not law, not tested, removable by appending `&`"). It was already law
in the tree: `with-member-lock.sh` plus `tests/fire_concurrency_test.py`
(15/15, replicated from two seats at two commits). Two careful readers each
verified the doc said what they said it said; neither checked the doc against
the tree, because the doc carried a date and a date reads like a binding.

The repair that thread ratified is *inherit, don't re-derive* — and a sentence
in a forum post is the exact artifact class that failed. So the forward clause
lives here instead, as acceptance criteria that fail loudly:

  L1. Every fire template (`fire-*.sh`) must take the member lock. Auto-
      discovered by glob: a fourth template is covered the day it lands, and
      one that forgets the lock goes red in CI, not on the wire.
  L2. Any future wake path — a duty-queue dispatcher, a cron rouser, anything
      whose name says it wakes a member (`*fire*|*wake*|*rouse*|*duty*|*queue*`
      executable in this directory) — must also route through the lock. Today
      no such script exists, so L2 passes vacuously; that is the point. It is
      written now, while there is no queue to make it pass, because that is
      when it is cheapest (CBP, notice 542).

L2's name-matching is deliberately crude: it asserts a convention (wake paths
are named like wake paths) and pays for the crudeness with a clear error
message when it trips, rather than with a silent bypass when it doesn't.

Run: python3 plugins/member-mesh/tests/fire_lock_guard_test.py
"""

import os
import re
import sys

MESH_DIR = os.path.join(os.path.dirname(__file__), "..")
LOCK = "with-member-lock.sh"
WAKE_NAME = re.compile(r"(fire|wake|rouse|duty|queue)", re.IGNORECASE)

failures = []
checks = 0


def check(ok, label, detail=""):
    global checks
    checks += 1
    if ok:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label}  {detail}")
        failures.append(label)


def main():
    entries = sorted(os.listdir(MESH_DIR))
    scripts = [
        e for e in entries
        if e.endswith(".sh") and os.path.isfile(os.path.join(MESH_DIR, e))
    ]

    # L1: every fire template routes through the member lock.
    fires = [e for e in scripts if e.startswith("fire-")]
    check(len(fires) >= 3, "L1: fire templates discovered",
          f"found {fires!r} — glob broken or templates renamed?")
    for f in fires:
        body = open(os.path.join(MESH_DIR, f)).read()
        check(LOCK in body, f"L1: {f} routes through {LOCK}",
              "wake path bypasses the member lock")

    # L2: any script named like a wake path routes through the lock.
    # (hestia-watch-member.sh is the poller; it wakes members BY invoking a
    # fire template, which L1 covers — it must not spawn a member CLI itself.)
    for f in scripts:
        if f.startswith("fire-") or f == LOCK:
            continue
        body = open(os.path.join(MESH_DIR, f)).read()
        if WAKE_NAME.search(f):
            check(LOCK in body or "fire-" in body,
                  f"L2: {f} routes wake through {LOCK} (directly or via a "
                  f"fire template)",
                  "wake-named script neither takes the lock nor delegates "
                  "to a locked template")

    print(f"\n{checks - len(failures)}/{checks} PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
