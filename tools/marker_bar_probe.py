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

THAT SECOND ROW IS NOW DECIDED, and the answer changes the headline. The one-sided
version was not a limit of the evidence -- it was a limit of where the probe was
willing to look. `bar_for`'s three literals live in the Rust source in this same
repo, so they can be READ at runtime instead of transcribed. Reading them keeps the
constraint that motivated the one-sidedness (no such literal appears in this file)
while removing the blind spot it caused.

What it found: of the governance names the matcher protects, the bar tests only a
subset, and one of the names it does NOT test is the shared policy core -- the file
the matcher's own comment says is to BECOME the single gate for all five harnesses.
So a `maybe strong` row was in fact a weak one, and the count of acts that cannot
reach the strong bar was under-reported by one. A one-sided instrument does not
report a bound; it gets read as a point ([[one-sided-refutability]]).

One name reaches the strong bar by SUBSTRING ACCIDENT rather than by design (its
basename ends with another governed basename), so renaming that file would silently
demote it. The drift table below states each name's class as derived, so a future
addition to either list shows up as an unclassified row instead of a silence.

NO LITERAL MARKER PATH OR GOVERNANCE FILENAME APPEARS IN THIS SOURCE. Every one is
derived from the imported module's own constants, or read from the bar's own source.
That is not a style choice -- a literal would make this file refused by the gate it
measures.

Run: python3 tools/marker_bar_probe.py
"""
import os
import re
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


# ---------------------------------------------------------------------------
# THE BAR'S OWN LIST, READ FROM THE BAR'S OWN SOURCE
# ---------------------------------------------------------------------------
# Transcribing these three would duplicate a pinned list AND make this file
# unwritable, which is why the first cut of this probe declined to test them at all.
# Reading them costs neither: the strings never appear here, only in the Rust file
# that already owns them. If that file moves or the function is rewritten, we say so
# and fall back to the one-sided verdicts rather than guessing.
BAR_SRC = os.path.join(REPO, "core", "src", "server", "gate_escalation.rs")


def _bar_names(path):
    """The filenames `bar_for` routes to the two-factor bar, or None if unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return None
    start = src.find("pub fn bar_for")
    if start < 0:
        return None
    end = src.find("\n}", start)
    if end < 0:
        return None
    body = src[start:end]
    names = re.findall(r'contains\("([^"]+)"\)', body)
    return names or None


STRONG = _bar_names(BAR_SRC)

dirs_in_tuple = sum(1 for m in G._SELF_MARKERS if not any(f in m for f in GOV))
print(f"imported from : {G.__file__}")
print(f"_SELF_DIR     : {G._SELF_DIR}")
print(f"marker tuple  : {len(G._SELF_MARKERS)} elements, {dirs_in_tuple} of them "
      f"name no file at all")
if STRONG is None:
    print(f"bar source    : UNREADABLE at {BAR_SRC} -- verdicts stay one-sided")
else:
    print(f"bar source    : {len(STRONG)} of {len(GOV)} governed names route to the "
          f"two-factor bar")
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
    hit = G._touches_self(tool, inp)
    # 5.2 (81286c0, 2026-08-07) made `_touches_self` return the (marker, resource, key)
    # TRIPLE; this probe kept reading a bare string and crashed at the print loop for 26
    # days -- neither RED nor GREEN, just absent (a crashed acceptance test reads as no
    # news). The bar still keys on hit[0] alone; hit[1] is the resource the record drops.
    marker = hit[0] if isinstance(hit, tuple) else hit
    resource = hit[1] if isinstance(hit, tuple) and len(hit) > 1 else None
    named = [f for f in GOV if marker and f in marker]
    if marker is None:
        verdict, weak, why = "NOT MATCHED AT ALL", False, ""
    elif not named:
        # No governed filename in the marker, so a bar testing for filenames cannot
        # match whatever subset it tests. True regardless of STRONG.
        verdict, weak, why = "single approver (PROVEN)", True, "NAMES A DIRECTORY, NOT A FILE"
    elif STRONG is None:
        verdict, weak, why = "maybe strong", False, ""
    elif any(s in marker for s in STRONG):
        verdict, weak, why = "sovereign+peer (PROVEN)", False, ""
    else:
        verdict, weak, why = ("single approver (PROVEN)", True,
                              "GOVERNED NAME THE BAR DOES NOT TEST")
    rows.append((name, marker, verdict, weak, why, resource))

w = max(len(r[0]) for r in rows)
weak_count = 0
for name, marker, verdict, weak, why, resource in rows:
    shown = marker if marker else "-"
    if resource and resource != marker:
        shown += f"   (resource: {resource})"
    if why:
        shown += f"   <-- {why}"
    if weak:
        weak_count += 1
    print(f"{name:<{w}}  ->  {verdict}")
    print(f"{'':<{w}}      marker: {shown}")

print()
print(f"{weak_count} of {len(rows)} acts on the governance surface cannot reach the "
      f"two-factor bar.")

if STRONG is not None:
    # Every governed name, classified. An unclassified row here is the drift this
    # table exists to surface: the matcher's list and the bar's list are maintained
    # in two languages with nothing binding them.
    print()
    print("Governed name -> bar, derived from both sources:")
    unreachable = []
    for f in GOV:
        hit = [s for s in STRONG if s in f]
        if not hit:
            unreachable.append(f)
            print(f"  {f:<34} single approver  <-- the bar never names it")
        elif hit[0] != f:
            print(f"  {f:<34} sovereign+peer   <-- by SUBSTRING ACCIDENT on "
                  f"{hit[0]!r}; a rename silently demotes it")
        else:
            print(f"  {f:<34} sovereign+peer")
    if unreachable:
        print()
        print(f"{len(unreachable)} of {len(GOV)} governed names can never reach the "
              f"two-factor bar, however")
        print("precisely the marker resolves. Making the marker resolution-aware "
              "does not reach them.")
        print()
        print("This table reports REACHABILITY, not intent. The bar's doc comment "
              "classes one of")
        print("these deliberately (a law renderer is one approver's call) and says "
              "nothing about")
        print("the others -- all of which were added to the matcher after that "
              "comment was written.")
        print("The bar carries no per-name class, so no instrument can tell "
              "deliberate from stale.")

sys.exit(1 if weak_count else 0)
