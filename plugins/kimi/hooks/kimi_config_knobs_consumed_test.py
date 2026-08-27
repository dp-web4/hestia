#!/usr/bin/env python3
"""(#585) Every config knob this hook ADVERTISES must be CONSUMED.

The dead-delegation defect: CLAUDE_PRE was assigned from HESTIA_SOCIETY_GATE, never read,
and the knob sat in the --help config block telling operators it did something. An unused
variable cannot fail to resolve, so the seat's own registration pointed the knob at a file
that does not exist and nothing noticed. The fix deleted the knob; this test is the guard
the class always needs: a documented knob that nothing reads is a RED TEST, not a forum post.

Rule: every HESTIA_* name in the module docstring's Config block must appear quoted in code
OUTSIDE the docstring — either in this hook or in the manifest-declared shared engine modules
(the §6.F cutover moved some consumers one import down, e.g. HESTIA_FORBIDDEN_EXTRA is read
by hestia_gate_core). A name that only appears in docs is the #585 shape.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "pre_tool_use.py")
SHARED = os.path.normpath(os.path.join(HERE, "..", "..", "_shared"))
ENGINE = ["hestia_gate_core.py", "hestia_gate_mechanism.py", "hestia_governance_closure.py"]


def main() -> int:
    src = open(HOOK, encoding="utf-8").read()
    # Docstring is the first triple-quoted block; the Config block is inside it.
    doc = src.split('"""', 2)[1]
    config_block = doc.split("Config (", 1)[1]
    advertised = sorted(set(re.findall(r"^\s+(HESTIA_[A-Z_]+)\s", config_block, re.M)))
    if not advertised:
        print("FAIL: no config knobs found in the docstring — the parser, not the hook, broke")
        return 1
    code = src.split('"""', 2)[2]  # hook code after the docstring
    for mod in ENGINE:  # plus the manifest-declared shared engine (consumers one import down)
        p = os.path.join(SHARED, mod)
        if os.path.exists(p):
            code += "\n" + open(p, encoding="utf-8").read()
    failures = []
    for name in advertised:
        if not re.search(r'["\']' + name + r'["\']', code):
            failures.append(f"{name}: advertised in Config but read nowhere in hook or engine")
    if failures:
        print("FAIL — advertised-but-dead config knobs (#585):")
        for f in failures:
            print("  " + f)
        return 1
    # The removed knob must stay removed (the regression itself). Prose MENTIONS are fine
    # (the removal note names it); what must not return is the env read or the assignment.
    if re.search(r'os\.environ[.\[][^)]*HESTIA_SOCIETY_GATE', code) or re.search(r"^CLAUDE_PRE\s*=", code, re.M):
        print("FAIL: HESTIA_SOCIETY_GATE / CLAUDE_PRE is being READ again — the #585 deletion regressed")
        return 1
    print(f"ok: {len(advertised)} advertised config knobs, all consumed; dead knob absent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
