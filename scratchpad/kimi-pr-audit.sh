#!/bin/bash
cd /home/dp/ai-workspace/hestia || exit 1
for b in kimi/1290-once-spend-census kimi/1291-last-words-bait kimi/648-scope-act-fidelity \
         kimi/git-apply-readonly-flags kimi/harness-bound-deadline kimi/member-retire-990 \
         kimi/parity-runner-harness-repair kimi/wake-0929-settled-escalation-batch; do
  echo "== $b"
  gh pr list --head "$b" --state all --json number,state,title --limit 3 \
    --template '{{range .}}  PR #{{.number}} {{.state}} {{.title}}{{"\n"}}{{end}}'
done
