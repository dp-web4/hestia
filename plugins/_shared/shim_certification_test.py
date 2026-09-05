"""Structural certification of every seat shim.

Behavioural tests prove the common decision path. This file proves a shim cannot grow a
second decision path that the behavioural corpus does not enumerate.

The reference template is the source of truth for the function/profile allow-list and the
byte-identical bootstrap/main bodies. The checker does not restate those lists.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGINS = Path(os.getenv("HGC_PLUGINS") or HERE.parent)
TEMPLATE = PLUGINS / "_template" / "shim_template.py"

_HOOK = "pre_" + "tool_" + "use.py"
_GEM = "before_" + "tool.py"
SHIMS = {
    "claude-code": Path("claude-code") / "hooks" / _HOOK,
    "codex": Path("codex") / "hooks" / _HOOK,
    "kimi": Path("kimi") / "hooks" / _HOOK,
    "gemini": Path("gemini") / "hooks" / _GEM,
}
DEPLOYED = {
    "claude-code": Path("~/.claude/hooks/hestia") / _HOOK,
    "codex": Path("~/.codex/hooks") / _HOOK,
    "kimi": Path("~/.kimi-code/hooks") / _HOOK,
    "gemini": Path("~/.gemini/hestia-plugins/gemini/hooks") / _GEM,
}

GOVERNANCE_VOCABULARY = (
    "_READ_ONLY_HEADS", "_is_read_only", "hestia_shell_classifier",
    "_closure_classify", "degraded_verdict", "resolve_agent_policy",
    "fetch_policy_snapshot", "command_in_scope", "path_in_scope",
    "detect_workspace", "witness_decision_unified", "gate_self_call",
    "claim_self_write", "tally_scope", "query_society_safety",
    "GATE_MODE", "mode_env", "forbidden_tokens", "_record_refusal",
    "_fallback_self_protection", "HESTIA_SHARED_DIR", "HESTIA_GATE_TEST_MODE",
    "HESTIA_PRE_TOTAL_BUDGET_MS", "HESTIA_PRE_REQUEST_TIMEOUT_S",
)

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


def read_parse(path: Path):
    src = path.read_text(encoding="utf-8")
    return src, ast.parse(src)


def literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if getattr(node.targets[0], "id", None) == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"template is missing literal assignment {name}")


def function_source(src: str, tree: ast.AST, name: str) -> str | None:
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def pure_adapter_helper(name: str, tree: ast.AST, adapters: set[str]) -> tuple[bool, str]:
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if node is None:
        return False, "not found"

    callers = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == name:
                callers.add(fn.name)
    outside = callers - adapters - {name}
    if outside:
        return False, f"called from non-adapter {sorted(outside)}"

    permitted_calls = {
        "isinstance", "len", "str", "list", "dict", "tuple", "set", "sorted",
        "int", "float", "bool", "enumerate", "range", "getattr", "reversed",
        "min", "max", "abs", "any", "all", "append", "extend", "values",
        "keys", "items", "get", "strip", "lower", "upper", "split", "join",
    }
    callees = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            ident = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if ident:
                callees.add(ident)
    impure = callees - permitted_calls - {name}
    if impure:
        return False, f"calls {sorted(impure)}; not pure extraction"
    return True, f"pure adapter helper; callers={sorted(callers - {name}) or ['(unused)']}"


def profile_value_is_data(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(profile_value_is_data(x) for x in node.elts)
    if isinstance(node, ast.Call):
        # A READ of the projected environment is data: `os.environ.get("<KEY>")` with exactly
        # one constant argument. A second argument is a default, and a default is a hardcoded
        # path -- the #943 class -- so the two-argument form is refused here, by the
        # certifier, not merely by review (dp ruling 2026-09-05: env vars except where
        # absolutely unavoidable; the one unavoidable value is HESTIA_HOME, which no profile
        # reads).
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"):
            return (len(node.args) == 1 and not node.keywords
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str))
        # Only deterministic path rendering belongs in profile construction.
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("expanduser", "abspath"):
            root = node.func.value
            if isinstance(root, ast.Attribute) and isinstance(root.value, ast.Name):
                if root.value.id == "os" and root.attr == "path":
                    return all(
                        isinstance(arg, ast.Constant) or
                        (isinstance(arg, ast.Name) and arg.id == "__file__")
                        for arg in node.args
                    )
    return False


def shim_path(seat: str) -> Path:
    if os.getenv("SHIM_CERT_DEPLOYED") == "1":
        return Path(os.path.expanduser(str(DEPLOYED[seat])))
    return PLUGINS / SHIMS[seat]


def main() -> int:
    try:
        template_src, template_tree = read_parse(TEMPLATE)
        permitted = tuple(literal_assignment(template_tree, "PERMITTED_FUNCTIONS"))
        identical = tuple(literal_assignment(template_tree, "BYTE_IDENTICAL_FUNCTIONS"))
        adapters = set(literal_assignment(template_tree, "ADAPTER_FUNCTIONS"))
        profile_keys = set(literal_assignment(template_tree, "PERMITTED_PROFILE_KEYS"))
        template_constants = {
            name: literal_assignment(template_tree, name)
            for name in ("SHIM_CERTIFICATION_SCHEMA", "CERTIFICATION_CRITERIA", "REQUIRED_GATE_API")
        }
    except Exception as exc:
        print(f"FAIL - certification template unreadable/invalid: {type(exc).__name__}: {exc}")
        return 1

    parsed = {}
    for seat in SHIMS:
        path = shim_path(seat)
        try:
            parsed[seat] = (path, *read_parse(path))
        except Exception as exc:
            check(f"C0 readable [{seat}]", False, f"{path}: {type(exc).__name__}: {exc}")

    if not parsed:
        print("FAIL - no shim could be read; certifying nothing")
        return 1

    want = set(permitted)
    for seat, (_path, src, tree) in sorted(parsed.items()):
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        extra, missing = defined - want, want - defined
        illegal = set()
        for name in sorted(extra):
            ok, why = pure_adapter_helper(name, tree, adapters)
            check(f"C4b adapter-local helper [{seat}] {name}", ok, why)
            if not ok:
                illegal.add(name)
        check(f"C4 function surface [{seat}]", not illegal and not missing,
              f"illegal_extra={sorted(illegal)} missing={sorted(missing)}")

        hits = sorted({token for token in GOVERNANCE_VOCABULARY if token in src})
        check(f"C2 no private governance/authority knobs [{seat}]", not hits,
              f"found={hits}")

        assignments = {
            getattr(node.targets[0], "id", None): node.value
            for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
        }
        for name, expected in template_constants.items():
            try:
                actual = ast.literal_eval(assignments[name])
            except Exception:
                actual = object()
            check(f"C9 certification constant [{seat}] {name}", actual == expected,
                  f"actual={actual!r} expected={expected!r}")

        profile = assignments.get("PROFILE")
        keys, bad_values = set(), []
        if isinstance(profile, ast.Dict):
            for key, value in zip(profile.keys, profile.values):
                if isinstance(key, ast.Constant):
                    keys.add(key.value)
                    if not profile_value_is_data(value):
                        bad_values.append(key.value)
        else:
            bad_values.append("PROFILE-not-dict")
        check(f"C3 profile is data only [{seat}]",
              keys <= profile_keys and not bad_values,
              f"unknown_keys={sorted(keys-profile_keys)} bad_values={bad_values}")

    # The bootstrap and main do not merely agree with one another; they agree with the
    # generic template. That makes the template an executable contract rather than prose.
    for fn in identical:
        template_body = function_source(template_src, template_tree, fn)
        expected = hashlib.sha256((template_body or "").encode()).hexdigest()
        for seat, (_path, src, tree) in sorted(parsed.items()):
            body = function_source(src, tree, fn)
            actual = hashlib.sha256((body or "").encode()).hexdigest()
            check(f"C1 template-identical [{seat}] {fn}", actual == expected,
                  f"got={actual[:12]} want={expected[:12]}")

    if FAILURES:
        print(f"\nFAIL - {len(FAILURES)} of {CHECKS} checks failed")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print(f"\nOK - {CHECKS}/{CHECKS} pass; every shim translates, none decides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
