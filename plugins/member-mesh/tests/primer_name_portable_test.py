#!/usr/bin/env python3
"""#1606: the watcher's primer file must get a fresh `notice-*.json` name on every wake, on
BSD (macOS) as well as GNU.

`mktemp "$PRIMERS/notice-XXXXXX.json"` is GNU-only: BSD mktemp replaces only TRAILING Xs, so it
creates the literal `notice-XXXXXX.json` once and fails "File exists" on every later wake. CI is
Linux with GNU mktemp, so a behaviour test of the old line would pass there; this test therefore
does two things:

  1. runs the EXACT `PRIMER=$(...)` line from hestia-watch-member.sh three times in one directory
     and checks three distinct, existing, empty `notice-<random>.json` files result;
  2. lints every plugin shell script for a mktemp template with anything after its X run, which is
     the shape that only GNU accepts.
"""
import glob
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = open(os.path.join(HERE, "..", "hestia-watch-member.sh")).read()

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    fails += (not ok)


lines = [l.strip() for l in SRC.splitlines() if l.strip().startswith("PRIMER=$(")]
check("exactly one PRIMER= assignment", len(lines) == 1, lines)

if len(lines) == 1:
    with tempfile.TemporaryDirectory() as d:
        script = f'PRIMERS="{d}"\n' + lines[0] + '\necho "$PRIMER"\n'
        names = []
        for _ in range(3):
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            names.append((r.returncode, r.stdout.strip()))
        check("each wake succeeds", all(rc == 0 for rc, _ in names), names)
        paths = [p for _, p in names]
        check("three distinct names", len(set(paths)) == 3, paths)
        check("every name is notice-<random>.json in $PRIMERS",
              all(os.path.dirname(p) == d and re.fullmatch(r"notice-[^/]+\.json", os.path.basename(p))
                  and "XXXXXX" not in p for p in paths), paths)
        check("every file exists and is empty",
              all(os.path.isfile(p) and os.path.getsize(p) == 0 for p in paths), paths)
        check("the sweeps' glob sees all three",
              len(glob.glob(os.path.join(d, "notice-*.json"))) == 3)

    with tempfile.TemporaryDirectory() as d:
        missing = os.path.join(d, "absent")
        r = subprocess.run(["bash", "-c", f'PRIMERS="{missing}"\n' + lines[0] + '\necho "[$PRIMER]"\n'],
                           capture_output=True, text=True)
        check("a missing directory leaves PRIMER empty, as mktemp failing did",
              r.stdout.strip() == "[]", r.stdout)

# A template with characters after its X run (`foo-XXXXXX.json`) works only with GNU mktemp.
SUFFIXED = re.compile(r"\bmktemp\b[^\n|;)]*?X{3,}[^X\s\"')]")
offenders = []
for path in glob.glob(os.path.join(PLUGINS, "**", "*.sh"), recursive=True):
    for n, line in enumerate(open(path, errors="replace"), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        if SUFFIXED.search(code):
            offenders.append(f"{os.path.relpath(path, PLUGINS)}:{n}")
check("no plugin script uses a GNU-only suffixed mktemp template", not offenders, offenders)

if fails:
    raise SystemExit(f"{fails} check(s) failed")
print("all checks passed")
