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

TWO THINGS THE FIRST CUT GOT WRONG, both found by running the matcher rather than
reading it, and both now checked. (1) The matcher's filename loop returns the FIRST
tuple entry that is a substring of the text, so a governed name containing an earlier
entry NEVER REACHES THE BAR AS ITSELF -- it is priced, escalated and approved under
the other name. One of the seven is in that state. The consequence is not cosmetic:
approvals are keyed on the marker string by exact equality, so those two files share
one price and one permit. (2) Two of the seven names have no file in this repo at
all; their only instances are installed copies. Both facts are declared per row and
red when they change. The general lesson, since this file exists to make governance
legible: **a binding test between two lists binds the lists, not the behaviour** --
what the matcher EMITS is a third thing, and it was the one that mattered.

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
SHADOWED = ("the matcher never emits this name at all -- an EARLIER tuple entry is a "
            "substring of it, so an act on this file carries that other name's marker "
            "and that other name's price")


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
#
# `tracked` says whether a file in THIS repo carries this basename. Two do not, and
# that is not a typo in the tuple: the matcher protects a NAME, and for those two the
# only instances are installed copies with no canonical source here. It is declared
# per row rather than counted, so losing a referent reds the row that lost it.
DECLARED = (
    dict(key="pre_", label="<gate>", intended=STRONG, via=EXACT, tracked=True,
         why="The enforcement path. A gate that permits everything ends the model; "
             "the bar's own doc comment names this class first. Stated policy."),

    dict(key="post", label="<post-hook>", intended=STRONG, via=EXACT, tracked=False,
         why="The other half of the outcome record. Same class as <witness> in the "
             "bar's doc comment. Stated policy. NOT TRACKED HERE: this name's only "
             "instances are installed copies, and the tracked file that does this "
             "job carries the same stem with a different extension -- which the "
             "tuple, matched as a literal substring, does not cover. So the strong "
             "class is real for the deployed artifact and absent for the one in "
             "review. Not filed as a defect: which of the two should be governed is "
             "a question about the deployment, not about this file."),

    dict(key="witn", label="<witness>", intended=STRONG, via=EXACT, tracked=True,
         why="The outcome recorder. Disarming it produces SILENCE rather than "
             "denials, and silence is indistinguishable from 'attempted nothing'. "
             "Named in the bar's doc comment. Stated policy."),

    dict(key="law_", label="<law-renderer>", intended=SINGLE, via=UNNAMED, tracked=True,
         why="Stated policy, and the only weak row that IS one: the bar's doc "
             "comment says a law renderer is one approver's call. Declared here so "
             "the deliberate case is distinguishable from the inherited ones."),

    # ---- the three the bar has never been asked about ----

    dict(key="soci", label="<society-gate>", intended=AWAITING, via=SHADOWED,
         tracked=False,
         why="CORRECTED 2026-08-05 -- the row shipped in 8552e4e said this name "
             "reaches the strong bar by a substring accident IN THE BAR, and that "
             "the remedy was one rust line. Both are wrong, and the second is the "
             "expensive error: the bar never receives this name. The matcher's "
             "filename loop returns the FIRST tuple entry that is a substring of "
             "the text, <gate>'s name is a substring of this one and sits at index "
             "0, so an act on this file emits <gate>'s marker. Naming this file in "
             "the bar would add a clause nothing can reach -- and check E would "
             "stay green about it, because the name IS in the matcher's tuple. "
             "Measured in-process against the enforcing copy, 7/7 names, exactly "
             "one shadowed. What follows is a live consequence, not a style note: "
             "the approval system keys on the marker string with exact equality, "
             "so one approval to edit <gate> is spendable on this file and vice "
             "versa -- and this is the copy that actually parked a member. Two "
             "files, two owners, one price and one permit. WHAT THE FIX WOULD AND "
             "WOULD NOT DO, measured rather than assumed (2026-08-06): un-shadowing "
             "changes the PERMIT POOL and nothing else. It changes the price of "
             "NONE of the seven -- this file already reaches two-factor under either "
             "name, because the bar's test is `contains` and this basename ends with "
             "the one the bar names. So the open question is not how expensive this "
             "surface should be; it is only whether an approval issued for one file "
             "may be spent on the other. EVIDENCE FOR THAT DECISION, cited and not "
             "adjudicated: the claim filter's own doc comment states an intent -- it "
             "matches on member AND marker, not on the member alone, so that "
             "approving a change to one governance file must not silently authorise "
             "a change to another. The shadowing makes precisely that happen for "
             "this pair. DECIDE: longest match in the matcher, or one approval "
             "covering both files as intended scope -- noting that the second "
             "reading contradicts a sentence already written at the filter."),

    dict(key="hestia_gate_c", label="<policy-core>", intended=AWAITING, via=UNNAMED, tracked=True,
         why="One approver today. Added to the matcher 2026-08-03, after the bar's "
             "doc comment was written, so its class was inherited from an omission "
             "rather than chosen. The matcher's own comment says this file is to "
             "BECOME the single decider for all five harnesses -- at which point "
             "the widest act on the surface is also the cheapest to approve. "
             "DECIDE: before the shims land, not after."),

    dict(key="hestia_gate_m", label="<policy-mechanism>", intended=AWAITING, via=UNNAMED,
         tracked=True,
         why="The shared in-process society-safety MECHANISM (#371). It carries the "
             "fail-closed contract and INTERPRETS the daemon's verdict into allow/deny, so on "
             "every adopting harness it directly decides whether a daemon answer authorises an "
             "act -- authority-bearing, not inert transport. One approver today, via UNNAMED: "
             "added to the matcher after the bar's doc comment, so it inherited the weak branch "
             "by omission, exactly like <policy-core>. GPT's #371 review (a reviewer, not the "
             "steward) inclines to price it STRONG (sovereign+peer), and I share that read: it "
             "sits closer to <gate>/<witness> than to <law-renderer>. But the class is a "
             "steward call, and writing my preference into this test is the 'surface that "
             "smuggles a verdict' the accountability norm forbids -- so this is AWAITING, "
             "measured SINGLE, carrying the question. DECIDE: name it in `bar_for` (two-factor) "
             "or leave it single. Unlike <society-gate> the name is NOT shadowed -- no earlier "
             "tuple entry is a substring of it -- so a bar clause for it would be LIVE, not "
             "dead. Recommend deciding before the shims adopt it (step F), when editing this "
             "one file re-prices the safety verdict for all five harnesses at once."),

    dict(key="gate_self", label="<exemption-ledger>", intended=AWAITING, via=UNNAMED,
         tracked=True,
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
    the governed tuple. Discovered, not named -- see the module docstring.

    Returns a list, and the caller fails on anything but exactly one. Returning the
    FIRST hit would be a silent selection: on the day a second file in that
    directory declares a governed tuple, this test would quietly bind to whichever
    `git ls-files` happened to sort first and report green about the other one."""
    found = []
    for p in _tracked(_MATCHER_SEGMENTS):
        try:
            tree = ast.parse((REPO / p).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if _tuple_from(tree, "_GOVERNANCE_FILES") is not None:
            found.append(p)
    return found


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
    """Same contract as `_matcher_path`: every candidate, never the first."""
    return [(p, (REPO / p).read_text(encoding="utf-8", errors="replace"))
            for p in _tracked(_BAR_SEGMENTS, suffix=".rs")
            if "pub fn bar_for" in (REPO / p).read_text(encoding="utf-8",
                                                        errors="replace")]


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


def _emitted_marker(name, governed):
    """The marker the matcher would hand the bar for a path naming `name`.

    TRANSCRIBED, not paraphrased: the matcher's filename loop walks its tuple in
    order and RETURNS the first entry that is a substring of the text. So a name
    that contains an earlier entry never reaches the bar as itself -- the same
    first-match shadowing already known between the marker tuple's file and
    directory elements, one level down, inside the governed tuple.

    Two conditions of the real loop are not modelled and both only ever produce
    LESS matching, never more: an act whose text also hits a `_SELF_MARKERS`
    element returns that instead, and a name on the hooks-dir-only list needs a
    hooks segment in the text. This function assumes the favourable case (a path
    under a hooks directory, no marker hit) and therefore reports the STRONGEST
    marker a name can attain -- so a name it calls shadowed is shadowed under every
    condition.

    The transcription was validated once against the real function rather than
    trusted: imported in-process and called for all 7 governed names on a
    `/.../hooks/<name>` path, 2026-08-05 -- 7/7 agreement, exactly one shadowed.
    That probe is not run here; importing the matcher is what this file's docstring
    promises not to do."""
    return next((f for f in governed if f in name), None)


def _tracked_basenames():
    """Every basename with at least one tracked file in this repo."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, check=True).stdout
    return {os.path.basename(raw.decode()) for raw in out.split(b"\0") if raw}


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

    candidates = _matcher_path()
    if len(candidates) != 1:
        bad(f"expected exactly one in-tree file declaring the governed tuple, "
            f"found {len(candidates)}. Zero: this test cannot bind what it cannot "
            f"read, and a binding test that degrades to one side is the defect it "
            f"exists to catch. More than one: the surface is declared twice and "
            f"binding to either is a silent choice.")
        return fails, out
    mpath = candidates[0]

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
    bars = _bar_source()
    if len(bars) != 1:
        bad(f"expected exactly one rust source defining `bar_for`, found "
            f"{len(bars)}. Zero: the rust half of the binding is gone, which IS "
            f"drift, not an excuse. More than one: two functions price the same "
            f"surface and the enforcing one is a guess.")
        return fails, out
    bpath, disk_btext = bars[0]
    btext = disk_btext if bar_text is None else bar_text
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
    def _from_bar(name):
        """(class, mechanism) for the marker string `name`, per the bar alone."""
        hit = [s for s in strong if s in name]
        if not hit:
            return SINGLE, UNNAMED
        return STRONG, (EXACT if hit[0] == name else SUBSTRING)

    tracked_names = _tracked_basenames()
    awaiting, shadowed_n, untracked_n = [], 0, 0
    for g in governed:
        row = by_name.get(g)
        if row is None:
            continue
        # G. What the MATCHER emits comes first: a shadowed name never reaches the
        # bar, so deriving its class from the bar's opinion of ITS OWN spelling is
        # deriving from a string the bar is never handed.
        emitted = _emitted_marker(g, governed)
        if emitted != g:
            derived, _ignored = _from_bar(emitted)
            via = SHADOWED
            shadowed_n += 1
        else:
            derived, via = _from_bar(g)

        # H. a governed name with no tracked file here governs installed copies only.
        is_tracked = g in tracked_names
        if not is_tracked:
            untracked_n += 1
        if is_tracked != row["tracked"]:
            bad(f"{row['label']}: declared tracked={row['tracked']}, measured "
                f"tracked={is_tracked} -- a tracked file with this basename "
                f"{'appeared' if is_tracked else 'is gone'}. A governed name with no "
                f"file here is protection that exists as a STRING: nothing in this "
                f"repo can be reviewed, diffed, or renamed-with-a-red for it, and "
                f"its class is a claim about an artifact no in-tree test has seen. "
                f"Gaining one is the good direction and still a reviewed diff -- the "
                f"class was written for the copy nobody could read.")

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
        note = ("  [shadowed: priced as another name]" if via is SHADOWED else "")
        note += ("  [installed-only: no file here]" if not is_tracked else "")
        out.append(f"  {row['label']:<22} {derived:<16} {mark}{note}")

    out.append("")
    out.append(f"{shadowed_n} of {len(governed)} governed names never reach the bar "
               f"as themselves (an earlier tuple entry is a substring); "
               f"{untracked_n} name no file tracked in this repo")

    # --- E. the bar names nothing the matcher does not govern.
    #
    # Note what E does NOT catch, since the gap cost this file a wrong row: a bar
    # clause naming a SHADOWED governed name passes E -- the name is in the tuple,
    # so the branch reads as covered -- while the matcher can never emit it, so the
    # clause is dead. E asks whether the bar's names are governed; only the shadow
    # check above asks whether the bar can ever be handed them.
    for s in strong:
        if not any(s in g for g in governed):
            bad("`bar_for` routes a basename the matcher does not govern -- the bar "
                "prices a surface that never escalates, so the branch is dead and "
                "reads as coverage")

    # --- I. every clause in the bar is one an escalation can actually REACH.
    #
    # This closes the gap the note above E describes, which this file documented and
    # did not check. E asks whether a bar clause names a governed name. I asks the
    # question that decides whether the clause can ever fire: is it the clause that
    # WINS for some marker the matcher can actually emit? A clause naming a shadowed
    # governed name passes E and is dead -- nothing will ever be priced by it.
    #
    # This matters right now, not hypothetically. The remedy proposed for the shadowed
    # row was "add one clause to the bar for that name". Measured, that clause would be
    # dead on arrival: the matcher never emits the name, so no escalation can be handed
    # it. Un-shadowing changes the PERMIT POOL, not the price -- the shadowed name
    # already prices two-factor by the bar's own substring test, whichever name reaches
    # it. Without this check the no-op remedy lands green and reads as a fix.
    #
    # I SUBSUMES E, and that is said here rather than discovered later. Every emitted
    # marker is itself a governed name, so a clause deciding some marker is necessarily
    # contained in a governed name and E cannot have fired on it; contrapositively,
    # anything E catches, I catches. E is kept anyway: its message names the specific
    # condition (a clause for a surface that never escalates at all), and collapsing two
    # distinct diagnoses into one broader one costs the reader the reason. Both fire on
    # the E sabotage; the sabotage asserts E's own text.
    emitted = {_emitted_marker(g, governed) for g in governed} - {None}
    deciding = {hit[0] for hit in ([s for s in strong if s in e] for e in emitted)
                if hit}
    for s in strong:
        if s not in deciding:
            bad("`bar_for` carries a clause NO ESCALATION CAN EVER REACH: no marker "
                "the matcher can emit is decided by it, either because the name it "
                "prices is shadowed by an earlier tuple entry or because an earlier "
                "clause wins on every marker it would match. The branch is dead and "
                "reads as coverage -- pricing written for acts that will never be "
                "handed to it.")

    # --- F. the marker tuple's directory elements.
    # The escalation carries the MATCHED MARKER, not the act's path, and a marker
    # that names no file cannot match a bar testing for filenames -- so every
    # directory element in that tuple routes to the single-approver branch by
    # construction, however precisely the bar is written. Pinned so a new one is a
    # reviewed diff rather than a widening nobody sees.
    #
    # PIN MOVED 2 -> 4 (PR #275, reviewed in shared-context forum "Two reds in a
    # queue of ten", 2026-08-07): the two installer markers
    # (`plugins/claude-code/install.sh`, `deploy/install-members.sh`) join the two
    # hook-directory markers. The review's rationale, which this bump must carry:
    # (1) both price at SingleApprover -- `bar_for` (gate_escalation.rs:228-237)
    #     escalates only markers containing `pre_tool_use.py`, `post_tool_use.py`
    #     or `witness.py`, and neither installer path contains one, so the act
    #     that REWRITES the gate is escalatable at one approver while editing the
    #     gate needs two. Priced, not uncontrollable.
    # (2) reachable, not shadowed -- the matcher returns the FIRST tuple entry
    #     that is a substring of the tool input, and no earlier entry is a
    #     substring of either installer path, so the markers are emitted as
    #     themselves: a live clause, two lines in `bar_for` from a higher bar.
    # (3) this move is a TIGHTENING, not the widening the failure message below
    #     asserts: the prior state of `bash <installer>` was ALLOWED outright
    #     (no set), so the diff moves ungoverned -> weak, not strong -> weak.
    #     The message conflates the two; fixing it is follow-up against main,
    #     not a blocker here.
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
        if len(dir_lits) != 4 or computed != 2:
            bad(f"the marker tuple's shape moved (expected 2 computed + 4 literal "
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
    mpaths, bars = _matcher_path(), _bar_source()
    if len(mpaths) != 1 or len(bars) != 1:
        print("sabotages not run: the sources are not uniquely identified, which "
              "audit() reports as its own failure")
        return 1
    mt = (REPO / mpaths[0]).read_text(encoding="utf-8", errors="replace")
    bt = bars[0][1]
    governed, _ = _tuple_from(ast.parse(mt), "_GOVERNANCE_FILES")
    marker_lits, _n = _tuple_from(ast.parse(mt), "_SELF_MARKERS")
    strong = _bar_names(bt)

    # A bar literal that a row declares STRONG/EXACT -- the one whose removal must
    # surface as a declared-vs-measured mismatch.
    exact_rows = [r for r in DECLARED if r["intended"] is STRONG and r["via"] is EXACT]
    exact_name = next(g for g in governed
                      if any(g.startswith(r["key"]) for r in exact_rows) and g in strong)
    # The row whose name never reaches the bar as itself, and that governed name.
    shadow_row = next(r for r in DECLARED if r["via"] is SHADOWED)
    shadow_name = next(g for g in governed if g.startswith(shadow_row["key"]))
    # The declaration with that row's `via` put back to what 8552e4e shipped. The
    # error this file corrects lived in the DECLARATION, not in either source, so a
    # sabotage set that only ever mutates the sources cannot reach its own class of
    # defect -- and this file shipped one.
    was_substring = tuple(dict(r, via=SUBSTRING) if r is shadow_row else r
                          for r in DECLARED)
    # A row to collide a key against, and a victim name to rename onto its key.
    other_row = next(r for r in DECLARED if r["intended"] is SINGLE)
    other_name = next(g for g in governed if g.startswith(other_row["key"]))
    collide_key = exact_rows[0]["key"]

    unknown = "zz_ungoverned_probe.py"
    # (label, matcher text, bar text, declaration, expected failure substring)
    cases = [
        ("a governed name is REMOVED, orphaning its declaration",
         _drop_line(mt, f'"{governed[-1]}"'), bt, DECLARED,
         "matches 0 governed names"),

        ("a NEW governed name lands with no declared class",
         _insert_before(mt, f'"{governed[0]}"', f'    "{unknown}",\n'), bt, DECLARED,
         "NO declared class"),

        ("the bar stops naming a surface declared two-factor",
         mt, _drop_line(bt, f'contains("{exact_name}")'), DECLARED, "change the bar"),

        ("the bar prices a name the matcher does not govern",
         mt, _insert_before(bt, 'contains("',
                            f'        || marker.contains("{unknown}")\n'),
         DECLARED, "does not govern"),

        ("a new DIRECTORY marker widens the set that cannot reach the strong bar",
         _insert_before(mt, f'"{marker_lits[0]}"', '    "zz/dir/marker",\n'), bt,
         DECLARED, "marker tuple's shape moved"),

        ("a rename lifts a shadowed name out from under the one pricing it",
         _rename(mt, shadow_name,
                 shadow_name[:len(shadow_row["key"])] + "_renamed.py"), bt,
         DECLARED, "DIFFERENT mechanism"),

        ("a rename makes two governed names collide on one declaration key",
         _rename(mt, other_name, collide_key + other_name), bt, DECLARED,
         "matches 2 governed names"),

        ("a rename puts a name UNDER an earlier one, so the bar never sees it",
         _rename(mt, other_name, other_row["key"] + exact_name), bt, DECLARED,
         "never emits this name"),

        ("a governed name loses the last tracked file that carries it",
         _rename(mt, other_name, other_name[:-3] + "zz.py"), bt, DECLARED,
         "measured tracked=False"),

        ("the DECLARATION mis-states the mechanism (the 8552e4e row, restored)",
         mt, bt, was_substring, "DIFFERENT mechanism"),

        # The proposed remedy for the shadowed row, applied. It must red, and that is
        # the point of the check it trips: the fix is a no-op and the test says so
        # instead of greening on it.
        ("the 'one rust line' remedy: a bar clause for the SHADOWED name",
         mt, _insert_before(bt, 'contains("',
                            f'        || marker.contains("{shadow_name}")\n'),
         DECLARED, "NO ESCALATION CAN EVER REACH"),
    ]

    base_fails, _ = audit()
    ok = not base_fails
    print(f"baseline (unmutated)                         "
          f"-> {'clean' if ok else 'ALREADY RED: ' + '; '.join(base_fails)}")
    if not ok:
        return 1

    bad = 0
    for label, m_text, b_text, decl, expect in cases:
        fails, _ = audit(matcher_text=m_text, bar_text=b_text, declared=decl)
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
