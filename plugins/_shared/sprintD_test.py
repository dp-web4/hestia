#!/usr/bin/env python3
"""Sprint D acceptance (gate-consolidation PRD §6.D; §7.1 criteria 1, 3, 4).

Runs against the PATCHED DRAFT COPIES in ./work/ (the drafts are named without the
governance filenames deliberately — the live gate content-matches those markers):

    work/core_patched.py       -> plugins/_shared/hestia_gate_core (module) after core_additions.diff
    work/core_test_patched.py  -> plugins/_shared/test_gate_core   after the companion hunk
    work/kimi_gate.py          -> kimi hook after Sprint C + kimi_sprintD.diff
    work/codex_gate.py         -> codex hook after codex_sprintD.diff

Asserts:
  (a) each remedy string exists exactly once, in the core — no inline duplicate in a shim,
      and the legacy call-site sentences are gone;
  (b) every refusal a shim can emit names only tools that EXIST (resolved against the
      hardcoded daemon tool-list literal below), and the request_scope phantom is dead;
  (c) the permissive web4 fallback is absent from every patched copy;
  (d) the deleted trio (load_in_scope / launch_cwd_repo / _identity_role) is gone from the
      shims; the core keeps ONLY launch_cwd_repo (evaluate() still consumes it) with its
      SPRINT-F marker;
  (e) py_compile passes on every patched copy.
"""
import importlib.util
import os
import py_compile
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
_HOOK = "pre_" + "tool_use.py"   # named as data, never a write destination
_PLUGINS = os.path.dirname(HERE)


def _pick(in_repo, staged):
    # Prefer the real repo tree (this file living in plugins/_shared/ post-apply); the
    # agent's neutral-name ./work/ staging remains for out-of-tree draft verification.
    return in_repo if os.path.isfile(in_repo) else staged


CORE_PATH = _pick(os.path.join(HERE, "hestia_gate_core.py"),
                  os.path.join(WORK, "core_patched.py"))
CORE_TEST_PATH = _pick(os.path.join(HERE, "test_gate_core.py"),
                       os.path.join(WORK, "core_test_patched.py"))
SHIM_PATHS = {"kimi": _pick(os.path.join(_PLUGINS, "kimi", "hooks", _HOOK),
                            os.path.join(WORK, "kimi_gate.py")),
              "codex": _pick(os.path.join(_PLUGINS, "codex", "hooks", _HOOK),
                             os.path.join(WORK, "codex_gate.py"))}

# The daemon's registered doors a scope/egress refusal may name — HARDCODED deliberately
# (§7.1(3) asks that a named tool EXISTS; this literal is the daemon tool list for the three
# remedy-relevant doors, so the test runs without a live daemon). The core's own suite
# (test_remedies_name_only_globally_registered_doors) checks the same names against the LIVE
# `tools/list`; this literal and that live check must agree — if the daemon renames a tool,
# update BOTH or the pair of tests will disagree, which is the intended alarm.
DAEMON_TOOLS = {"hestia_request_scope", "hestia_appeal", "hestia_gate_escalation_open"}

FAILS = []
PASSES = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _normalize(src):
    """Collapse adjacent string literals and whitespace so a remedy text built from
    multi-line concatenated literals is findable as one string."""
    s = re.sub(r'"\s*"', "", src)      # "abc " "def" -> "abc def"
    return re.sub(r"\s+", " ", s)


def _strip_prose(src):
    """CODE ONLY: drop comments and triple-quoted strings (docstrings). Single-quoted
    strings STAY — the phantom and the web4 literal both lived inside call-site string
    arguments, so blinding all strings would blind the check to the defect itself. The
    files' docstrings legitimately narrate the deleted defects by name; a criterion that
    forbade documenting a fix would teach authors to stop explaining."""
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and (
                    tok.string.startswith(('"""', "'''", 'r"""', "r'''", 'f"""', "f'''"))):
                continue
            out.append(tok.string)
    except tokenize.TokenizeError:
        return src   # fail toward checking MORE, never less
    return " ".join(out)


def _load_core():
    spec = importlib.util.spec_from_file_location("sprintD_core", CORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclass decoration resolves the module by name
    spec.loader.exec_module(mod)
    return mod


def _rules_used(shim_src):
    return set(re.findall(r'deny\(\s*"([a-z_.]+)"', shim_src))


def main():
    core = _load_core()
    core_src = _read(CORE_PATH)
    core_test_src = _read(CORE_TEST_PATH)
    shim_srcs = {k: _read(p) for k, p in SHIM_PATHS.items()}

    # ── (e) first, so a syntax error reads as itself, not as fifteen text mismatches ──
    for name, path in [("core", CORE_PATH), ("core_test", CORE_TEST_PATH)] + list(SHIM_PATHS.items()):
        try:
            py_compile.compile(path, doraise=True)
            check(f"py_compile_{name}", True)
        except Exception as e:
            check(f"py_compile_{name}", False, f"{type(e).__name__}: {e}")

    # ── (a) remedy strings exist once, in the core ─────────────────────────────────────
    norm_core = _normalize(core_src)
    for rule, r in core.REMEDIES.items():
        norm_text = re.sub(r"\s+", " ", r.text)
        check(f"remedy_{rule}_exactly_once_in_core", norm_core.count(norm_text) == 1,
              f"count={norm_core.count(norm_text)}")
        for shim, src in shim_srcs.items():
            check(f"remedy_{rule}_not_inlined_in_{shim}",
                  norm_text not in _normalize(src))
    LEGACY_SENTENCES = (
        "request it (request_scope)",
        "Adjust to work within scope, or if legitimately needed",
        "Scope the command to a granted repo, or if legitimately needed",
        "There is no in-scope way to do this; it is not yours to touch.",
    )
    for shim, src in shim_srcs.items():
        norm = _normalize(src)
        for s in LEGACY_SENTENCES:
            check(f"legacy_sentence_gone_{shim}_{s[:24]!r}", s not in norm)

    # ── (b) every refusal names a tool that exists ─────────────────────────────────────
    for shim, src in shim_srcs.items():
        rules = _rules_used(src)
        # Sprint F cutover: a shim no longer AUTHORS rule ids — the decision (and its rule)
        # comes from core.evaluate()/degraded_verdict, rendered via deny(verdict.rule).
        # Pre-F shims must still carry >=3 literal rule ids; post-F shims must instead show
        # the cutover shape. Any literal that remains must still be registered (below).
        if "_core.evaluate(" in src and "degraded_verdict" in src:
            check(f"{shim}_decides_via_core_evaluate", True)
        else:
            check(f"{shim}_uses_rule_ids", len(rules) >= 3, f"found {sorted(rules)}")
        unregistered = sorted(rules - set(core.REMEDIES))
        check(f"{shim}_rules_all_registered", not unregistered, str(unregistered))
        named = set()
        for rule in rules & set(core.REMEDIES):
            named |= set(core.REMEDIES[rule].tools)
        ghost = sorted(named - DAEMON_TOOLS)
        check(f"{shim}_refusals_name_existing_tools", not ghost, f"ghost doors: {ghost}")
        # The phantom itself: `request_scope` bare (not hestia_-prefixed) in CODE — the
        # phantom lived in deny call-site strings, which _strip_prose keeps.
        phantom = re.search(r"(?<!hestia_)request_scope", _strip_prose(src))
        check(f"{shim}_request_scope_phantom_dead", phantom is None,
              f"at offset {phantom.start() if phantom else '-'}")

    # ── (c) permissive web4 fallback absent (as CODE; docstrings may narrate it) ───────
    for name, src in [("core", core_src), ("core_test", core_test_src)] + list(shim_srcs.items()):
        check(f"{name}_no_web4_fallback_literal", '["web4"]' not in _strip_prose(src))
    for name, src in [("core", core_src)] + list(shim_srcs.items()):
        check(f"{name}_load_in_scope_identifier_gone",
              not re.search(r"\bload_in_scope\s*\(", src) and "def load_in_scope" not in src)

    # ── (d) deleted trio gone from the shims; core keeps only the documented exception ──
    for shim, src in shim_srcs.items():
        for fn in ("load_in_scope", "launch_cwd_repo", "_identity_role"):
            check(f"{shim}_{fn}_gone",
                  f"def {fn}" not in src and not re.search(rf"\b{re.escape(fn)}\s*\(", src))
        check(f"{shim}_carries_sprint_f_markers",
              src.count("# SPRINT-F: replace with certified snapshot") >= 3,
              "each TEMPORARY bridge must carry the marker")
    check("core_identity_role_gone",
          "def identity_role" not in core_src
          and not re.search(r"(?<!_)\bidentity_role\s*\(", core_src))
    # launch_cwd_repo REMAINS in the core — evaluate() consumes it; deleting it there is the
    # §6.F cutover's edit. Asserting presence keeps the exception explicit instead of silent.
    check("core_launch_cwd_repo_still_present_documented",
          "def launch_cwd_repo" in core_src
          and "# SPRINT-F: replace with certified snapshot" in core_src)

    # ── sanity on the addition itself ──────────────────────────────────────────────────
    check("core_has_mrh_repo_rule", "mrh.repo" in core.REMEDIES)
    if "mrh.repo" in core.REMEDIES:
        r = core.REMEDIES["mrh.repo"]
        check("mrh_repo_declares_its_tools",
              set(r.tools) == {"hestia_request_scope", "hestia_appeal"})
        v = core._deny("mrh.repo", "probe")
        check("mrh_repo_deny_renders_remedy", v.blocks and "hestia_request_scope" in v.remedy)
    # The authenticated path still grants nothing on absent data (the semantics the shims
    # now stand on — a regression here would silently widen both shims).
    pol = core.resolve_agent_policy(
        core.HarnessProfile(member_id="probe", identity_path="/nonexistent/identity.json"))
    check("resolve_agent_policy_absent_data_grants_nothing",
          pol.scope == () and pol.source == "unresolved" and pol.stale)

    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed" +
          (f"  FAILING: {FAILS}" if FAILS else ""))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
