#!/bin/bash
# Ancestry/status check for kimi-owned branches (cleanup audit, wake-1020).
cd /home/dp/ai-workspace/hestia || exit 1
for b in kimi/1290-once-spend-census kimi/1291-last-words-bait kimi/648-scope-act-fidelity \
         kimi/git-apply-readonly-flags kimi/harness-bound-deadline kimi/member-retire-990 \
         kimi/parity-runner-harness-repair kimi/wake-0929-settled-escalation-batch; do
  if git merge-base --is-ancestor "$b" origin/main 2>/dev/null; then merged=MERGED; else merged=not-merged; fi
  ahead=$(git rev-list --count origin/main.."$b" 2>/dev/null)
  # commits on the branch not pushed to its origin twin
  unpushed=$(git rev-list --count "origin/$b".."$b" 2>/dev/null || echo NA)
  echo "$b: $merged not_on_main=$ahead unpushed=$unpushed"
done
echo "--- detached worktree heads (contain-only check against origin/main) ---"
for c in c01036d9 f785001b 3f92b5aa 8d43d2b1 2038cfee 3987de0e; do
  if git merge-base --is-ancestor "$c" origin/main 2>/dev/null; then echo "$c: MERGED"; else echo "$c: not-merged"; fi
done
