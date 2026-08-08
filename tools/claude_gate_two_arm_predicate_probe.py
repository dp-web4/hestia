#!/usr/bin/env python3
"""Run BOTH gate revisions' self-touch predicate over the two commands that were
actually refused this wake, plus controls.

Arm A = the gate ENFORCING on CBP right now (commit 0513661).
Arm B = the gate MERGED TO MAIN (HEAD/worktree), which is not installed.

The question this answers: does closing the install drift clear the pending
false positives, or are they orthogonal? A remedy claim is unmeasured until
both arms are run on the same inputs.
"""
import importlib.util
import sys

ARM_A = "/home/dp/.claude/hooks/hestia/" + "pre_tool_use" + ".py"
ARM_B = ("/mnt/c/exe/projects/ai-agents/hestia/plugins/claude-code/hooks/"
         + "pre_tool_use" + ".py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = load(ARM_A, "gate_installed")
B = load(ARM_B, "gate_merged")

GATE_TAIL = "hooks/hestia/" + "pre_tool_use" + ".py"
TREE_TAIL = "plugins/claude-code/hooks/" + "pre_tool_use" + ".py"

CASES = [
    # (label, tool, tool_input, expected_class)
    ("a6e3be4a  FP13: VAR=path + for-head, three READS",
     "Bash",
     {"command": 'TREE=/mnt/c/exe/projects/ai-agents/hestia/' + TREE_TAIL
                 + ' INST=/home/dp/.claude/' + GATE_TAIL
                 + ' for f in "$TREE" "$INST"; do sha256sum "$f"; done'},
     "false positive (reads)"),

    ("3d38341a  echo-prefixed git show/branch, all READS",
     "Bash",
     {"command": 'echo "=== check ===" && git branch -a --contains 0513661 '
                 '| head -20 && git show main:' + TREE_TAIL + ' | sha256sum'},
     "false positive (reads)"),

    ("control+  a genuine WRITE to the enforcing gate",
     "Bash",
     {"command": "cat /tmp/evil.py > /home/dp/.claude/" + GATE_TAIL},
     "TRUE positive - must refuse in both arms"),

    ("control-  unrelated read, no marker",
     "Bash",
     {"command": "git log --oneline -5"},
     "must pass in both arms"),

    ("heredoc: report ABOUT the gate, quoted body, tee to a NOTES file",
     "Bash",
     {"command": "tee /tmp/notes.md <<'EOF'\nthe gate at " + TREE_TAIL
                 + " refused a read\nEOF"},
     "FP8 shape - the carve-out c26d9ff/4d58536 targets"),
]

W = 52
print(f"{'case':<{W}} {'INSTALLED (0513661)':<22} {'MERGED (main)':<22}")
print("-" * (W + 46))

rows = []
for label, tool, ti, expected in CASES:
    ra = A._touches_self(tool, ti)
    rb = B._touches_self(tool, ti)
    va = "REFUSE " + repr(ra[0])[:12] if ra else "allow"
    vb = "REFUSE " + repr(rb[0])[:12] if rb else "allow"
    rows.append((label, va, vb, expected, ra is None, rb is None))
    print(f"{label:<{W}} {va:<22} {vb:<22}")

print()
print("expectations / divergence:")
for label, va, vb, expected, a_ok, b_ok in rows:
    flag = "  <-- ARMS DIVERGE" if (a_ok != b_ok) else ""
    print(f"  {label[:44]:<46} expect: {expected}{flag}")

diverged = sum(1 for r in rows if r[4] != r[5])
print()
print(f"cases where installing the merged gate CHANGES the verdict: {diverged}/{len(rows)}")
