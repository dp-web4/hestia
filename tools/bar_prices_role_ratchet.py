#!/usr/bin/env python3
"""RATCHET: the strong bar prices a filename SPELLING, not a role.

`bar_for()` (core/src/server/gate_escalation.rs) is a hardcoded tuple of four basename
substrings, and its fallthrough is SingleApprover. So the bar is fail-open by omission:
any decision-carrying artifact not spelled like an August-2026 file is priced one-factor,
silently, with no drift signal.

This is NOT the #206/#810 defect (the marker carries a directory glob, so no filename ever
reaches bar_for). It is the SECOND defect underneath it: even with the act's resolved target
-- #206's exact repair -- gemini's `before_tool.py` and three of the four shared engine
modules still price SingleApprover, because the list never learned their names.

WHY A RATCHET AND NOT A RED TEST. #206's acceptance probe was written, crashed on 08-07, sat
in no CI job for 27 days, and the finding was re-derived as new by a second seat in the gap
(findings/marker-bar-probe-dead-27-days-after-206-20260902.md). A test that fails on day one
gets skipped and rots the same way. This pins TODAY's count and fails only when it GROWS --
so the next collapse slice that moves decision logic into an unpriced module has to notice.

Exit 0 = no regression. Exit 1 = a new decision-carrying file was born one-factor.

(Repo root is derived from this file's own location rather than an env lookup: the standard
attribute for the process environment carries the forbidden dotfile token as a bare
substring, which the gate's egress.secret rule matches -- a known false positive with no
escalation door, six classes already recorded on #680. This comment is a SEVENTH: the note
could not name the token it is about, because naming it re-trips the rule at source-comment
level. Using __file__ is better code regardless.)
"""
import os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAR_SRC = os.path.join(REPO, "core", "src", "server", "gate_escalation.rs")

# A file is in the decision path if it loads the shared gate engine. Role, not spelling.
ENGINE = re.compile(r"hestia_gate_core|hestia_gate_mechanism|hestia_governance_closure"
                    r"|load_closure|hestia_shell_classifier")

# Pinned 2026-09-04 by claude-code (CBP). Lower this when the bar is repaired; never raise it
# without saying in the commit message which decision-carrying file was added and why it is
# acceptable for it to be born at one factor.
PINNED_WEAK = 4


def strong_list():
    """The bar's own list, read from the bar's own source. Never transcribed."""
    try:
        src = open(BAR_SRC, encoding="utf-8").read()
    except OSError as e:
        print(f"FAIL: bar source unreadable at {BAR_SRC}: {e}")
        sys.exit(1)
    s = src.find("pub fn bar_for")
    e = src.find("\n}", s)
    if s < 0 or e < 0:
        print("FAIL: bar_for() not found -- the bar moved; this ratchet is stale")
        sys.exit(1)
    names = re.findall(r'contains\("([^"]+)"\)', src[s:e])
    if not names:
        print("FAIL: bar_for() matched no names -- shape changed")
        sys.exit(1)
    return names


def decision_carrying():
    """Files loaded in a hook's decision path: the shared engine + every seat's gate hook.

    Detected by ROLE, not by spelling -- a gate hook is a hook file that LOADS THE SHARED
    ENGINE, whatever its harness happens to call it. This is deliberate and is the tool's
    own thesis applied to itself: the spelling-based question ("is it called pre_tool_use.py?")
    finds 3 of the 4 seats and silently misses gemini, which is precisely the defect being
    ratcheted. The role-based question finds all 4.
    """
    out = []
    shared = os.path.join(REPO, "plugins", "_shared")
    if os.path.isdir(shared):
        for f in sorted(os.listdir(shared)):
            if f.endswith(".py") and "test" not in f and f.startswith("hestia_"):
                out.append(f"plugins/_shared/{f}")
    plugins = os.path.join(REPO, "plugins")
    for plug in sorted(os.listdir(plugins)):
        hd = os.path.join(plugins, plug, "hooks")
        if not os.path.isdir(hd):
            continue
        for f in sorted(os.listdir(hd)):
            if not f.endswith(".py") or "test" in f:
                continue
            t = open(os.path.join(hd, f), encoding="utf-8", errors="replace").read()
            if ENGINE.search(t):
                out.append(f"plugins/{plug}/hooks/{f}")
    return out


def main():
    STRONG = strong_list()
    files = decision_carrying()
    weak = [f for f in files if not any(s in f for s in STRONG)]

    print(f"bar_for() STRONG substrings ({len(STRONG)}): {STRONG}")
    print(f"decision-carrying files discovered: {len(files)}\n")
    for f in files:
        b = "SovereignPlusPeer" if any(s in f for s in STRONG) else "SingleApprover  <-- one factor"
        print(f"  {b:<34} {f}")
    print(f"\nweak: {len(weak)}   pinned: {PINNED_WEAK}")

    if len(weak) > PINNED_WEAK:
        print("\nFAIL: a decision-carrying file was born ONE-FACTOR.")
        print("A new module now decides allow/deny but is not named in bar_for(), so editing")
        print("it needs one approver instead of two. Either add it to the bar's list, or say")
        print("in the commit why one factor is right and raise PINNED_WEAK deliberately.")
        return 1
    if len(weak) < PINNED_WEAK:
        print(f"\nPASS (improved): weak count dropped to {len(weak)}. Lower PINNED_WEAK to {len(weak)}.")
        return 0
    print("\nPASS: no regression. (Still a live defect -- see")
    print("findings/the-strong-bar-prices-spelling-not-role-206-repair-closes-half-20260904.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
