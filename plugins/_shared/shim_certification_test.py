"""Structural certification of every seat shim.

A shim translates an event. It never decides how that event is governed.

`hestia_single_gate_test.py` is the behavioural half. This file is the structural half:
it proves that a seat cannot quietly grow a private classifier, scope rule, recorder, mode
switch, or alternate authority path that the behavioural corpus happens not to exercise.

Run with bare `python3`; absence/unreadability is RED, never a skip.
"""
from __future__ import annotations

import ast
import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.getenv("HGC_PLUGINS") or os.path.dirname(HERE)

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

# The function allow-list is deliberately tiny. Adapter-local pure extraction helpers are
# allowed by the mechanical rule below; they are not allowed to become another call graph.
PERMITTED_FUNCTIONS = (
    "_authority_dir",
    "_load_gate",
    "_emergency_block",
    "to_event",
    "emit",
    "read_harness_event",
    "main",
)
BOOTSTRAP = ("_authority_dir", "_load_gate", "_emergency_block")
ADAPTERS = ("to_event", "emit", "read_harness_event")

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

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))
        FAILURES.append(name)


def shim_path(seat: str) -> str:
    if os.getenv("SHIM_CERT_DEPLOYED") == "1":
        return os.path.expanduser(DEPLOYED[seat])
    return os.path.join(PLUGINS, SHIMS[seat])


def pure_adapter_helper(name: str, tree: ast.AST) -> tuple[bool, str]:
    """Permit an extra helper only when it is mechanically pure translation.

    It may be called only by adapters (or itself for recursion), and it may call only a
    small builtin/method vocabulary plus itself. It cannot call a shared gate module or
    another helper. This is what makes Gemini's recursive string extraction legitimate
    without making `helper()` a loophole through C4.
    """
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if node is None:
        return False, "not found"

    callers = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == name:
                callers.add(fn.name)
    outside = callers - set(ADAPTERS) - {name}
    if outside:
        return False, f"called from non-adapter {sorted(outside)}"

    builtins = {
        "isinstance", "len", "str", "list", "dict", "tuple", "set", "sorted",
        "int", "float", "bool", "enumerate", "range", "getattr", "reversed",
        "min", "max", "abs", "any", "all", "append", "extend", "values",
        "keys", "items", "get", "strip", "lower", "upper", "split", "join",
    }
    callees = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            fid = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if fid:
                callees.add(fid)
    impure = callees - builtins - {name}
    if impure:
        return False, f"calls {sorted(impure)}; not pure extraction"
    return True, f"pure extraction, called only from {sorted(callers - {name}) or ['(unused)']}"


def function_source(src: str, tree: ast.AST, name: str) -> str | None:
    lines = src.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def main() -> int:
    scope = "DEPLOYED" if os.getenv("SHIM_CERT_DEPLOYED") == "1" else "in-repo"
    print("shim structural certification")
    print(f"  scope: {scope}")
    print(f"  tree : {PLUGINS}\n")

    parsed = {}
    for seat in SHIMS:
        path = shim_path(seat)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            parsed[seat] = (path, src, ast.parse(src))
        except Exception as exc:
            check(f"C0 readable [{seat}]", False, f"{path}: {type(exc).__name__}: {exc}")

    if not parsed:
        print("\nFAIL - no shim could be read; certifying nothing")
        return 1

    for seat, (_path, src, tree) in sorted(parsed.items()):
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        want = set(PERMITTED_FUNCTIONS)
        extra, missing = defined - want, want - defined
        illegal = set()
        for name in sorted(extra):
            ok, why = pure_adapter_helper(name, tree)
            check(f"C4b adapter-local helper [{seat}] {name}", ok, why)
            if not ok:
                illegal.add(name)
        check(f"C4 exact function set [{seat}]", not illegal and not missing,
              f"illegal_extra={sorted(illegal)} missing={sorted(missing)}")

        hits = sorted({token for token in GOVERNANCE_VOCABULARY if token in src})
        check(f"C2 no governance vocabulary [{seat}]", not hits, f"found: {hits}")

        keys, callables = set(), []
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PROFILE":
                if isinstance(node.value, ast.Dict):
                    for key, value in zip(node.value.keys, node.value.values):
                        if isinstance(key, ast.Constant):
                            keys.add(key.value)
                        if isinstance(value, ast.Lambda):
                            callables.append(getattr(key, "value", "?"))
        unknown = sorted(keys - PERMITTED_PROFILE_KEYS)
        check(f"C3 profile is data only [{seat}]", not unknown and not callables,
              f"unknown_keys={unknown} callables={callables}")

    for fn in BOOTSTRAP:
        digests = {}
        for seat, (_path, src, tree) in sorted(parsed.items()):
            body = function_source(src, tree, fn)
            digests[seat] = hashlib.sha256(body.encode()).hexdigest() if body else "ABSENT"
        check(f"C1 bootstrap identical [{fn}]", len(set(digests.values())) == 1,
              "  ".join(f"{s}={d[:10]}" for s, d in sorted(digests.items())))

    if FAILURES:
        print(f"\nFAIL - {len(FAILURES)} of {CHECKS} checks failed")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print(f"\nOK - {CHECKS}/{CHECKS} pass; every shim translates, none decides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
