#!/usr/bin/env python3
"""Pins for tools/marker_fp_classify.py.

Every case below is a REAL escalation shape taken from the witness chain, and each
one is a bug this classifier had at some point during #668's follow-up. They are
pinned because each failure produced a plausible, well-formed, WRONG verdict --
never an error -- which is the failure mode #668's abandoned regex died of.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from marker_fp_classify import classify

CASES = [
    # (label, cmd, marker, tool, expected)
    ("plain read is an FP",
     "grep -n marker plugins/_shared/hestia_gate_core.py", "plugins/_shared", "Bash", "READ_ONLY"),
    ("genuine gated write",
     "echo x > plugins/_shared/hestia_gate_core.py", "plugins/_shared", "Bash", "WRITE"),
    # the `for f in ...; do grep ...; done` shape that #668 said classified as NEITHER
    ("for-loop list is a naming, body decides",
     "for f in plugins/_shared/hestia_gate_core.py; do grep -n marker \"$f\"; done",
     "plugins/_shared", "Bash", "READ_ONLY"),
    # the chain record flattens newlines, collapsing a script into one cd-headed segment
    ("newline-flattened script still finds the write",
     "cd /mnt/c/x/.wt/585 chmod +x plugins/kimi/hooks/t.py git add plugins/kimi/hooks/t.py",
     "plugins/*/hooks", "Bash", "WRITE"),
    # gate 1a is a raw substring match, so it trips on paths named inside quoted data
    ("marker named inside a heredoc body is not a write",
     "tee /tmp/out.txt <<'EOF'\nprose naming pre_tool_use.py and nothing else\nEOF",
     "pre_tool_use.py", "Bash", None),          # must NOT be WRITE
    ("relative destination under a /tmp cwd is a lookalike, not a gated write",
     "cd /tmp/armb && mkdir -p wt/plugins/kimi/hooks && cp g.py wt/plugins/kimi/hooks/guard.py",
     "plugins/*/hooks", "Bash", "READ_ONLY"),
    # truncation asymmetry: a visible write is monotone, a visible read is not
    ("truncated tail cannot unmake a visible write",
     "chmod +x plugins/kimi/hooks/t.py && git add plugins/kimi/hooks/t.py…[truncated]",
     "plugins/*/hooks", "Bash", "WRITE"),
    ("truncated tail CAN hide a write after visible reads",
     "grep -n x plugins/_shared/hestia_gate_core.py…[truncated]",
     "plugins/_shared", "Bash", "READ_ONLY_PREFIX"),
    # stated_reason has a DIFFERENT GRAMMAR per tool -- parsing Edit rows as shell
    # manufactured spurious READ_ONLY verdicts and broke the negative control
    ("Edit reason is a bare destination, not a command",
     "/mnt/c/x/plugins/kimi/hooks/t.py", "plugins/*/hooks", "Edit", "WRITE"),
    ("Edit destination under /tmp is a lookalike",
     "/tmp/585new/plugins/kimi/hooks/t.py", "plugins/*/hooks", "Edit", "READ_ONLY"),
    ("apply_patch reason is patch text; the header names the destination",
     "*** Begin Patch\n*** Update File: /mnt/c/x/plugins/_shared/gate.py\n@@ -a\n+b",
     "plugins/_shared", "apply_patch", "WRITE"),
    ("apply_patch marker matching only the diff BODY is an FP",
     "*** Begin Patch\n*** Update File: /mnt/c/x/tools/z.py\n@@\n+ see plugins/_shared/gate.py\n",
     "plugins/_shared", "apply_patch", "READ_ONLY"),
    ("redaction is its own stratum, never silently an FP",
     "Bash [REDACTED — names a credential-shaped token; 243 chars withheld]",
     "plugins/_shared", "Bash", "REDACTED"),
]

def main():
    bad = 0
    for label, cmd, marker, tool, want in CASES:
        got, why = classify(cmd, marker, tool)
        if want is None:
            ok = got != "WRITE"
            want_s = "not WRITE"
        else:
            ok = got == want
            want_s = want
        if not ok:
            bad += 1
            print(f"FAIL {label}\n  want {want_s}, got {got} ({why})")
        else:
            print(f"ok   {label}  -> {got}")
    print(f"\n{len(CASES)-bad} passed, {bad} failed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
