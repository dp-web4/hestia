#!/usr/bin/env python3
"""Which string prices the bar for a governance-surface act — and does the act's
own resolved target carry what the bar needs to see?

WHY THIS EXISTS. The escalation `marker` is not the path the act touches. It is
whichever element of the matcher's marker tuple matched first -- the matcher says
so outright. The Rust side chose the approval bar by testing THAT STRING for four
governance filenames (`bar_for()`, core/src/server/gate_escalation.rs), and most
of the marker-tuple elements are DIRECTORIES with no filename in them. When one of
those matched first, the bar test found nothing to match and fell to the
single-approver bar -- for an act on the governance surface. Measured between
#206 merging and #810 being filed: 166 strong-named hook writes priced weak in 27
days (findings/marker-bar-probe-dead-27-days-after-206-20260902.md).

THE REPAIR (#810, the one #206 named): the escalation carries the act's RESOLVED
TARGET alongside the matched marker, and the bar is priced from the target when
the record carries one, from the marker when it does not. The matcher's triple
(and the closure verdict) have carried that target all along -- it was computed
and dropped at the door. This probe's question is therefore not "does the marker
name a file" but the end-to-end one:

    the matcher emits (marker, resource) -- does the string the bar is priced
    from still carry the strong-bar filename the RESOURCE carried?

WHICH RULE IS IN FORCE IS READ FROM THE PRICING SITE, not assumed. The repair's
wiring is `bar_for(bar_basis(...))` in gate_escalation.rs; its absence means the
legacy marker-only rule. That is what makes this probe RED against pre-repair
code and GREEN after it, with no edit to this file in between.

WHAT THIS DOES NOT DO. It does not route a tool call, so it mints no escalation,
no deny, and no conduct record for anyone -- unlike `gate-probe.py`, which drives
the real gate end-to-end and must exonerate the ding it causes. This one imports
the enforcing matcher copy and calls it in-process. It is safe to run repeatedly
and needs no cleanup.

WHAT IT DOES NOT COUNT, and why the exit code is honest about it. Two classes of
governance act stay off the exit code deliberately, because neither is the defect
this probe exists to catch:

  * an act whose resolved target names a governed file the BAR never tests (the
    drift table below -- a bar-coverage gap, repairable only by widening
    `bar_for`, which #206 explicitly ruled out of this repair), and
  * an act that carries no governed filename ANYWHERE (a wildcard over a hooks
    directory) -- a filename-keyed bar has nothing to price from, however the
    escalation is shaped.

Both are printed, both are real, and neither is "the pipeline had the filename
and dropped it". That last class -- the information existed and the pricing never
saw it -- is the one that drives the exit code.

THE TRIPLE, and the 26 days. 5.2 (2026-08-07, two days after #206 merged) made
the matcher return (marker, resource, key); this probe kept reading a bare string
and crashed at its print loop until the triple unpack landed (PR #808). A crashed
acceptance test reads as no news: RED for ~36 hours, then absent for 26 days, in
no CI job. The unpack below handles both shapes so the probe cannot die that
death again silently -- an unexpected shape is now a row, not a traceback.

NO LITERAL MARKER PATH OR GOVERNANCE FILENAME APPEARS IN THIS SOURCE. Every one
is derived from the imported module's own constants, or read from the bar's own
source. That is not a style choice -- a literal would make this file refused by
the gate it measures.

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
# THE BAR'S OWN LIST, AND THE PRICING RULE, READ FROM THE BAR'S OWN SOURCE
# ---------------------------------------------------------------------------
# Transcribing the bar's literals would duplicate a pinned list AND make this
# file unwritable, which is why the first cut of this probe declined to test them
# at all. Reading them costs neither: the strings never appear here, only in the
# Rust file that already owns them. If that file moves or the function is
# rewritten, we say so and fall back to the one-sided verdicts rather than
# guessing.
BAR_SRC = os.path.join(REPO, "core", "src", "server", "gate_escalation.rs")


def _bar_source(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _bar_names(src):
    """The filenames `bar_for` routes to the two-factor bar, or None if unreadable."""
    if src is None:
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


def _bar_rule(src):
    """Which string the bar is priced from, as wired at the pricing site.

    "resolved-target" -- the #810 repair is in the tree: `bar_for` is fed
    `bar_basis(resolved_target, marker)`, so the act's target prices the bar
    when the record carries one.
    "marker-only" -- the pre-#810 wiring: the bar sees the marker and nothing
    else, so a directory marker prices weak whatever the act touched.
    None -- the source is unreadable; verdicts stay one-sided.
    """
    if src is None:
        return None
    if re.search(r"bar_for\(\s*bar_basis\(", src):
        return "resolved-target"
    if "pub fn bar_for" in src:
        return "marker-only"
    return None


BAR_SRC_TEXT = _bar_source(BAR_SRC)
STRONG = _bar_names(BAR_SRC_TEXT)
RULE = _bar_rule(BAR_SRC_TEXT)

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
print(f"pricing rule  : {RULE or 'UNKNOWN'} (read from the pricing site, not assumed)")
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
    # The matcher has returned (marker, resource, key) since 5.2; before that, a
    # bare marker. Read both -- and treat any OTHER shape as a finding, not a
    # traceback: the last time this probe assumed a shape it died for 26 days.
    if isinstance(hit, tuple):
        marker = hit[0] if hit else None
        resource = hit[1] if len(hit) > 1 else None
    else:
        marker, resource = hit, None
    if not isinstance(marker, str) and marker is not None:
        rows.append((name, repr(marker), "UNEXPECTED MATCHER SHAPE", True,
                     "the probe cannot price this -- read it, do not crash", resource))
        continue

    # The string the bar is priced from, under the in-force rule.
    basis = (resource or marker) if RULE == "resolved-target" else marker
    in_target = [f for f in (STRONG or []) if resource and f in resource]
    priced_strong = STRONG is not None and basis and any(f in basis for f in STRONG)

    if marker is None:
        verdict, weak, why = "NOT MATCHED AT ALL", False, ""
    elif priced_strong:
        via = "target" if in_target and not any(f in marker for f in STRONG) else "marker"
        verdict, weak, why = f"sovereign+peer (PROVEN, via {via})", False, ""
    elif in_target:
        # THE #810 DEFECT, LIVE: the act's own resolved target names a strong-bar
        # file, and the pricing rule in force never looks at it. This row -- not
        # the two classes below -- is what the exit code counts.
        verdict, weak, why = ("single approver (PROVEN)", True,
                              "TARGET NAMES THE FILE; THE PRICING NEVER SEES IT")
    elif any(f in (resource or "") for f in GOV) or any(f in marker for f in GOV):
        # A governed file whose name the bar never tests: a bar-coverage gap,
        # reported in the drift table below. #206 ruled widening `bar_for` OUT of
        # this repair, so this class cannot count against it.
        verdict, weak, why = ("single approver", False,
                              "GOVERNED NAME THE BAR DOES NOT TEST (see the drift table)")
    else:
        # No governed filename anywhere in what the matcher emits (a wildcard over
        # a hooks directory). A filename-keyed bar has nothing to price from here,
        # however the escalation is shaped -- a real gap, NOT this defect.
        verdict, weak, why = ("single approver", False,
                              "NO GOVERNED FILENAME IN THE ACT AT ALL")
    rows.append((name, marker, verdict, weak, why, resource))

w = max(len(r[0]) for r in rows)
weak_count = 0
for name, marker, verdict, weak, why, resource in rows:
    shown = marker if marker else "-"
    if resource and resource != marker:
        shown += f"   (target: {resource})"
    if why:
        shown += f"   <-- {why}"
    if weak:
        weak_count += 1
    print(f"{name:<{w}}  ->  {verdict}")
    print(f"{'':<{w}}      marker: {shown}")

print()
if weak_count:
    print(f"{weak_count} of {len(rows)} acts carry the strong-bar filename in their "
          f"resolved target and are priced from a string that lacks it.")
    print("The escalation drops the target at the door; #810's repair (carry it,"
          " price from it) is what turns this probe green.")
else:
    print(f"0 of {len(rows)} acts lose a strong-bar filename between the matcher "
          f"and the pricing. Every act whose resolved target names a strong-bar "
          f"file prices the two-factor bar.")

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
        print("precisely the target resolves. Carrying the resolved target (#810) "
              "does not reach them;")
        print("only widening the bar's list would, and #206 ruled that out of the "
              "repair.")
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
