#!/usr/bin/env python3
"""Structural certification of every seat shim against the certified template.

One-gate stage C. Behavioural tests (seat_gate_boundary_test, the decide() contract suite and
its parity matrix) prove what the common gate decides. This file proves a shim cannot grow a
second decision path the behavioural corpus does not enumerate (PRD_SHIM_CERTIFICATION C1-C4,
C9), harvested from #934's structural checker:

  C4  the shim defines EXACTLY the template's PERMITTED_FUNCTIONS — no extra, none missing;
  C1  the five bootstrap/main functions are byte-identical to the TEMPLATE's (so the template
      is an executable contract, not prose);
  C2  no private governance or authority knob appears in the shim (a per-seat rollout name, a
      mechanism or core import, a recorder, a budget override, a spawned governor);
  C3  PROFILE and HARNESS are DATA: only permitted keys, values that are literals or a single
      one-argument read of the projected environment (a default would be the #943 class);
  C9  the certification scalars equal the template's;
  and every per-seat adapter carries its HARNESS-DIFFERENCE justification in the header, and
  every HESTIA_* name a shim's header mentions is actually read somewhere (#585's rule, which
  kimi_config_knobs_consumed_test enforced for one seat, now for all four).

Reads only and parses only: no shim is imported. Staging seams (unset in the repo and in CI):
HESTIA_CONTRACT_REPO, HESTIA_CONTRACT_SHIMS ({seat: path}), SHIM_STRUCTURE_TEMPLATE (path).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("HESTIA_CONTRACT_REPO") or os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
PLUGINS = os.path.join(REPO, "plugins")
TEMPLATE = os.environ.get("SHIM_STRUCTURE_TEMPLATE") or os.path.join(PLUGINS, "_template", "shim_template.py")
SHIM_OVERRIDE = json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}")
OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
_HOOK = "pre_" + "tool_" + "use.py"
_GEM = "before_" + "tool.py"
SHIMS = {"claude-code": ("claude-code", _HOOK, "claude-code"), "codex": ("codex", _HOOK, "codex"),
         "kimi": ("kimi", _HOOK, "kimi-code"), "gemini": ("gemini", _GEM, "gemini")}

# Anything here in a shim is a second decision path or an authority knob (C2). Substrings,
# matched against the SOURCE (comments included: a shim has no business narrating them either).
FORBIDDEN_TOKENS = (
    "hestia_gate_mechanism", "hestia_gate_core", "hestia_governance_closure",
    "hestia_shell_classifier", "query_society_safety", "fetch_policy_snapshot",
    "record_decision", "witness_decision", "claim_self_write", "witness_gate_self",
    "gate_self_call", "tally_scope", "degraded_verdict", "resolve_agent_policy",
    "path_in_scope", "command_in_scope", "detect_workspace", "_closure_classify",
    "_is_read_only", "HESTIA_PRE_TOTAL_BUDGET_MS", "HESTIA_PRE_REQUEST_TIMEOUT_S",
    "HESTIA_SOCIETY_GATE", "HESTIA_TEST_SABOTAGE", "subprocess", "mode_env",
)
PER_SEAT_KNOB = re.compile(r"HESTIA_[A-Z]+_GATE_MODE")
REQUIRED_HARNESS_KEYS = ("name", "event", "registrations", "timeout_unit_seconds",
                         "default_timeout_seconds", "on_timeout", "margin_seconds")

FAILURES: list = []
CHECKS = [0]


def check(name, ok, detail=""):
    CHECKS[0] += 1
    if not ok:
        FAILURES.append(f"{name}: {str(detail)[:400]}")


def shim_path(seat):
    if seat in SHIM_OVERRIDE:
        return SHIM_OVERRIDE[seat]
    d, f, _ = SHIMS[seat]
    return os.path.join(PLUGINS, d, "hooks", f)


def parse(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    return src, ast.parse(src)


def literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise KeyError(name)


def assignment(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == name:
            return node.value
    return None


def function_source(src, tree, name):
    lines = src.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def _env_read(node):
    """`os.environ.get("<KEY>")` with exactly one constant string argument, or None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "os"):
        if len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            return node.args[0].value
    return None


def profile_value_is_data(node):
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(profile_value_is_data(x) for x in node.elts)
    if _env_read(node) is not None:
        return True
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "abspath" and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path" and getattr(node.func.value.value, "id", None) == "os"):
        return len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "__file__"
    return False


def environment_reads(tree) -> set:
    """Every name read from the environment in a module, by any access form."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            f = node.func
            if isinstance(f, ast.Attribute) and (
                    (getattr(f.value, "id", None) == "os" and f.attr == "getenv")
                    or (isinstance(f.value, ast.Attribute) and f.value.attr == "environ"
                        and f.attr in ("get", "setdefault", "pop"))):
                out.add(node.args[0].value)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                and node.value.attr == "environ" and isinstance(node.slice, ast.Constant):
            out.add(node.slice.value)
        # A module constant naming an env var that is read through it (ROLLOUT_ENV, ...).
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and re.fullmatch(r"HESTIA_[A-Z0-9_]+", node.value.value):
            out.add(node.value.value)
    return out


def engine_trees():
    shared = os.path.join(PLUGINS, "_shared")
    with open(os.path.join(shared, "RUNTIME_MANIFEST.txt"), encoding="utf-8") as fh:
        names = [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    out = []
    for name in dict.fromkeys(names + [m + ".py" for m in OVERLAY]):
        path = OVERLAY.get(name[:-3]) or os.path.join(shared, name)
        if os.path.isfile(path):
            out.append(parse(path)[1])
    return out


def main() -> int:
    t_src, t_tree = parse(TEMPLATE)
    permitted = tuple(literal(t_tree, "PERMITTED_FUNCTIONS"))
    identical = tuple(literal(t_tree, "BYTE_IDENTICAL_FUNCTIONS"))
    adapters = tuple(literal(t_tree, "ADAPTER_FUNCTIONS"))
    profile_keys = set(literal(t_tree, "PERMITTED_PROFILE_KEYS"))
    harness_keys = set(literal(t_tree, "PERMITTED_HARNESS_KEYS"))
    scalars = {n: literal(t_tree, n) for n in
               ("SHIM_CERTIFICATION_SCHEMA", "CERTIFICATION_CRITERIA", "REQUIRED_GATE_API")}
    check("template-split-is-total", set(identical) | set(adapters) == set(permitted)
          and not set(identical) & set(adapters), (identical, adapters, permitted))
    check("template-defines-exactly-its-own-surface",
          {n.name for n in t_tree.body if isinstance(n, ast.FunctionDef)} == set(permitted))
    engine_env = set().union(*(environment_reads(t) for t in engine_trees()))

    for seat, (_d, _f, member) in SHIMS.items():
        src, tree = parse(shim_path(seat))
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        check(f"C4 [{seat}] function surface", defined == set(permitted),
              f"extra={sorted(defined - set(permitted))} missing={sorted(set(permitted) - defined)}")
        hits = sorted({t for t in FORBIDDEN_TOKENS if t in src} | set(PER_SEAT_KNOB.findall(src)))
        check(f"C2 [{seat}] no private governance or authority knob", not hits, hits)
        for name, want in scalars.items():
            try:
                got = literal(tree, name)
            except Exception:  # noqa: BLE001
                got = None
            check(f"C9 [{seat}] {name}", got == want, f"{got!r} != {want!r}")
        try:
            check(f"[{seat}] MEMBER_ID", literal(tree, "MEMBER_ID") == member)
        except Exception as e:  # noqa: BLE001
            check(f"[{seat}] MEMBER_ID", False, e)
        profile = assignment(tree, "PROFILE")
        keys, bad = set(), []
        if isinstance(profile, ast.Dict):
            for k, v in zip(profile.keys, profile.values):
                if isinstance(k, ast.Constant):
                    keys.add(k.value)
                    if not profile_value_is_data(v):
                        bad.append(k.value)
                    if k.value == "member_id" and not (isinstance(v, ast.Constant) and v.value == member):
                        bad.append("member_id!=" + member)
        else:
            bad.append("PROFILE-not-a-dict")
        check(f"C3 [{seat}] PROFILE is data", keys <= profile_keys and not bad,
              f"unknown={sorted(keys - profile_keys)} bad={bad}")
        try:
            harness = literal(tree, "HARNESS")
            ok = isinstance(harness, dict)
        except Exception as e:  # noqa: BLE001 — not a literal is not data
            harness, ok = {}, False
        check(f"C3 [{seat}] HARNESS is a literal", ok)
        check(f"C3 [{seat}] HARNESS keys", set(harness) == set(REQUIRED_HARNESS_KEYS)
              and set(harness) <= harness_keys, sorted(set(harness) ^ set(REQUIRED_HARNESS_KEYS)))
        check(f"[{seat}] HARNESS declares where its registration lives",
              bool(harness.get("registrations")) and all(
                  r.get("reader") in ("json-hook-commands", "toml-hook-commands") and r.get("path")
                  for r in harness.get("registrations", ())), harness.get("registrations"))
        check(f"[{seat}] HARNESS declares its timeout behaviour",
              str(harness.get("on_timeout", "")).startswith(("fail-open", "fail-closed")),
              harness.get("on_timeout"))
        check(f"[{seat}] HARNESS margin is positive", isinstance(harness.get("margin_seconds"), (int, float))
              and harness.get("margin_seconds", 0) > 0, harness.get("margin_seconds"))
        for fn in identical:
            want = hashlib.sha256((function_source(t_src, t_tree, fn) or "").encode()).hexdigest()
            got = hashlib.sha256((function_source(src, tree, fn) or "").encode()).hexdigest()
            check(f"C1 [{seat}] {fn} is the template's", got == want, f"{got[:12]} != {want[:12]}")
        doc = ast.get_docstring(tree) or ""
        for fn in adapters:
            n = len(re.findall(rf"^HARNESS-DIFFERENCE: {re.escape(fn)} - \S", doc, re.M))
            check(f"C4 [{seat}] {fn} is justified in the header", n == 1, n)
        own_env = environment_reads(tree)
        for knob in sorted(set(re.findall(r"HESTIA_[A-Z0-9_]+", doc))):
            check(f"#585 [{seat}] {knob} named in the header is read", knob in own_env | engine_env,
                  "a documented knob nothing reads")

    if FAILURES:
        print(f"FAIL — {len(FAILURES)} of {CHECKS[0]} checks")
        for f in FAILURES:
            print("  -", f)
        return 1
    print(f"OK — {CHECKS[0]}/{CHECKS[0]}: every shim is the template plus data plus three adapters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
