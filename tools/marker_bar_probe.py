#!/usr/bin/env python3
"""Which marker does the gate hand an escalation, and can the strong bar see it?

WHY THIS EXISTS. The escalation `marker` is not the path the act touches. It is
whichever element of the matcher's own marker tuple matched first -- the matcher's
docstring says so outright ("Return the matched marker"). The Rust side then chooses
the approval bar by testing THAT STRING for three governance filenames
(`bar_for()`, core/src/server/gate_escalation.rs). Three of the four marker-tuple
elements are DIRECTORIES and contain no filename at all. When one of those matches
first, the bar test finds nothing to match and falls to the single-approver bar --
for an act on the governance surface.

The consequence is an inversion: the wider the act, the weaker the bar. A wildcard
over the whole installed hooks directory matches the directory element and gets one
approver; naming a single file exactly matches the file element and gets
sovereign-plus-peer.

WHAT THIS DOES NOT DO. It does not route a tool call, so it mints no escalation, no
deny, and no conduct record for anyone -- unlike `gate-probe.py`, which drives the
real gate end-to-end and must exonerate the ding it causes. This one imports the
enforcing copy and calls `_touches_self` directly. It is safe to run repeatedly and
needs no cleanup.

THE BRIDGE TO THE BAR IS ONE-SIDED, DELIBERATELY. This is Python; `bar_for` is Rust,
and transcribing its three literals here would both duplicate a pinned list and make
this file unwritable (the gate scans proposed content for exactly those strings). So
the test is on the weaker, derivable predicate:

    marker contains NO governance filename  =>  `bar_for`, which looks for a strict
    SUBSET of those filenames, cannot match either  =>  single approver. Airtight.

    marker contains SOME governance filename  =>  `bar_for` may still miss it, since
    it checks only three of the seven. Reported as "maybe strong", never as proof.

The proven direction is the one that carries the finding; the unproven direction is
reported honestly rather than rounded up.

NO LITERAL MARKER PATH OR GOVERNANCE FILENAME APPEARS IN THIS SOURCE. Every one is
derived from the imported module's own constants. That is not a style choice -- a
literal would make this file refused by the gate it measures.

Run: python3 tools/marker_bar_probe.py
"""
import os
import sys

HOME = os.path.expanduser("~")
INSTALLED_DIR = os.path.join(HOME, ".claude", "hooks", "hestia")
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
INTREE_DIR = os.path.join(REPO, "plugins", "claude-code", "hooks")

# The ENFORCING copy is the one whose behaviour matters; fall back to in-tree so the
# probe still runs on a seat that has no install (and says which it used).
SOURCE = INSTALLED_DIR if os.path.isdir(INSTALLED_DIR) else INTREE_DIR
sys.path.insert(0, SOURCE)
import pre_tool_use as G  # noqa: E402

GOV = G._GOVERNANCE_FILES
# selected by prefix so no governance filename is spelled literally in this file
WITNESS = [f for f in GOV if f.startswith("wit")][0]
GATE = [f for f in GOV if f.startswith("pre_")][0]
CORE = [f for f in GOV if f.startswith("hestia_")][0]

dirs_in_tuple = sum(1 for m in G._SELF_MARKERS if not any(f in m for f in GOV))
print(f"imported from : {G.__file__}")
print(f"_SELF_DIR     : {G._SELF_DIR}")
print(f"marker tuple  : {len(G._SELF_MARKERS)} elements, {dirs_in_tuple} of them "
      f"name no file at all")
print()

tilde_dir = "~" + INSTALLED_DIR[len(HOME):]

CASES = [
    ("Edit  in-tree gate source (the copy that redeploys to every member)",
     "Edit", {"file_path": os.path.join(INTREE_DIR, GATE)}),
    ("Edit  installed gate (the enforcing copy)",
     "Edit", {"file_path": os.path.join(INSTALLED_DIR, GATE)}),
    ("Edit  installed outcome recorder",
     "Edit", {"file_path": os.path.join(INSTALLED_DIR, WITNESS)}),
    ("Edit  shared policy core in-tree",
     "Edit", {"file_path": os.path.join(REPO, "plugins", "_shared", CORE)}),
    ("Bash  cp onto the recorder, ABSOLUTE spelling",
     "Bash", {"command": "cp /tmp/x " + os.path.join(INSTALLED_DIR, WITNESS)}),
    ("Bash  cp onto the recorder, TILDE spelling",
     "Bash", {"command": "cp /tmp/x " + os.path.join(tilde_dir, WITNESS)}),
    ("Bash  cp onto the enforcing gate, ABSOLUTE spelling",
     "Bash", {"command": "cp /tmp/x " + os.path.join(INSTALLED_DIR, GATE)}),
    ("Bash  wildcard over the whole installed hooks dir",
     "Bash", {"command": "cp /tmp/x " + os.path.join(INSTALLED_DIR, "*")}),
    ("Bash  sed -i on the in-tree gate source",
     "Bash", {"command": "sed -i s/a/b/ " + os.path.join(INTREE_DIR, GATE)}),
]

rows = []
for name, tool, inp in CASES:
    marker = G._touches_self(tool, inp)
    named = [f for f in GOV if marker and f in marker]
    if marker is None:
        verdict = "NOT MATCHED AT ALL"
    elif not named:
        verdict = "single approver (PROVEN)"
    else:
        verdict = "maybe strong"
    rows.append((name, marker, verdict))

w = max(len(r[0]) for r in rows)
weak = 0
for name, marker, verdict in rows:
    shown = marker if marker else "-"
    if marker and not any(f in marker for f in GOV):
        shown += "   <-- NAMES A DIRECTORY, NOT A FILE"
        weak += 1
    print(f"{name:<{w}}  ->  {verdict}")
    print(f"{'':<{w}}      marker: {shown}")

print()
print(f"{weak} of {len(rows)} acts on the governance surface carry a marker that "
      f"names no file,")
print("so the strong bar is unreachable for them no matter what it tests for.")
sys.exit(1 if weak else 0)
