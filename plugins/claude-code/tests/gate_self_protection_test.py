#!/usr/bin/env python3
"""Every file that DECIDES policy must be inside the rule that protects the gate.

WHY THIS EXISTS
---------------
PR #169 landed `plugins/_shared/hestia_gate_core.py` — the shared policy core that was to
become the single gate for all five harnesses, with the per-harness hooks reduced to adapter
shims. The gate's self-protection rule matched hook DIRECTORIES and governance FILENAMES; the
core matched neither, so the entire PR was written with no escalation. Verified by writing it,
and disclosed in the PR rather than used.

**Consolidation is what makes this sharp.** Disarming the gate used to mean editing five files
and tripping the rule five times. Since one-gate stage C every seat's shim delegates its whole
decision to ONE file, `hestia_single_gate.py`. If that file sat outside the rule, consolidation
would have moved the whole policy surface somewhere unguarded while every per-harness
protection still read as intact. (It did, for its INSTALLED copy: before stage C a write to
`$HESTIA_HOME/shared/hestia_single_gate.py` classified "none". Stage C adds it to the floor.)

WHAT THIS ASSERTS, AND WHAT IT CANNOT
-------------------------------------
A bounded, checkable twin of the real property. The real property — "no file that can decide a
policy outcome is writable without escalation" — is a negative over an open set and no test can
assert it. The performable twin: **every `.py` under `plugins/_shared/` is either protected or
explicitly exempted with a recorded reason, and every canonical governance name is enforced.**
A green here means the enumeration has not changed since a person last looked. It is a fact
about attention, not about safety.

SCOPE — READ THIS BEFORE CITING A GREEN
---------------------------------------
Before stage C this protected only writes judged by the CLAUDE adapter: the matcher
(`_GOVERNANCE_FILES`, `_touches_self`) existed in that one gate (codex NOT-SAME review of #175,
finding 2). Since stage C there is no per-adapter matcher anywhere: the enforced rule is the
shared governance closure (`hestia_governance_closure.LITERAL_FLOOR`), applied by the common
gate on EVERY seat (claude-code, codex, kimi, gemini). What it still cannot see: a seat whose
hook is not registered, or a member that kills the hook process — this is A1, cooperative.
"""
from __future__ import annotations

import ast
import functools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("HESTIA_CONTRACT_REPO") or os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SHARED = os.path.join(REPO, "plugins", "_shared")
_OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")   # staging seam
CLOSURE = _OVERLAY.get("hestia_governance_closure") or os.path.join(SHARED, "hestia_governance_closure.py")
CORE = _OVERLAY.get("hestia_gate_core") or os.path.join(SHARED, "hestia_gate_core.py")

# Files under plugins/_shared/ that do NOT decide policy, each with the reason it is safe.
#
# THIS LEDGER IS A POLICY ARTIFACT, AND IT MUST BE PROTECTED LIKE ONE (codex NOT-SAME review
# of #175, finding 1): an actor who could add a shared decider AND exempt it here in one
# unescalated write would pass every check. `gate_self_protection_test.py` is a distinctive
# governance name in the closure floor, and `test_the_exemption_ledger_is_itself_protected`
# asserts that a write to it is refused.
EXEMPT = {
    "test_gate_core.py": "a test of the core, not a decider; editing it cannot change a verdict "
                         "reached at runtime — only whether the build notices",
    "hestia_gate_mechanism_test.py": "a test of the shared society-safety mechanism, not a decider; "
                                     "editing it cannot change a runtime verdict — only whether the "
                                     "build notices a weakened fail-closed contract",
}

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# THE FILE MUST MEAN THE SAME THING UNDER BOTH INVOCATIONS (kimi-code, verifying #175): the
# bare runner reports every failure; pytest gets the delta as an AssertionError per test.
_BARE = False


def asserting(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        before = len(FAILURES)
        result = fn(*args, **kwargs)
        new = FAILURES[before:]
        if new and not _BARE:
            raise AssertionError(f"{len(new)} check(s) failed in {fn.__name__}: {new}")
        return result
    return wrapper


def _floor():
    """`LITERAL_FLOOR`'s files_anywhere and files_hooks_only, read out of the closure's AST.

    Parsed, never imported, for the reason this file always had: an enumeration check must not
    execute the thing it audits, and must work when the module cannot run at all."""
    with open(CLOSURE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "LITERAL_FLOOR" for t in node.targets):
            out = {}
            for kw in getattr(node.value, "keywords", []):
                if kw.arg in ("files_anywhere", "files_hooks_only") and isinstance(kw.value, ast.Tuple):
                    out[kw.arg] = {e.value for e in kw.value.elts
                                   if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            return out.get("files_anywhere", set()), out.get("files_hooks_only", set())
    return set(), set()


def _governance_files():
    anywhere, hooks_only = _floor()
    return anywhere | hooks_only


def _core_governance_files():
    """The core's canonical `GOVERNANCE_FILES`, parsed."""
    with open(CORE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GOVERNANCE_FILES"
                                                for t in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                return {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _classifier():
    """The closure module, imported, so the rule can be CALLED (whether it FIRES is a different
    question from whether a name is listed, and wants the other instrument)."""
    import importlib.util
    sys.path.insert(0, SHARED)
    spec = importlib.util.spec_from_file_location("hestia_governance_closure", CLOSURE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_governance_closure"] = mod
    spec.loader.exec_module(mod)
    return mod


@asserting
def test_the_shared_core_and_the_common_gate_are_protected():
    g = _governance_files()
    check("governance_files_were_actually_parsed", len(g) >= 5,
          f"found {len(g)} — the AST read may be broken, which would make every assertion vacuous")
    for name in ("hestia_gate_core.py", "hestia_gate_mechanism.py", "hestia_single_gate.py"):
        check(f"{name}_is_protected_by_name", name in g,
              f"{name} decides for every seat; outside the floor its INSTALLED copy (not under "
              f"plugins/_shared) is writable with no escalation")


@asserting
def test_the_write_is_actually_refused():
    """kimi-code NOT-SAME review of #175, D1+D2: membership is not firing. Each payload must
    classify as a governance WRITE through the shared classifier every seat's gate calls."""
    hgc = _classifier()
    installed = "/home/member/.hestia/shared/"
    cases = [
        ("Write", {"file_path": "plugins/_shared/hestia_gate_core.py", "content": "x"},
         "the policy core, relative path"),
        ("Write", {"file_path": os.path.join(SHARED, "hestia_gate_core.py"), "content": "x"},
         "the policy core, absolute path"),
        ("Edit", {"file_path": "plugins/_shared/hestia_gate_core.py",
                  "old_string": "a", "new_string": "b"}, "the core by Edit"),
        ("Bash", {"command": "sed -i s/x/y/ plugins/_shared/hestia_gate_core.py"}, "the core by shell"),
        ("Write", {"file_path": installed + "hestia_single_gate.py", "content": "x"},
         "the INSTALLED common gate"),
        ("Write", {"file_path": installed + "hestia_gate_mechanism.py", "content": "x"},
         "the INSTALLED mechanism"),
        ("Write", {"file_path": "plugins/claude-code/tests/gate_self_protection_test.py",
                   "content": "x"}, "the EXEMPTION LEDGER"),
    ]
    for tool, payload, why in cases:
        v = hgc.classify(tool, payload, cwd=REPO)
        check(f"refused__{tool}__{why[:40]}", v.classification == "write",
              f"classified {v.classification!r}: {why} would be written with no escalation")


@asserting
def test_the_hooks_dir_qualifier_is_a_subset_of_the_governed_names():
    """The weakening list (hooks-dir-only names) must not drift from the canonical names."""
    _anywhere, hooks_only = _floor()
    canonical = _core_governance_files()
    check("hooks_dir_qualifier_is_a_subset", hooks_only <= canonical,
          f"{sorted(hooks_only - canonical)} are hooks-dir qualified but not canonical names")


@asserting
def test_every_shared_file_is_protected_or_exempted():
    """A new file under plugins/_shared/ is red until someone decides whether it decides. The
    closure protects the directory positionally; this asks it, file by file."""
    if not os.path.isdir(SHARED):
        check("shared_dir_exists", False, f"{SHARED} missing — did the layout move?")
        return
    hgc = _classifier()
    unjudged = []
    for fn in sorted(os.listdir(SHARED)):
        if not fn.endswith(".py") or fn in EXEMPT:
            continue
        v = hgc.classify("Write", {"file_path": os.path.join(SHARED, fn)})
        if v.classification != "write":
            unjudged.append(fn)
    check("every_shared_file_is_protected_or_exempted", not unjudged,
          f"{unjudged} sit under plugins/_shared/ and are neither refused by the closure nor "
          f"exempted with a reason")


@asserting
def test_the_exemption_ledger_is_itself_protected():
    me = os.path.basename(__file__)
    check("exemption_ledger_is_named", me in _governance_files() or "gate_self_protection_test.py"
          in _governance_files(), f"{me} holds EXEMPT and is not a governed name")


@asserting
def test_the_scope_of_this_protection_is_stated_honestly():
    """The docstring must say what enforces this (the common gate, on every seat) and what it
    cannot see, so a reader does not infer more than this checks."""
    doc = " ".join((sys.modules[__name__].__doc__ or "").lower().split())
    for phrase in ("common gate", "every seat", "a1"):
        check(f"scope_note_mentions_{phrase.replace(' ', '_')}", phrase in doc)


@asserting
def test_exemptions_carry_reasons():
    thin = sorted(k for k, v in EXEMPT.items() if len(v.strip()) < 20)
    check("exemptions_carry_reasons", not thin, f"exempt with no real reason: {thin}")


@asserting
def test_exemptions_are_not_stale():
    if not os.path.isdir(SHARED):
        return
    present = set(os.listdir(SHARED))
    stale = sorted(k for k in EXEMPT if k not in present)
    check("exemptions_are_not_stale", not stale, f"EXEMPT names files that are gone: {stale}")


@asserting
def test_every_canonical_name_is_enforced():
    """The consolidation drift guard, re-aimed at stage C. The core carries the CANONICAL
    `GOVERNANCE_FILES`; the enforced rule is the closure floor, which every seat's gate applies.
    The floor may be a superset (it also governs the hub's deploy surfaces), never a subset:
    a canonical name the floor does not enforce is a closure nobody applies. (The pre-C version
    pinned a per-gate fail-safe literal byte-equal to the canonical; there is no per-gate literal
    any more — a gate that cannot import the closure cannot load at all, and fails closed.)"""
    enforced = _governance_files()
    canonical = _core_governance_files()
    check("canonical_list_parsed", len(canonical) >= 5, f"found {len(canonical)}")
    check("every_canonical_name_is_enforced", canonical <= enforced,
          f"canonical names the floor does not enforce: {sorted(canonical - enforced)}")


if __name__ == "__main__":
    _BARE = True
    print("gate self-protection")
    test_the_shared_core_and_the_common_gate_are_protected()
    test_every_canonical_name_is_enforced()
    test_the_write_is_actually_refused()
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
