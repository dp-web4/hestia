#!/bin/bash
# Phase 1: report dirty state of kimi-owned stale worktrees (remove nothing).
cd /home/dp/ai-workspace/hestia || exit 1
for wt in scratchpad/wt-0929-batch scratchpad/wt-1290-census scratchpad/wt-1291-lastwords \
          scratchpad/wt-648-scope-act scratchpad/wt-apply-readonly scratchpad/wt-kimi-member-retire \
          scratchpad/wt-kimi-parity-cell scratchpad/wt-kimi-pr1224-review \
          scratchpad/wt-kimi-pr1231-postmerge scratchpad/wt-kimi-pr1232-review \
          scratchpad/wt-kimi-pr1239-review scratchpad/wt-onegate-review scratchpad/wt-resolver-verify; do
  if [ -d "$wt" ]; then
    dirty=$(git -C "$wt" status --porcelain | wc -l)
    echo "$wt: dirty_entries=$dirty"
    git -C "$wt" status --porcelain | head -5 | sed 's/^/    /'
  else
    echo "$wt: MISSING"
  fi
done
