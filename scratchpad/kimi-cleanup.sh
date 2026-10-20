#!/bin/bash
# Phase 2: remove kimi-owned stale worktrees (PRs verified merged or detached review
# checkouts) and delete local kimi/* branches that are FULLY PUSHED (origin twin exists,
# nothing unpushed). Never touches: the shared tree's branch, open-PR branches
# (harness-bound-deadline PR #1262, 1354-moot-transient-debt PR #1357), or anything with
# no remote twin / unpushed commits.
cd /home/dp/ai-workspace/hestia || exit 1

echo "== worktrees =="
for wt in scratchpad/wt-0929-batch scratchpad/wt-1290-census scratchpad/wt-1291-lastwords \
          scratchpad/wt-648-scope-act scratchpad/wt-apply-readonly scratchpad/wt-kimi-member-retire \
          scratchpad/wt-kimi-parity-cell scratchpad/wt-kimi-pr1224-review \
          scratchpad/wt-kimi-pr1231-postmerge scratchpad/wt-kimi-pr1232-review \
          scratchpad/wt-kimi-pr1239-review scratchpad/wt-onegate-review scratchpad/wt-resolver-verify; do
  git worktree remove --force "$wt" && echo "removed $wt"
done

echo "== local branches (only fully-pushed) =="
KEEP="kimi/wake-1013-four-petitions kimi/harness-bound-deadline kimi/1354-moot-transient-debt"
git branch --list 'kimi/*' --format '%(refname:short)' | while read -r b; do
  case " $KEEP " in *" $b "*) echo "keep (active): $b"; continue;; esac
  if ! git rev-parse --verify -q "origin/$b" >/dev/null; then
    echo "keep (NO REMOTE TWIN): $b"; continue
  fi
  unpushed=$(git rev-list --count "origin/$b".."$b")
  if [ "$unpushed" != "0" ]; then
    echo "keep (unpushed=$unpushed): $b"; continue
  fi
  git branch -D "$b" >/dev/null && echo "deleted local (record on origin): $b"
done
