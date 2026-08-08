#!/usr/bin/env python3
"""Bisect the two verbatim refused commands to the exact condemning segment."""
import importlib.util
import sys

ARM_B = ("/mnt/c/exe/projects/ai-agents/hestia/plugins/claude-code/hooks/"
         + "pre_tool_use" + ".py")
spec = importlib.util.spec_from_file_location("b", ARM_B)
B = importlib.util.module_from_spec(spec)
sys.modules["b"] = B
spec.loader.exec_module(B)

TREE = "plugins/claude-code/hooks/" + "pre_tool_use" + ".py"

print("git read subcommands:", sorted(B._GIT_READ_SUBCOMMANDS))
print("git guarded subcommands:", {k: sorted(v) for k, v in sorted(B._GIT_GUARDED_SUBCOMMANDS.items())})
print()

SEGMENTS = [
    'echo "=== is 0513661 on main? ==="',
    'git branch -a --contains 0513661',
    'git branch -a --contains 0513661 2>/dev/null | head -20',
    'git show main:' + TREE,
    'git show main:' + TREE + ' | sha256sum',
    'git log --oneline -5 -- ' + TREE,
    'git rev-parse HEAD',
    'git merge-base --is-ancestor a b',
    'git cat-file -p HEAD',
]

print(f"{'segment':<58} verdict")
print("-" * 70)
for s in SEGMENTS:
    print(f"{s[:56]:<58} {'read-only' if B._is_read_only('Bash', {'command': s}) else 'WRITE'}")

print()
full = ('echo "=== is 0513661 on main? ===" && git branch -a --contains 0513661 '
        '2>/dev/null | head -20 && echo "=== main vs HEAD gate digest ===" && '
        'git show main:' + TREE + ' | sha256sum')
print("verbatim refused 3d38341a:",
      "read-only" if B._is_read_only("Bash", {"command": full}) else "WRITE")

fp13 = ('TREE=/mnt/c/exe/projects/ai-agents/hestia/' + TREE
        + ' INST=/home/dp/.claude/hooks/hestia/pre_tool_use.py'
        + ' for f in "$TREE" "$INST"; do sha256sum "$f"; done')
print("verbatim refused a6e3be4a:",
      "read-only" if B._is_read_only("Bash", {"command": fp13}) else "WRITE")

# The proposed remedy for the ordering defect: strip to a FIXPOINT.
print()
print("remedy check — does re-running the strippers to a fixpoint fix a6e3be4a?")
parts = fp13.split()
# emulate: alternate the two strippers until neither changes anything
prev = None
cur = parts
for _ in range(6):
    cf = B._control_flow_remainder(cur)
    if cf is None:
        cur = None
        break
    asg = B._assignment_remainder(cf)
    if asg is None:
        cur = None
        break
    if asg == cur:
        break
    cur = asg
print("  fixpoint head:", (cur[0] if cur else None),
      "->", "would be read-only" if cur and cur[0] in B._READ_ONLY_HEADS else "still WRITE")
