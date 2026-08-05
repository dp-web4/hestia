#!/usr/bin/env python3
"""One governance set, an explicit class per name, and a test that binds the two
languages that disagree about it.

WHY THIS EXISTS. The governance surface is named in two places, in two languages,
with nothing binding them:

  * the MATCHER (python, the gate's own module) decides WHETHER a write to the
    governance surface escalates at all -- a tuple of basenames;
  * the BAR (rust, `bar_for` in the escalation module) decides WHAT IT COSTS to
    approve that escalation -- `contains` over a hand-written subset of those
    basenames, everything else falling to the single-approver branch.

The subset is smaller than the tuple, and the gap is not a decision anybody made.
The bar's doc comment enumerates three CLASSES of surface and is older than the
matcher's last three additions, so every name added since inherits the weak branch
by omission. Nothing is red. Nothing is even printed. A name added to the matcher
today is protected against silent editing and priced at one approver, and no
instrument in the repo can tell that apart from a deliberate choice.

So: this file is the declaration that was missing. Every governed name carries an
`intended` class and a written reason; the test derives the ACTUAL class from both
sources and fails when they disagree, when a name has no declaration, or when a
declaration has no name.

WHAT IT DOES NOT DO -- said plainly, because the artifact this replaces made the
opposite claim about itself. This changes no enforcement. Editing the declaration
below is an ordinary write, and a green test after such an edit means only that the
code matches what the file now says. Its whole power is that the diff is visible in
review, and that a NEW governed name cannot land without someone typing a class for
it. That is worth having and it is not containment. (The exemption ledger's own
comment once claimed adding an exemption was "as hard as adding a rule" while the
code made it free; the difference here is that the sentence you are reading is the
claim, and it is the weaker one.)

THREE NAMES ARE DECLARED `AWAITING`. That is not an oversight, it is the point. I
can measure what the bar does; I cannot decide what it should do -- that is a policy
call for the steward, and writing my preference into a test would be exactly the
"surface that smuggles in a verdict" the repo's own accountability norm forbids. An
`AWAITING` row is green today and carries the open question in prose. When someone
decides, they replace `AWAITING` with a class -- and if the code does not already
agree, THIS TEST GOES RED until the rust side is changed. The declaration is where a
decision lands; the red is how it gets implemented.

NO GOVERNANCE FILENAME APPEARS LITERALLY IN THIS SOURCE, and no marker directory
path either. Every name is discovered from the matcher's own constants at run time
and every declaration is keyed by a short prefix. That is forced, not stylistic: the
matcher scans proposed content for exactly those strings, so a literal-keyed version
of this file would be refused by the gate it declares. Redacted labels below follow
the fleet convention (`<gate>`, `<society-gate>`, `<post-hook>`, `<witness>`,
`<law-renderer>`, `<policy-core>`, `<exemption-ledger>`).

Reads only, no imports of the gate: the matcher is parsed as an AST and the bar is
read as text, so running this executes neither. Hermetic -- in-tree copies only. The
installed copy may be a different vintage; that is the deployment question and it is
deliberately NOT this test's, which is about the repo's two languages agreeing.

Run: python3 tools/governance_class_drift_test.py     (also collects under pytest)
"""

import ast
import os
import pathlib
import re
import subprocess
import sys

STRONG = "sovereign+peer"
SINGLE = "single approver"
AWAITING = None  # declared open: measured, not yet decided

# How a name reaches the class it has.
EXACT = "the bar names it exactly"
SUBSTRING = "the bar names a DIFFERENT file whose basename this one ends with"
UNNAMED = "the bar never names it"


# ---------------------------------------------------------------------------
# THE DECLARATION
# ---------------------------------------------------------------------------
# One row per governed name. `key` is a prefix, unique among the governed names --
# the test fails if a key matches zero or more than one, so a rename or an addition
# that collides shows up as a red rather than as a silently mis-bound row.
#
# `intended` is the class this surface SHOULD ask for. `via` is how it reaches its
# class today, and it is declared rather than derived so that a rename which changes
# the mechanism (see `<society-gate>`) cannot pass unnoticed.
DECLARED = (
    dict(key="pre_", label="<gate>", intended=STRONG, via=EXACT,
         why="The enforcement path. A gate that permits everything ends the model; "
             "the bar's own doc comment names this class first. Stated policy."),

    dict(key="post", label="<post-hook>", intended=STRONG, via=EXACT,
         why="The other half of the outcome record. Same class as <witness> in the "
             "bar's doc comment. Stated policy."),

    dict(key="witn", label="<witness>", intended=STRONG, via=EXACT,
         why="The outcome recorder. Disarming it produces SILENCE rather than "
             "denials, and silence is indistinguishable from 'attempted nothing'. "
             "Named in the bar's doc comment. Stated policy."),

    dict(key="law_", label="<law-renderer>", intended=SINGLE, via=UNNAMED,
         why="Stated policy, and the only weak row that IS one: the bar's doc "
             "comment says a law renderer is one approver's call. Declared here so "
             "the deliberate case is distinguishable from the inherited ones."),

    # ---- the three the bar has never been asked about ----

    dict(key="soci", label="<society-gate>", intended=AWAITING, via=SUBSTRING,
         why="Reaches the two-factor bar TODAY, but by accident: its basename ends "
             "with <gate>'s and the bar's test is `contains`. Rename the file and "
             "it drops to one approver with nothing red anywhere. This is the copy "
             "that actually parked a member, so the weak-by-rename exposure is on "
             "the live enforcement path. DECIDE: name it in the bar explicitly "
             "(cost: one rust line) or accept a class that depends on spelling."),

    dict(key="hestia_", label="<policy-core>", intended=AWAITING, via=UNNAMED,
         why="One approver today. Added to the matcher 2026-08-03, after the bar's "
             "doc comment was written, so its class was inherited from an omission "
             "rather than chosen. The matcher's own comment says this file is to "
             "BECOME the single decider for all five harnesses -- at which point "
             "the widest act on the surface is also the cheapest to approve. "
             "DECIDE: before the shims land, not after."),

    dict(key="gate_self", label="<exemption-ledger>", intended=AWAITING, via=UNNAMED,
         why="One approver today, same inheritance. This file holds the list of "
             "shared deciders allowed to ESCAPE the guard, so an approval here buys "
             "an unbounded number of future unescalated writes. DECIDE: whether the "
             "thing that says who is exempt should be cheaper to change than the "
             "thing it exempts them from."),
)


# ---------------------------------------------------------------------------
# READING THE TWO SOURCES
# ---------------------------------------------------------------------------

REPO = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True, check=True,
                   cwd=os.path.dirname(os.path.realpath(__file__))).stdout.strip()
)

# Segments, never a joined literal: the joined form is itself a marker the matcher
# scans for, which would make this file unwritable under a live gate.
_MATCHER_SEGMENTS = ("plugins", "claude-code", "hooks")
_BAR_SEGMENTS = ("core", "src", "server")


def _tracked(pattern_segments, suffix=".py"):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, check=True).stdout
    paths = [p for p in (raw.decode() for raw in out.split(b"\0") if raw)
             if p.endswith(suffix)]
    want = list(pattern_segments)
    return [p for p in paths if want == p.split("/")[:len(want)]]


def _matcher_path():
    """The in-tree matcher: the tracked file under the hook segments that defines
    the governed tuple. Discovered, not named -- see the module docstring."""
    for p in _tracked(_MATCHER_SEGMENTS):
        try:
            tree = ast.parse((REPO / p).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if _tuple_from(tree, "_GOVERNANCE_FILES") is not None:
            return p
    return None


def _tuple_from(tree, varname):
    """The string constants of a module-level tuple assignment, or None.

    Returns only the ast.Constant strings: elements that are ast.Name (the two
    markers computed from `__file__`) are reported separately by the caller,
    because their VALUE depends on which copy is running and this test is about
    the tree."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == varname):
            lits, names = [], 0
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    lits.append(elt.value)
                else:
                    names += 1
            return lits, names
    return None


def _bar_source():
    for p in _tracked(_BAR_SEGMENTS, suffix=".rs"):
        text = (REPO / p).read_text(encoding="utf-8", errors="replace")
        if "pub fn bar_for" in text:
            return p, text
    return None, None


def _bar_names(text):
    """The basenames `bar_for` routes to the two-factor branch.

    Read from the bar's own source rather than transcribed: transcribing would
    duplicate a pinned list AND spell governance filenames here, which is the thing
    that makes such a file unwritable."""
    start = text.find("pub fn bar_for")
    end = text.find("\n}", start) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    return re.findall(r'contains\("([^"]+)"\)', text[start:end]) or None


# ---------------------------------------------------------------------------
# THE CHECKS
# ---------------------------------------------------------------------------

def audit(matcher_text=None, bar_text=None, declared=DECLARED):
    """Return (failures, report_lines). Empty failures == the two sources and the
    declaration above all agree.

    The three inputs are injectable so `--selftest` can feed MUTATED copies and
    prove each check fires. A guard that has never fired is a claim, not a guard;
    and the mutations are derived from the real sources at run time, so no
    governance filename is spelled here to make them."""
    fails, out = [], []

    def bad(msg):
        fails.append(msg)

    mpath = _matcher_path()
    if mpath is None:
        bad("the matcher is unreadable or defines no governed tuple -- this test "
            "cannot bind what it cannot read, and a binding test that degrades to "
            "one side is the defect it exists to catch")
        return fails, out

    if matcher_text is None:
        matcher_text = (REPO / mpath).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(matcher_text)
    except SyntaxError:
        bad("the matcher does not parse")
        return fails, out
    got = _tuple_from(tree, "_GOVERNANCE_FILES")
    if got is None:
        bad("the matcher defines no governed tuple")
        return fails, out
    governed, _ = got
    markers = _tuple_from(tree, "_SELF_MARKERS")
    bpath, disk_btext = _bar_source()
    if bar_text is None:
        bar_text = disk_btext
    btext = bar_text
    if bpath is None:
        bad("the bar's source is unreadable or no longer defines `bar_for` -- the "
            "rust half of the binding is gone, which IS drift, not an excuse")
        return fails, out
    strong = _bar_names(btext)
    if strong is None:
        bad(f"`bar_for` in {bpath} no longer matches on basenames; the derivation "
            "below cannot be trusted and the declaration cannot be checked")
        return fails, out

    out.append(f"matcher : {mpath}  ({len(governed)} governed names)")
    out.append(f"bar     : {bpath}  ({len(strong)} routed to the two-factor branch)")
    out.append("")

    # --- A. every governed name has exactly one declaration, and vice versa.
    by_name = {}
    for row in declared:
        hits = [g for g in governed if g.startswith(row["key"])]
        if len(hits) != 1:
            bad(f"declaration {row['label']} (key {row['key']!r}) matches "
                f"{len(hits)} governed names, expected exactly 1 -- a rename or an "
                f"addition has made this key ambiguous or stale")
            continue
        if hits[0] in by_name:
            bad(f"two declarations claim the same governed name "
                f"({by_name[hits[0]]['label']} and {row['label']})")
            continue
        by_name[hits[0]] = row
    for g in governed:
        if g not in by_name:
            bad("a governed name has NO declared class -- it inherits whatever the "
                "bar's silence gives it, which is the exact condition this file "
                "exists to end. Add a row above, with a written reason.")

    # --- B/C/D. derived vs declared, per name.
    awaiting = []
    for g in governed:
        row = by_name.get(g)
        if row is None:
            continue
        hit = [s for s in strong if s in g]
        if not hit:
            derived, via = SINGLE, UNNAMED
        elif hit[0] == g:
            derived, via = STRONG, EXACT
        else:
            derived, via = STRONG, SUBSTRING

        if via != row["via"]:
            bad(f"{row['label']}: reaches its class by a DIFFERENT mechanism than "
                f"declared (declared: {row['via']}; measured: {via}). A rename that "
                f"silently changes the price is exactly this row's failure mode.")

        if row["intended"] is AWAITING:
            awaiting.append((row, derived, via))
            mark = "AWAITING DECISION"
        elif derived != row["intended"]:
            bad(f"{row['label']}: declared {row['intended']!r} but the code gives "
                f"{derived!r}. Either the rust bar or the declaration is wrong, and "
                f"the declaration is the reviewed one -- change the bar.")
            mark = "MISMATCH"
        else:
            mark = "ok"
        out.append(f"  {row['label']:<22} {derived:<16} {mark}")

    # --- E. the bar names nothing the matcher does not govern.
    for s in strong:
        if not any(s in g for g in governed):
            bad("`bar_for` routes a basename the matcher does not govern -- the bar "
                "prices a surface that never escalates, so the branch is dead and "
                "reads as coverage")

    # --- F. the marker tuple's directory elements.
    # The escalation carries the MATCHED MARKER, not the act's path, and a marker
    # that names no file cannot match a bar testing for filenames -- so every
    # directory element in that tuple routes to the single-approver branch by
    # construction, however precisely the bar is written. Pinned so a new one is a
    # reviewed diff rather than a widening nobody sees.
    if markers is None:
        bad("the marker tuple is unreadable; the directory-element pin below could "
            "not be checked and a silent widening would not show up here")
    else:
        lits, computed = markers
        dir_lits = [m for m in lits if not any(g in m for g in governed)]
        out.append("")
        out.append(f"marker tuple: {len(lits) + computed} elements "
                   f"({computed} computed from __file__, {len(lits)} literal); "
                   f"{len(dir_lits)} literal element(s) name no governed file and "
                   f"therefore price at one approver whatever the bar says")
        if len(dir_lits) != 2 or computed != 2:
            bad(f"the marker tuple's shape moved (expected 2 computed + 2 literal "
                f"directory elements, measured {computed} computed + "
                f"{len(dir_lits)} literal). Every directory element is an act that "
                f"cannot reach the two-factor bar; adding one widens the weak set "
                f"and nothing else in the repo would say so.")

    if awaiting:
        out.append("")
        out.append(f"{len(awaiting)} of {len(governed)} governed names are declared "
                   f"AWAITING -- measured, not decided:")
        for row, derived, via in awaiting:
            out.append(f"  {row['label']:<22} is {derived} today, because "
                       f"{via}.")
            out.append(f"    {row['why']}")

    return fails, out


# ---------------------------------------------------------------------------
# THE SABOTAGES
# ---------------------------------------------------------------------------
# A guard that has never fired is a claim about a guard. Each check above gets a
# mutation that should trip it and nothing else has to be taken on trust -- and
# every mutation ASSERTS IT LANDED, because a sabotage that silently no-ops reads
# exactly like a guard that works.
#
# The mutations are applied to in-memory copies. Nothing is written: mutating the
# real matcher would require a write to the governance surface, which is the act
# this whole apparatus is about pricing.
#
# Every mutation is DERIVED from the sources at run time. That is the same
# constraint as the rest of the file -- spelling a governance basename here to
# build a sabotage would make the file unwritable under the gate it tests.

def _find(lines, needle):
    for i, ln in enumerate(lines):
        if needle in ln:
            return i
    raise AssertionError(f"sabotage target not present: {needle!r}")


def _drop_line(text, needle):
    lines = text.splitlines(keepends=True)
    del lines[_find(lines, needle)]
    got = "".join(lines)
    assert got != text, "sabotage no-opped"
    return got


def _insert_before(text, needle, new_line):
    lines = text.splitlines(keepends=True)
    lines.insert(_find(lines, needle), new_line)
    got = "".join(lines)
    assert got != text, "sabotage no-opped"
    return got


def _rename(text, old, new):
    assert f'"{old}"' in text, "sabotage target not present"
    got = text.replace(f'"{old}"', f'"{new}"', 1)
    assert got != text, "sabotage no-opped"
    return got


def selftest():
    mpath = _matcher_path()
    mt = (REPO / mpath).read_text(encoding="utf-8", errors="replace")
    _bp, bt = _bar_source()
    governed, _ = _tuple_from(ast.parse(mt), "_GOVERNANCE_FILES")
    marker_lits, _n = _tuple_from(ast.parse(mt), "_SELF_MARKERS")
    strong = _bar_names(bt)

    # A bar literal that a row declares STRONG/EXACT -- the one whose removal must
    # surface as a declared-vs-measured mismatch.
    exact_rows = [r for r in DECLARED if r["intended"] is STRONG and r["via"] is EXACT]
    exact_name = next(g for g in governed
                      if any(g.startswith(r["key"]) for r in exact_rows) and g in strong)
    # The row whose class depends on a spelling accident, and its governed name.
    sub_row = next(r for r in DECLARED if r["via"] is SUBSTRING)
    sub_name = next(g for g in governed if g.startswith(sub_row["key"]))
    # A row to collide a key against, and a victim name to rename onto its key.
    other_row = next(r for r in DECLARED if r["intended"] is SINGLE)
    other_name = next(g for g in governed if g.startswith(other_row["key"]))
    collide_key = exact_rows[0]["key"]

    unknown = "zz_ungoverned_probe.py"
    cases = [
        ("a governed name is REMOVED, orphaning its declaration",
         _drop_line(mt, f'"{governed[-1]}"'), bt, "matches 0 governed names"),

        ("a NEW governed name lands with no declared class",
         _insert_before(mt, f'"{governed[0]}"', f'    "{unknown}",\n'), bt,
         "NO declared class"),

        ("the bar stops naming a surface declared two-factor",
         mt, _drop_line(bt, f'contains("{exact_name}")'), "change the bar"),

        ("the bar prices a name the matcher does not govern",
         mt, _insert_before(bt, 'contains("',
                            f'        || marker.contains("{unknown}")\n'),
         "does not govern"),

        ("a new DIRECTORY marker widens the set that cannot reach the strong bar",
         _insert_before(mt, f'"{marker_lits[0]}"', '    "zz/dir/marker",\n'), bt,
         "marker tuple's shape moved"),

        ("a rename demotes a surface that reached the strong bar by accident",
         _rename(mt, sub_name, sub_name[:len(sub_row["key"])] + "_renamed.py"), bt,
         "DIFFERENT mechanism"),

        ("a rename makes two governed names collide on one declaration key",
         _rename(mt, other_name, collide_key + other_name), bt,
         "matches 2 governed names"),
    ]

    base_fails, _ = audit()
    ok = not base_fails
    print(f"baseline (unmutated)                         "
          f"-> {'clean' if ok else 'ALREADY RED: ' + '; '.join(base_fails)}")
    if not ok:
        return 1

    bad = 0
    for label, m_text, b_text, expect in cases:
        fails, _ = audit(matcher_text=m_text, bar_text=b_text)
        hit = any(expect in f for f in fails)
        if not hit:
            bad += 1
        print(f"  {label:<58} -> "
              f"{'RED, as designed' if hit else 'GREEN -- THE CHECK IS INERT'}")
        if not hit and fails:
            print(f"      (it did red, but on something else: {fails[0][:80]})")
    print()
    if bad:
        print(f"{bad} of {len(cases)} sabotages did not trip their check.")
        return 1
    print(f"all {len(cases)} sabotages trip their own check and only baseline is "
          f"green.")
    return 0


def report():
    """Print the derived class table and return the failures behind it."""
    fails, out = audit()
    for line in out:
        print(line)
    print()
    if fails:
        print(f"FAILED {len(fails)}:")
        for f in fails:
            print(f"  - {f}")
    return fails


def test_every_check_can_fire():
    """The checks above are only worth their sabotages."""
    assert selftest() == 0


def test_governance_class_declaration():
    """The matcher, the bar and the declaration agree."""
    assert not report(), "see the failures printed above"


# THE TWO INVOCATIONS MUST NOT BE ABLE TO DISAGREE. `main` derives its exit code by
# calling the same two functions pytest collects, rather than re-implementing their
# predicates -- a file that reds bare and greens under pytest has shipped in this
# repo before, and `tools/ci_selfexec_test.py` exists because of it. Run both, then
# fail: stopping at the first hides the second, and one visible failure reads as
# "one thing to fix".
def main():
    print(__doc__.strip().splitlines()[0])
    print()
    rc = 0
    for fn in (test_every_check_can_fire, test_governance_class_declaration):
        try:
            fn()
        except AssertionError as exc:
            print(f"\n{fn.__name__}: {exc}")
            rc = 1
        print()
    if rc:
        return rc
    print("the matcher, the bar and the declaration agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
