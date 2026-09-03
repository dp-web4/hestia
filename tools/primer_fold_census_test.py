#!/usr/bin/env python3
"""Guards for tools/primer_fold_census.py.

What is worth pinning here is the CLASSIFICATION, not the counts: the counts are
a property of one box on one day, and a test that asserts them pins the box. The
two judgements the tool makes that a reader will act on are

  (1) three delivery states, not two — a fold that is present but EMPTY renders
      exactly like a fold that was deleted, because the fire templates gate the
      whole debt block on `[ -n "$DEBT" ]`; and
  (2) the producer's vintage is readable off the key set alone, which is the
      question `open-petitions.py` currently sends the reader to a tool for.

Each check runs against a payload that would pass under the opposite reading.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import primer_fold_census as m  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        print("  <- " + str(detail))
        FAILED.append(name)


DRAIN = {"evicted": 0, "notices": [], "peeked": False, "total": 1}
ROW = {"id": 1, "kind": "reply", "from_plugin": "kimi-code", "to_plugin": "claude-code"}

# --- (1) three states ---------------------------------------------------------
absent = dict(DRAIN)
empty = dict(DRAIN, for_plugin="claude-code", unanswered={"i_owe": [], "owed_to_me": []})
ships = dict(DRAIN, for_plugin="claude-code", unanswered={"i_owe": [ROW], "owed_to_me": []})

check("A the composition fallback is recognised by the absent fold",
      m.classify(absent) == "A_absent", m.classify(absent))
check("B a present-but-empty fold is NOT counted as delivered",
      m.classify(empty) == "B_empty", m.classify(empty))
check("C a fold with a single row in either direction ships the debt block",
      m.classify(ships) == "C_ships", m.classify(ships))
check("B/C are distinguished — a two-state reading would collapse them",
      m.classify(empty) != m.classify(ships))
check("a non-dict fold degrades to absent rather than raising",
      m.classify(dict(DRAIN, unanswered=None)) == "A_absent")

# `owed_to_me` alone is enough: the block renders both directions.
check("owed_to_me alone still ships",
      m.classify(dict(DRAIN, unanswered={"i_owe": [], "owed_to_me": [ROW]})) == "C_ships")

# --- (2) producer vintage from the key set ------------------------------------
check("fallback: exactly the raw drain keys",
      m.producer(absent).startswith("fallback"), m.producer(absent))
check("pre-for_plugin: fold but no owner stamp",
      m.producer(dict(DRAIN, unanswered={})).startswith("pre-for_plugin"),
      m.producer(dict(DRAIN, unanswered={})))
check("pre-open_petitions: owner stamp, no petitions fold",
      m.producer(empty).startswith("pre-open_petitions"), m.producer(empty))
check("current: petitions fold present",
      m.producer(dict(empty, open_petitions={"asked": True, "mine": []})).startswith("current"))
# The discriminating pair: both of these lack `open_petitions`, and the primer
# text calls them different causes wanting opposite responses.
check("the two causes of an absent open_petitions key are told apart",
      m.producer(absent) != m.producer(empty), (m.producer(absent), m.producer(empty)))

# --- census runs end to end over a synthetic directory ------------------------
with tempfile.TemporaryDirectory() as td:
    for i, d in enumerate((absent, empty, ships, ships)):
        json.dump(d, open(os.path.join(td, "notice-%d.json" % i), "w"))
    m.PRIMERS = td
    m.census("01-01")  # must not raise on a directory it has never seen

# --- (3) a re-delivered primer is dated by COMPOSITION, not by the sweep ------
# The retry store re-fires primers composed days earlier; each lands in the
# primary store with today's mtime. Dating the series there attributes an old
# file's shape to the sweep day -- which is what inflated 08-31 from 23% to 48%
# in the published table. The arm below is red against that dating.
import contextlib  # noqa: E402
import datetime  # noqa: E402
import io  # noqa: E402
import time  # noqa: E402

import calendar  # noqa: E402

SWEEP = calendar.timegm(time.strptime("2026-08-31T21:59Z", "%Y-%m-%dT%H:%MZ"))
BORN = calendar.timegm(time.strptime("2026-08-16T02:17Z", "%Y-%m-%dT%H:%MZ"))
# Label them the way the tool does, so the arms pin the BEHAVIOUR and not this
# box's timezone.
D_SWEEP = datetime.datetime.utcfromtimestamp(SWEEP).strftime("%m-%d")
D_BORN = datetime.datetime.utcfromtimestamp(BORN).strftime("%m-%d")


def _rows(out):
    """day -> (n, C_ships) parsed from the census table."""
    got = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 7 and len(f[0]) == 5 and f[0][2] == "-" and f[0][:2].isdigit():
            got[f[0]] = (int(f[1]), int(f[5]))
    return got


def _census(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.census("01-01", **kw)
    return _rows(buf.getvalue())


with tempfile.TemporaryDirectory() as prim, tempfile.TemporaryDirectory() as retry:
    # one primer genuinely composed on the sweep day, one re-delivered that day
    for name, born in (("notice-native.json", SWEEP), ("notice-old.json", BORN)):
        path = os.path.join(prim, name)
        json.dump(ships, open(path, "w"))
        # BOTH sit in the primary store with the sweep day's mtime -- that is
        # exactly what the re-fire does, and why the primary mtime cannot be trusted.
        os.utime(path, (SWEEP, SWEEP))
    src = os.path.join(retry, "notice-old.json")
    json.dump(ships, open(src, "w"))
    os.utime(src, (BORN, BORN))
    open(os.path.join(retry, "notice-old.json.attempts"), "w").write("3\n")

    m.PRIMERS, m.RETRY = prim, retry
    seen = m.refires()
    check("the .attempts sibling identifies the re-delivered primer",
          set(seen) == {"notice-old.json"}, sorted(seen))
    check("its composition time comes from the retry copy, not the primary copy",
          abs(seen["notice-old.json"] - BORN) < 2, seen)

    dropped = _census()
    check("re-fires excluded: the sweep day counts only what was composed then",
          dropped.get(D_SWEEP, (0, 0))[0] == 1, dropped)
    check("re-fires excluded: the old primer is not credited to any day",
          D_BORN not in dropped, dropped)

    redated = _census(exclude_refires=False)
    check("re-fires re-dated: the sweep day still counts only its own primer",
          redated.get(D_SWEEP, (0, 0))[0] == 1, redated)
    check("re-fires re-dated: the old primer lands on its COMPOSITION day",
          redated.get(D_BORN, (0, 0))[0] == 1, redated)

    # SABOTAGE ARM: restore the published dating (primary-store mtime, no
    # re-fire awareness) and confirm both arms above go red. A guard that is
    # green under the defect it names is not a guard.
    _real = m.refires
    m.refires = lambda: {}
    sabotaged = _census(exclude_refires=False)
    m.refires = _real
    check("SABOTAGE: dating by primary mtime inflates the sweep day to 2",
          sabotaged.get(D_SWEEP, (0, 0))[0] == 2, sabotaged)
    check("SABOTAGE: and erases the composition day entirely",
          D_BORN not in sabotaged, sabotaged)

# --- the cap is measured, and it is the per-string one ------------------------
n = m.cap()
page = os.sysconf("SC_PAGESIZE")
check("measured per-string execve cap is 32 pages",
      n == 32 * page, (n, 32 * page))

print()
print("FAILED: %d" % len(FAILED) if FAILED else "all checks passed")
sys.exit(1 if FAILED else 0)
