#!/usr/bin/env python3
"""Every file that DECIDES policy must be inside the rule that protects the gate.

WHY THIS EXISTS
---------------
PR #169 landed `plugins/_shared/hestia_gate_core.py` — the shared policy core that is to
become the single gate for all five harnesses, with the per-harness hooks reduced to adapter
shims. The gate's self-protection rule matches two hook DIRECTORIES (`_SELF_MARKERS`) and
five FILENAMES (`_GOVERNANCE_FILES`). The core matched neither, so the entire PR was written
with no escalation. Verified by writing it, and disclosed in the PR rather than used.

**Consolidation is what makes this sharp.** Today, disarming the gate means editing five
files and tripping the rule five times. After the shims land it means editing ONE file. If
that file sits outside the rule, consolidation moves the whole policy surface somewhere
unguarded while every per-harness protection still reads as intact — the rule staying green
about five shims that no longer decide anything. A protection that is true of the parts and
false of the whole is the same shape as a receipt naming a filename rather than the object
accepted, or a queue naming submission existence rather than applicability.

WHAT THIS ASSERTS, AND WHAT IT CANNOT
-------------------------------------
It asserts a bounded, checkable twin of the real property. The real property — "no file that
can decide a policy outcome is writable without escalation" — is a negative over an open set
and no test can assert it. The performable twin: **every `.py` under `plugins/_shared/` is
either protected by name or explicitly exempted with a recorded reason.** A new file there
goes red on the author, at write time, which is the only moment anyone holds the context to
answer "does this decide anything?"

Same instrument class as `core/tests/member_presence_census.rs`, and the same caveat: a green
here means the enumeration has not changed since a person last looked. It is a fact about
attention, not about safety.
"""
from __future__ import annotations

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
HOOK = os.path.join(REPO, "plugins", "claude-code", "hooks", "pre_tool_use.py")
SHARED = os.path.join(REPO, "plugins", "_shared")

# Files under plugins/_shared/ that do NOT decide policy, each with the reason it is safe.
# Adding a name here is a judgement someone made; it should be as hard to add as it is to
# add a rule, which is why it lives in the test rather than in a glob.
EXEMPT = {
    "test_gate_core.py": "a test of the core, not a decider; editing it cannot change a verdict "
                         "reached at runtime — only whether the build notices",
}
# `__init__.py` was in this list on the first draft, speculatively, for a file that does not
# exist. `exemptions_are_not_stale` caught it on the very first run — against its own author,
# which is the only real evidence an instrument works. Removed rather than creating the file
# to match the list: an exemption for a hypothetical file is a claim nobody checked.

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def _governance_files():
    """Read `_GOVERNANCE_FILES` out of the hook's AST.

    Parsed, never imported: importing the gate runs its module body, and a test that executes
    the thing it audits can be fooled by the thing it audits. Also means this test works when
    the hook cannot run at all."""
    with open(HOOK, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "_GOVERNANCE_FILES":
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    return {e.value for e in node.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def test_the_shared_core_is_protected():
    """The specific regression. `hestia_gate_core.py` must be named in the rule."""
    g = _governance_files()
    check("governance_files_were_actually_parsed", len(g) >= 5,
          f"found {len(g)} entries — the AST read may be broken, which would make every "
          f"assertion below silently vacuous")
    check("shared_core_is_protected", "hestia_gate_core.py" in g,
          "plugins/_shared/hestia_gate_core.py is the policy core for all five harnesses. "
          "Outside _GOVERNANCE_FILES it is writable with no escalation, and after the shims "
          "land it is the ONLY file an attacker needs.")


def test_every_shared_file_is_protected_or_exempted():
    """The scheduled judgement. A new file under plugins/_shared/ is red until someone
    decides whether it decides."""
    if not os.path.isdir(SHARED):
        check("shared_dir_exists", False, f"{SHARED} missing — did the layout move?")
        return
    g = _governance_files()
    unjudged = []
    for fn in sorted(os.listdir(SHARED)):
        if not fn.endswith(".py"):
            continue
        if fn in g or fn in EXEMPT:
            continue
        unjudged.append(fn)
    check("every_shared_file_is_protected_or_exempted", not unjudged,
          f"{unjudged} sit under plugins/_shared/ and are neither protected by name nor "
          f"exempted. Decide: does this file participate in reaching a verdict? If yes, add "
          f"it to _GOVERNANCE_FILES (a governance-surface edit, so escalate). If no, add it "
          f"to EXEMPT here WITH the reason.")


def test_exemptions_carry_reasons():
    """An exemption without a stated reason is indistinguishable from an oversight."""
    thin = sorted(k for k, v in EXEMPT.items() if len(v.strip()) < 20)
    check("exemptions_carry_reasons", not thin, f"exempt with no real reason: {thin}")


def test_exemptions_are_not_stale():
    """An exemption naming a file that no longer exists is dead weight that makes the list
    look more considered than it is."""
    if not os.path.isdir(SHARED):
        return
    present = set(os.listdir(SHARED))
    stale = sorted(k for k in EXEMPT if k not in present)
    check("exemptions_are_not_stale", not stale,
          f"EXEMPT names files that are gone: {stale}")


if __name__ == "__main__":
    print("gate self-protection")
    test_the_shared_core_is_protected()
    test_every_shared_file_is_protected_or_exempted()
    test_exemptions_carry_reasons()
    test_exemptions_are_not_stale()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print("all checks pass")
