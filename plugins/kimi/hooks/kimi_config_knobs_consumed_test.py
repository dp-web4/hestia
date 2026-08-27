#!/usr/bin/env python3
"""(#585) Every config knob this hook ADVERTISES must be CONSUMED.

The dead-delegation defect: CLAUDE_PRE was assigned from HESTIA_SOCIETY_GATE, never read,
and the knob sat in the --help config block telling operators it did something. An unused
variable cannot fail to resolve, so the seat's own registration pointed the knob at a file
that does not exist and nothing noticed. The fix deleted the knob; this test is the guard
the class always needs: a documented knob that nothing reads is a RED TEST, not a forum post.

Rule: every HESTIA_* name in the module docstring's Config block must reach a REAL
environment access — os.environ.get/[...]/setdefault/pop or os.getenv — in this hook or in
the manifest-declared shared engine modules (the §6.F cutover moved some consumers one
import down). Indirection through a HarnessProfile field counts ONLY when the field is both
bound to the name (`field: str = "NAME"`) and itself passed to an environment access;
HESTIA_FORBIDDEN_EXTRA is read exactly that way (hestia_gate_core.py).

Tightened 2026-08-27 on codex's cross-vendor dissent (escalation 992c8226a06aa908): the
first version of this guard censused QUOTED TOKENS anywhere in hook/engine source, so a
comment or an inert string satisfied it — and for HESTIA_FORBIDDEN_EXTRA the only quoted
token in the corpus WAS the field default, not the read: deleting
`os.environ.get(profile.forbidden_extra_env, "")` left the old guard green over a dead
knob, the exact #585 shape. The census is now over the AST: comments and docstrings never
parse into the patterns below, and a string literal nothing passes to os.environ is not
consumption. Measured on the mutation arms in .cbp-tmp (wake of notice 6360): the old
regex greened the read-deleted mutant; this guard reds it.
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "pre_tool_use.py")
SHARED = os.path.normpath(os.path.join(HERE, "..", "..", "_shared"))
ENGINE = ["hestia_gate_core.py", "hestia_gate_mechanism.py", "hestia_governance_closure.py"]

_ENV_METHODS = ("get", "setdefault", "pop")


def advertised_knobs(hook_src):
    """HESTIA_* names from the Config block of the hook's module docstring."""
    doc = hook_src.split('"""', 2)[1]
    config_block = doc.split("Config (", 1)[1]
    return sorted(set(re.findall(r"^[ \t]*(HESTIA_[A-Z0-9_]+)[\s:=]", config_block, re.M)))


def _is_environ(node):
    """The `os.environ` half of os.environ.get(...) / os.environ[...]."""
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _env_arg(node):
    """The name argument of one environment access, or None.

    Direct:   a string constant — os.environ.get("NAME"), os.environ["NAME"],
              os.getenv("NAME"), os.environ.setdefault/pop("NAME", ...).
    Indirect: an attribute — os.environ.get(profile.workspace_env) — reported by
              field name so a HarnessProfile binding can close it below.
    """
    if isinstance(node, ast.Call) and node.args:
        f = node.func
        if isinstance(f, ast.Attribute) and (
                (isinstance(f.value, ast.Name) and f.value.id == "os"
                 and f.attr == "getenv")
                or (_is_environ(f.value) and f.attr in _ENV_METHODS)):
            return node.args[0]
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        return node.slice
    return None


def consumed_names(sources):
    """Knob names provably passed to an environment access in any of the sources.

    AST-only, so neither comments nor docstrings can mint a proof. Two arms:
      direct   — the quoted name IS the access argument;
      indirect — a `field: str = "NAME"` binding whose field is itself an access
                 argument somewhere in the corpus (the HarnessProfile convention).
    A binding without a field read, or a field read without a binding, proves nothing.
    """
    direct, bindings, field_reads = set(), {}, set()
    for src in sources:
        for node in ast.walk(ast.parse(src)):
            arg = _env_arg(node)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                direct.add(arg.value)
            elif isinstance(arg, ast.Attribute):
                field_reads.add(arg.attr)
            if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and node.value.value.startswith("HESTIA_")):
                bindings[node.target.id] = node.value.value
    return direct | {name for field, name in bindings.items() if field in field_reads}


def _strip_doc(body):
    """Blank a docstring in place: prose is not code, and a mention is not a read."""
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body[0].value.value = ""


def _code_strings(src):
    """String constants in executable position, docstrings excluded."""
    tree = ast.parse(src)
    _strip_doc(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _strip_doc(node.body)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _claude_pre_assigned(src):
    """A CLAUDE_PRE* assignment at ANY depth — the dead delegation variable returning."""
    for node in ast.walk(ast.parse(src)):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
        if any(isinstance(t, ast.Name) and t.id.startswith("CLAUDE_PRE") for t in targets):
            return True
    return False


def main() -> int:
    src = open(HOOK, encoding="utf-8").read()
    advertised = advertised_knobs(src)
    if not advertised:
        print("FAIL: no config knobs found in the docstring — the parser, not the hook, broke")
        return 1
    sources = [src]
    for mod in ENGINE:  # plus the manifest-declared shared engine (consumers one import down)
        p = os.path.join(SHARED, mod)
        if os.path.exists(p):
            sources.append(open(p, encoding="utf-8").read())
    consumed = consumed_names(sources)
    failures = [f"{name}: advertised in Config but read nowhere in hook or engine"
                for name in advertised if name not in consumed]
    if failures:
        print("FAIL — advertised-but-dead config knobs (#585):")
        for f in failures:
            print("  " + f)
        return 1
    # The removed knob must stay removed (the regression itself). Tightened 2026-08-27 on
    # claude-code's mutation probe (peer factor on 5344b7832489bc1e; staging escalations
    # 61e282101e871eb9 / 3c7474bb8b1bd1e5): the regex arm this replaced could not see
    # os.getenv("HESTIA_SOCIETY_GATE"), a from-import of environ, a variable-held name, or
    # an indented CLAUDE_PRE — each resurrected the dead knob green. The census is now AST:
    # the knob's NAME as a code string constant (docstrings stripped, so prose mentions
    # stay fine) or a CLAUDE_PRE* assignment at any depth IS the regression.
    bodies = [src.split('"""', 2)[2]] + sources[1:]
    if any("HESTIA_SOCIETY_GATE" in _code_strings(b) or _claude_pre_assigned(b) for b in bodies):
        print("FAIL: HESTIA_SOCIETY_GATE / CLAUDE_PRE is being READ again — the #585 deletion regressed")
        return 1
    print(f"ok: {len(advertised)} advertised config knobs, all consumed; dead knob absent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
