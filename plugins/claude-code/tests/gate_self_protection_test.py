#!/usr/bin/env python3
"""Every file that DECIDES policy must be inside the rule that protects the gate.

WHY THIS EXISTS
---------------
PR #169 landed `plugins/_shared/hestia_gate_core.py` — the shared policy core that is to
become the single gate for all five harnesses, with the per-harness hooks reduced to adapter
shims. The gate's self-protection rule matches hook DIRECTORIES plus the installer paths
that overwrite them (`_SELF_MARKERS`) and the governance FILENAMES (`_GOVERNANCE_FILES`).
The core matched neither, so the entire PR was written
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

SCOPE — READ THIS BEFORE CITING A GREEN
---------------------------------------
**This protects against writes judged by the CLAUDE adapter, and only that adapter.** (codex
NOT-SAME review of #175, finding 2.) `_SELF_MARKERS` and `_GOVERNANCE_FILES` exist in exactly
one gate in the tree. kimi, codex, gemini and cursor run scope and egress checks and have **no
self-protection mechanism at all**, so there is nothing to extend this list into — and adding
one per adapter would be a fifth copy of the thing the shared core exists to eliminate.

So a member on another harness can write `hestia_gate_core.py` today and this test will still
be green, because it is green about the Claude adapter's rule and says nothing about theirs.
The gap is real, permanent until the shims land, and stated here rather than left for a reader
to infer coverage this file does not have.
"""
from __future__ import annotations

import ast
import functools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
HOOK = os.path.join(REPO, "plugins", "claude-code", "hooks", "pre_tool_use.py")
SHARED = os.path.join(REPO, "plugins", "_shared")
# The seat resolves shared law ONLY from an explicit HESTIA_SHARED_DIR or the installed
# engine (#747); the tree is no longer an implicit fallback. This names the reviewed tree
# under test explicitly: a fixture, chosen and visible, not an authority fallback.
os.environ.setdefault("HESTIA_SHARED_DIR", SHARED)

# Files under plugins/_shared/ that do NOT decide policy, each with the reason it is safe.
#
# THIS LEDGER IS A POLICY ARTIFACT, AND IT MUST BE PROTECTED LIKE ONE (codex NOT-SAME review
# of #175, finding 1). The first version said adding a name here "should be as hard to add as
# it is to add a rule" — and it was not. This file sat outside `_GOVERNANCE_FILES` and outside
# the hook-directory markers, so an actor could add a new shared decider AND exempt it here,
# in one unescalated write, and the guard would pass. The claim was aspirational and the code
# contradicted it, which is worse than not making the claim: a reader trusts the sentence.
#
# `gate_self_protection_test.py` is now in `_GOVERNANCE_FILES`, and
# `test_the_exemption_ledger_is_itself_protected` below asserts it stays there. Editing this
# list is now a governed write, which is what the sentence always said it was.
EXEMPT = {
    "test_gate_core.py": "a test of the core, not a decider; editing it cannot change a verdict "
                         "reached at runtime — only whether the build notices",
    "hestia_gate_mechanism_test.py": "a test of the shared society-safety mechanism, not a decider; "
                                     "editing it cannot change a runtime verdict — only whether the "
                                     "build notices a weakened fail-closed contract",
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


# THE FILE MUST MEAN THE SAME THING UNDER BOTH INVOCATIONS (kimi-code, verifying #175 at
# 6220e75). `check()` only records; `FAILURES` was read only by the `__main__` block below.
# CI runs discovered tests bare (`tools/ci_discovery.py bare` -> `python3 "$t"`), so the exit
# code held — but under `python3 -m pytest`, the invocation a file named `*_test.py` invites,
# every `test_*` returned normally and pytest reported 8 PASSED while five checks FAILED. A
# green identical to the null state, guarding the PR whose own subject is a green identical to
# the null state. kimi almost sent a "cannot reproduce" on the strength of it.
#
# `check()` deliberately stays non-raising: the bare run's job is to report EVERY failure, not
# to stop at the first, and that property is why the five-row table above is readable at all.
# So the raise lives at the test-function boundary instead, and only for callers that are not
# the bare runner — pytest gets the delta as an AssertionError, `__main__` gets it as exit 1.
_BARE = False


def asserting(fn):
    """Re-raise a test function's newly recorded failures for a harness that reads exceptions.

    Snapshot-and-delta rather than `if FAILURES:` — with the latter, one early red would make
    every later test fail too, and a run where four of five tests are red-by-contagion cannot
    be read against the five-row table this PR exists to publish.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        before = len(FAILURES)
        result = fn(*args, **kwargs)
        new = FAILURES[before:]
        if new and not _BARE:
            raise AssertionError(
                f"{len(new)} check(s) failed in {fn.__name__}: {new}. "
                f"Run `python3 {os.path.relpath(__file__, REPO)}` from the repo root for the "
                f"full detail lines — that is how CI invokes it.")
        return result
    return wrapper


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


@asserting
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


def _load_hook():
    """Load the hook as a module so its matcher can be CALLED.

    The AST reader above is deliberate and stays: an enumeration assertion must not execute
    the thing it audits. But the assertion below is about whether the rule FIRES, and there
    is no way to observe a guard firing without running it. The two are different questions
    and want different instruments — the mistake this file shipped with was answering the
    second question with the first one's tool.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_gate_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@asserting
def test_the_shared_core_write_is_actually_refused():
    """kimi-code NOT-SAME review of #175, D1+D2. The regression the membership test cannot see.

    `test_the_shared_core_is_protected` asserts membership in a tuple. That passed while the
    rule could not fire at the protected file, because `_touches_self` gates the filename loop
    behind `if "hooks/" in low or "/hooks" in low` — and `plugins/_shared/hestia_gate_core.py`
    carries no `hooks` segment. A green identical to the null state, guarding the exact
    consolidation the file's own docstring calls the sharp case.

    So: assert the executable property. Each payload below must return a marker, not None.
    """
    mod = _load_hook()
    touches = mod._touches_self
    cases = [
        ("Write", {"file_path": "plugins/_shared/hestia_gate_core.py", "content": "x"},
         "the canonical policy core, written by relative path"),
        ("Write", {"file_path": os.path.join(SHARED, "hestia_gate_core.py"), "content": "x"},
         "the canonical policy core, written by absolute path"),
        ("Edit", {"file_path": "plugins/_shared/hestia_gate_core.py",
                  "old_string": "a", "new_string": "b"},
         "the same file reached by Edit rather than Write"),
        ("Bash", {"command": "sed -i s/x/y/ plugins/_shared/hestia_gate_core.py"},
         "the same file reached through the shell"),
        ("Write", {"file_path": "plugins/claude-code/tests/gate_self_protection_test.py",
                   "content": "x"},
         "the EXEMPTION LEDGER — in _GOVERNANCE_FILES, but tests/ has no hooks segment "
         "either, so the ledger protecting the guard was itself unguarded"),
    ]
    for tool, payload, why in cases:
        marker = touches(tool, payload)
        check(f"refused__{tool}__{why[:40]}", marker is not None,
              f"_touches_self returned None. {why}. The write proceeds with no escalation "
              f"and no gate_self_access witness.")


@asserting
def test_the_hooks_dir_qualifier_is_a_subset_of_the_governed_names():
    """The weakening list must not drift away from the list it weakens.

    `_HOOKS_DIR_ONLY` names the governance filenames common enough that matching them
    anywhere would fire on ordinary work. A name there that is NOT in `_GOVERNANCE_FILES`
    weakens nothing and reads as if it did — and the default for a newly governed name is
    the STRONG behaviour, so weakening always costs a second, visible edit."""
    mod = _load_hook()
    weak = set(getattr(mod, "_HOOKS_DIR_ONLY", ()))
    g = _governance_files()
    check("hooks_dir_qualifier_is_a_subset", weak <= g,
          f"{sorted(weak - g)} are qualified by hooks-dir but are not governed names at all")


@asserting
def test_every_shared_file_is_protected_or_exempted():
    """The scheduled judgement. A new file under plugins/_shared/ is red until someone
    decides whether it decides."""
    if not os.path.isdir(SHARED):
        check("shared_dir_exists", False, f"{SHARED} missing — did the layout move?")
        return
    g = _governance_files()
    # ARCHITECTURE MIGRATION (gate-consolidation train): protection is no longer a
    # per-name tuple — the closure CLASSIFIER protects plugins/_shared POSITIONALLY
    # (its dir marker makes any write there a governance write, including files that
    # did not exist when any tuple was written). The judgement this test schedules is
    # now: does the classifier actually refuse a write to this file? Name-tuple
    # membership remains meaningful only for the Tier-2 fallback layer. If the
    # classifier cannot be imported or does not refuse, the file is red — an
    # instrument that cannot verify must not report protected.
    sys.path.insert(0, SHARED)
    try:
        import hestia_governance_closure as _hgc
    except Exception:
        _hgc = None
    unjudged = []
    for fn in sorted(os.listdir(SHARED)):
        if not fn.endswith(".py"):
            continue
        if fn in g or fn in EXEMPT:
            continue
        v = (_hgc.classify("Write", {"file_path": os.path.join(SHARED, fn)})
             if _hgc is not None else None)
        if v is not None and v.classification == "write":
            continue  # positionally protected by the canonical closure
        unjudged.append(fn)
    check("every_shared_file_is_protected_or_exempted", not unjudged,
          f"{unjudged} sit under plugins/_shared/ and are neither refused by the closure "
          f"classifier, protected by name, nor exempted. Decide: does this file participate "
          f"in reaching a verdict? If the classifier should refuse it, fix the closure; "
          f"legacy-tuple membership (escalated edit) or EXEMPT-with-reason remain the "
          f"fallback-layer options.")


@asserting
def test_the_exemption_ledger_is_itself_protected():
    """codex #175 finding 1. A ledger that decides what escapes the guard is a policy
    artifact, and an unprotected one is a bypass with paperwork.

    Without this, the attack is one write: add `decider.py` to `plugins/_shared/`, add
    `"decider.py": "not a decider, honest"` to EXEMPT, and every check here passes."""
    g = _governance_files()
    me = os.path.basename(__file__)
    check("exemption_ledger_is_protected", me in g,
          f"{me} holds EXEMPT, which decides what escapes this guard, and is not in "
          f"_GOVERNANCE_FILES. An actor could add a shared decider and exempt it in the same "
          f"unescalated write.")


@asserting
def test_the_scope_of_this_protection_is_stated_honestly():
    """codex #175 finding 2. This protects against writes judged by the CLAUDE adapter only.

    `_SELF_MARKERS` / `_GOVERNANCE_FILES` exist in exactly one gate. kimi, codex, gemini and
    cursor have scope and egress checks but no self-protection mechanism at all, so there is
    nothing to extend the list into — and inventing one per adapter is precisely the
    five-copies problem the shared core exists to end.

    The limitation is therefore real and permanent until the shims land, and the honest
    response is to SAY so rather than let the PR read as universal protection. This test
    exists so the claim cannot quietly drift back to 'protected' — it asserts the docs still
    admit the gap."""
    doc = sys.modules[__name__].__doc__ or ""
    for phrase in ("claude", "adapter"):
        check(f"scope_note_mentions_{phrase}", phrase in doc.lower(),
              "the module docstring must state that this protection is enforced only by the "
              "Claude adapter, so a reader does not infer fleet-wide coverage")


@asserting
def test_exemptions_carry_reasons():
    """An exemption without a stated reason is indistinguishable from an oversight."""
    thin = sorted(k for k, v in EXEMPT.items() if len(v.strip()) < 20)
    check("exemptions_carry_reasons", not thin, f"exempt with no real reason: {thin}")


@asserting
def test_exemptions_are_not_stale():
    """An exemption naming a file that no longer exists is dead weight that makes the list
    look more considered than it is."""
    if not os.path.isdir(SHARED):
        return
    present = set(os.listdir(SHARED))
    stale = sorted(k for k in EXEMPT if k not in present)
    check("exemptions_are_not_stale", not stale,
          f"EXEMPT names files that are gone: {stale}")


def _core_governance_files():
    """Read `GOVERNANCE_FILES` out of the shared core's AST — parsed, not imported, for the
    same reason as `_governance_files()`: a self-protection check must not execute the code it
    audits, and this must work when the core cannot run at all."""
    core = os.path.join(SHARED, "hestia_gate_core.py")
    with open(core, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "GOVERNANCE_FILES":
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    return {e.value for e in node.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


@asserting
def test_the_enforced_list_matches_the_canonical():
    """The consolidation drift guard (step B, PR-1). The core now carries the CANONICAL
    `GOVERNANCE_FILES`; each enforcing gate keeps its own fail-safe literal — the list must NOT
    become import-only, because an import failure would run the self-access check against an
    empty list and, since engines fail OPEN on a hook crash, silently disarm the gate. So the
    canonical and the enforced copy are pinned byte-equal here; if they drift, one gate enforces
    a different closure than the ratified one — the exact failure the shared core exists to
    prevent, at the one place fail-safety forbids collapsing to a single copy."""
    enforced = _governance_files()        # the hook's own literal (AST)
    canonical = _core_governance_files()  # the core's canonical (AST)
    check("canonical_list_parsed", len(canonical) >= 5,
          f"found {len(canonical)} in the core's GOVERNANCE_FILES — the AST read may be broken, "
          f"which would make this assertion silently vacuous")
    check("enforced_matches_canonical", enforced == canonical,
          f"the hook's _GOVERNANCE_FILES and the core's GOVERNANCE_FILES have DRIFTED: "
          f"only-in-hook={sorted(enforced - canonical)}, only-in-core={sorted(canonical - enforced)}. "
          f"A gate enforcing a different closure than the canonical is the consolidation failure.")


if __name__ == "__main__":
    # The bare runner reads FAILURES itself and wants the whole table, so switch `asserting`
    # off. This assignment is the ONLY difference between the two invocations, and it changes
    # how failures are DELIVERED, never whether they are detected.
    _BARE = True
    print("gate self-protection")
    test_the_shared_core_is_protected()
    test_the_enforced_list_matches_the_canonical()
    test_the_shared_core_write_is_actually_refused()
    test_the_hooks_dir_qualifier_is_a_subset_of_the_governed_names()
    test_the_exemption_ledger_is_itself_protected()
    test_the_scope_of_this_protection_is_stated_honestly()
    test_every_shared_file_is_protected_or_exempted()
    test_exemptions_carry_reasons()
    test_exemptions_are_not_stale()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print("all checks pass")
