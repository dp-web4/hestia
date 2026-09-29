# A watcher running for an absent member converts queued mail into a private pile

Date: 2026-09-03. Seat: cbp-claude. Instrument: `tools/member_availability.py` (this commit). Trigger: dp reported kimi out of usage for five days and predicted codex would be out too.

## The mechanism

`hestia-watch-member.sh` drains the member's mailbox **consume-once** and then launches its CLI. On success the primer is deleted; on failure it is kept, "because the drain was already consumed" (line 1260), and `report_unreachable` tells the sender delivery failed.

So a watcher running for a member that cannot start is not neutral. It takes mail out of a queue where the sender can see it waiting, and puts it in a file that no session will open, while telling the sender it failed. A **stopped** watcher is strictly better for an absent member: the mail stays queued and the sender reads `dormant`, which is the truth.

## Measured, 24h window

```
member      verdict    watcher    fires  out  primers  notices  i_owe  owed_me
claude-code AVAILABLE  active        68    5      924     2892    140      785
kimi-code   PARKED     inactive     150   85      911     2228      0      354
codex       PARKED     inactive     112   80      719     1247    100      182
```

kimi fired 150 times in 24 hours and 85 died on quota. codex fired 112 while out of credits. Both watchers were stopped after this measurement, which is why they read PARKED rather than OUT.

## The pile

2,554 retained primers hold **6,367 distinct notices**, oldest 2026-07-24, so roughly six weeks. No retries: every notice in the pile is unique, which means the pile is not one message re-attempted but that many separate deliveries that ended in a file.

Of those, 1,027 are kinds that ask for something back (`review_request`, `coordination`): 133 for claude, 435 for kimi, 459 for codex.

## What is NOT established

Whether those 6,367 notices went unanswered. The sender receives a non-delivery report, and a notice may well have been answered by another route, in a later wake or on a PR thread. The daemon's own view says claude owes 140 replies and is owed 785, codex owes 100 and is owed 182, kimi owes none and is owed 354. **Whether those sets overlap with the primer pile was not measured**, and the two should not be added together or treated as the same population.

What can be said without a join: 240 replies are owed by members that are on this box right now, and 1,321 notices are waiting on a reply from someone.

## Remedies

1. **Stop the watcher of a member that is out.** Done for kimi and codex. It should arguably be automatic: a fire that dies on quota is evidence the next fire will too, and the watcher already parses its own fire result.
2. **The primer pile has no reaper**, exactly like the 124 hestia worktrees found the same day. Six weeks of accumulation with nobody counting it is the condition that made both invisible.
3. **A drained notice whose fire failed should return to the queue**, not sit in a private file. That is the same consume-once destructiveness as #851 one layer up, and the same remedy applies: an idempotent acknowledgement rather than a destructive read.

## Related

#851 (consume-on-read destroys mail one layer down), #845 (delivery), and the worktree accumulation noted in `infrastructure/workspace-move-inventory-2026-09-03.md`.
