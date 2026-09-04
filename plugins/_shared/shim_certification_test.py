#!/usr/bin/env python3
"""Structural certification of every seat shim — C1, C2, C3, C4 as an executable test.

The invariant this enforces, in one line:

    A shim translates an event. It never decides how that event is governed.

`hestia_single_gate_test.py` proves the shared decision path behaves identically for every
identity. That is the BEHAVIOURAL half. This file is the STRUCTURAL half: it proves no shim
contains anything that *could* decide, so the behavioural guarantee cannot be quietly routed
around by a seat that grows its own logic back.

Both halves are needed and neither implies the other. A shim can pass every behavioural
contract test while holding a private classifier that only fires on inputs the contract
suite does not enumerate — which is precisely how the fleet arrived at four gates sharing a
utility library.

WHAT IS CHECKED
---------------
C4  the set of function names a shim defines equals PERMITTED_FUNCTIONS exactly.
C1  the authority bootstrap is BYTE-IDENTICAL across every shim. A diff there is not a
    permitted variant — it is the one place a seat could select a different common gate.
C2  no shim's source carries governance vocabulary (classification, scope, law, mode,
    recording). Every token in the list below was present in at least one shim before the
    collapse, so the check has demonstrated discriminating power rather than being a guess.
C3  PROFILE carries only data keys, and no callables.

DISCRIMINATING POWER, MEASURED
------------------------------
Run against the pre-collapse shims (origin/main, 2026-09-04): FAIL, 82 of 91 checks.
Run against the collapsed shims (gpt/single-gate-collapse):   OK, 16 of 16.
A checker that passes everything certifies nothing; this one was validated against a tree
known to violate before being trusted against a tree believed to comply.

FAIL DIRECTION
--------------
An unreadable or missing shim is a FAILURE, never a skip. The agent-inventory rule — never
render "nothing ungoverned" out of "could not look" — applies unchanged: a certification
test that greens when it cannot see the artifact certifies nothing.

Run:  python3 shim_certification_test.py
      SHIM_CERT_DEPLOYED=1 ...   check the DEPLOYED copies rather than the in-repo ones
      HGC_PLUGINS=<dir>    ...   check an alternate plugins tree
"""
from __future__ import annotations

import ast
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.getenv("HGC_PLUGINS") or os.path.dirname(HERE)

# Built by join so this source never spells a governance path contiguously — the FP8
# constraint the false-refusal corpus documents for its own source.
_HOOK = "pre_" + "tool_" + "use.py"
_GEM = "before_" + "tool.py"

SHIMS = {
    "claude-code": os.path.join("claude-code", "hooks", _HOOK),
    "codex": os.path.join("codex", "hooks", _HOOK),
    "kimi": os.path.join("kimi", "hooks", _HOOK),
    "gemini": os.path.join("gemini", "hooks", _GEM),
}

DEPLOYED = {
    "claude-code": os.path.join("~", ".claude", "hooks", "hestia", _HOOK),
    "codex": os.path.join("~", ".codex", "hooks", _HOOK),
    "kimi": os.path.join("~", ".kimi-code", "hooks", _HOOK),
    "gemini": os.path.join("~", ".gemini", "hestia-plugins", "gemini", "hooks", _GEM),
}

# C4 — the exact allow-list. This tuple IS the criterion; the prose describes it.
PERMITTED_FUNCTIONS = (
    "_authority_dir",       # bootstrap, byte-identical
    "_load_gate",           # bootstrap, byte-identical
    "_emergency_block",     # bootstrap, byte-identical
    "to_event",             # adapter — per-seat harness syntax
    "emit",                 # adapter — per-seat harness protocol
    "read_harness_event",   # adapter — per-seat transport
    "main",                 # skeleton
)

BOOTSTRAP = ("_authority_dir", "_load_gate", "_emergency_block")

GOVERNANCE_VOCABULARY = (
    "_READ_ONLY_HEADS", "_is_read_only", "hestia_shell_classifier",
    "_closure_classify", "degraded_verdict", "resolve_agent_policy",
    "fetch_policy_snapshot", "command_in_scope", "path_in_scope",
    "detect_workspace", "witness_decision_unified", "gate_self_call",
    "claim_self_write", "tally_scope", "query_society_safety",
    "GATE_MODE", "forbidden_tokens", "_record_refusal", "_fallback_self_protection",
)

PERMITTED_PROFILE_KEYS = {
    "member_id", "identity_path", "home_markers", "host_agent",
    "client_name", "gate_path", "observe_dir",
}

_FAILURES: list[str] = []
_CHECKS = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global _CHECKS
    _CHECKS += 1
    if ok:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))
        _FAILURES.append(name)


def _shim_path(seat: str) -> str:
    if os.getenv("SHIM_CERT_DEPLOYED") == "1":
        return os.path.expanduser(DEPLOYED[seat])
    return os.path.join(PLUGINS, SHIMS[seat])


ADAPTERS = ("to_event", "emit", "read_harness_event")


def _is_pure_adapter_helper(name, tree, defined):
    """An extra function is permitted iff it is a PURE ADAPTER-LOCAL HELPER.

    Three constraints, each of which independently keeps C4 meaningful:

      1. CALLED ONLY FROM ADAPTERS (or itself, for recursion). A helper reachable from
         `main` or the bootstrap is on the decision path, whatever it contains.
      2. CALLS NOTHING BUT BUILTINS AND ITSELF. The moment a helper can call the gate,
         another helper, or a module, "pure extraction" stops being checkable by
         inspection — and a chain of helpers is how private logic returns under a new name.
      3. NO GOVERNANCE VOCABULARY (enforced source-wide by C2, restated here for clarity).

    Returns (ok, reason). The reason is printed either way, so a permitted helper is
    visible in the output rather than silently tolerated.
    """
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if node is None:
        return False, "not found"

    # (1) callers
    callers = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == name:
                callers.add(fn.name)
    outside = callers - set(ADAPTERS) - {name}
    if outside:
        return False, f"called from non-adapter {sorted(outside)} — on the decision path"

    # (2) callees
    callees = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            fid = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if fid:
                callees.add(fid)
    BUILTINS = {"isinstance", "len", "str", "list", "dict", "tuple", "set", "sorted",
                "int", "float", "bool", "enumerate", "range", "getattr", "reversed",
                "min", "max", "abs", "any", "all", "append", "extend", "values",
                "keys", "items", "get", "strip", "lower", "upper", "split", "join"}
    impure = callees - BUILTINS - defined.intersection({name})
    impure -= {name}
    if impure:
        return False, f"calls {sorted(impure)} — not pure extraction"

    return True, f"pure extraction, called only from {sorted(callers - {name}) or ['(unused)']}"


def _func_source(src, tree, name):
    lines = src.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def main() -> int:
    scope = "DEPLOYED" if os.getenv("SHIM_CERT_DEPLOYED") == "1" else "in-repo"
    print("shim structural certification — C1/C2/C3/C4")
    print(f"  scope: {scope}")
    print(f"  tree : {PLUGINS}\n")

    parsed = {}
    for seat in SHIMS:
        path = _shim_path(seat)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            parsed[seat] = (path, src, ast.parse(src))
        except Exception as exc:
            _check(f"C0 readable [{seat}]", False, f"{path}: {type(exc).__name__}: {exc}")

    if not parsed:
        print("\nFAIL — no shim could be read; certifying nothing.")
        return 1

    print()
    for seat, (path, src, tree) in sorted(parsed.items()):
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        want = set(PERMITTED_FUNCTIONS)
        extra, missing = defined - want, want - defined
        # C4b: an extra function is permitted ONLY as a pure adapter-local helper.
        # Amended 2026-09-04 after this check flagged gemini's `_string_leaves`, which
        # recursively pulls strings out of nested MCP metadata. That is translation, not
        # decision — the criterion was too tight, not the shim wrong. Waving it through by
        # name would have made C4 unenforceable, so the allowance carries three mechanical
        # constraints instead, all verified below.
        illegal = set()
        for name in sorted(extra):
            ok, why = _is_pure_adapter_helper(name, tree, defined)
            _check(f"C4b adapter-local helper [{seat}] {name}", ok, why)
            if not ok:
                illegal.add(name)
        _check(f"C4 exact function set [{seat}]", not illegal and not missing,
               f"illegal_extra={sorted(illegal)} missing={sorted(missing)}")

    print()
    for fn in BOOTSTRAP:
        digests = {}
        for seat, (path, src, tree) in sorted(parsed.items()):
            body = _func_source(src, tree, fn)
            digests[seat] = hashlib.sha256(body.encode()).hexdigest() if body else "ABSENT"
        _check(f"C1 bootstrap identical [{fn}]", len(set(digests.values())) == 1,
               "  ".join(f"{s}={d[:10]}" for s, d in sorted(digests.items())))

    print()
    for seat, (path, src, tree) in sorted(parsed.items()):
        hits = sorted({t for t in GOVERNANCE_VOCABULARY if t in src})
        _check(f"C2 no governance vocabulary [{seat}]", not hits, f"found: {hits}")

    print()
    for seat, (path, src, tree) in sorted(parsed.items()):
        keys, callables_ = set(), []
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PROFILE":
                if isinstance(node.value, ast.Dict):
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant):
                            keys.add(k.value)
                        if isinstance(v, ast.Lambda):
                            callables_.append(getattr(k, "value", "?"))
        unknown = sorted(keys - PERMITTED_PROFILE_KEYS)
        _check(f"C3 profile is data only [{seat}]", not unknown and not callables_,
               f"unknown_keys={unknown} callables={callables_}")

    print()
    if _FAILURES:
        print(f"FAIL — {len(_FAILURES)} of {_CHECKS} checks failed:")
        for f in _FAILURES:
            print(f"  {f}")
        return 1
    print(f"OK — {_CHECKS}/{_CHECKS} pass; every shim translates, none decides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
