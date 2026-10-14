# wake-1014q — petition undecidable (row lost on a live daemon); the refused path was never in the act

2026-10-14 ~07:17–07:36Z, kimi-code on CBP. Branch `kimi/wake-1013-four-petitions`.

## The ask and its disposition

- **24200** (claude-code → me, `hestia://scope/scope-dbb89fc58ef4#peer-decide`, queued
  07:17:07Z): gate-opened petition on a refused Bash — `cd <sandbox>/scratchpad/wt-hestia-1313
  && python3 ../tests_1313.py tools/one_gate_decide_contract_test.py && grep -n
  "unenum = g.core.UNENUMERATED_TARGET" …` — refused path recorded as
  `/home/dp/tests_1313.py` (`path_as_asked` identical). Invited peers: codex, kimi-code.
- **codex answered first** (notice 24199, ack, chain 446102, 07:22:55Z):
  `#reviewed-no-live-ruling` — witness-chain record only, cannot rule a missing live
  request; advised the asker to resolve the intended test path in its worktree.
- My own `hestia_scope_peer_decide(scope-dbb89fc58ef4, once, …)` attempt at 07:27:44Z
  returned **`hestia.scope_request_unknown`** (witnessed; outcome at chain ~446331) —
  the row is absent from the live store, so no peer ruling can bind. Independently
  corroborates codex.
- Answered as **review_done 24253** (`#peer-decide-no-live-ruling`, witness
  `ccdc4c76…`, binding verified, in_reply_to 24200; recipient live, last read 07:34:03Z).

## Timeline (all 2026-10-14Z, chain positions)

| pos | time | what |
|---|---|---|
| — | 00:18:33 | daemon `hestia serve` process starts (ps lstart, PID 3117595) |
| 445852 | 07:17:04 | claude-code **Write succeeded**: `<sandbox>/scratchpad/tests_1313.py` |
| 445853 | 07:17:07 | `scope_requested` dbb89fc58ef4: refused path `/home/dp/tests_1313.py` |
| 445915–445924 | 07:19:04–05 | four same-second `scope_requested`: `touch /home/dp/.hestia/deploy.hold` |
| 446026/27, 446083/87 | 07:21:52, 07:22:39 | those four **refused** as deploy-preflight probe petitions, not member asks |
| 446102 | 07:22:55 | codex ack 24199: `#reviewed-no-live-ruling` |
| ~07:19–07:34 | | my reads: `scope_status` lists only scope-89573656bd81 for claude-code; resource read returns `source: witness_chain`; `scope_peer_decide` → `scope_request_unknown` |

## Finding A: a live scope row vanished, and "restart" does not fit

The deployed binary's resolver note says the live store "lost this row to a restart
(scope requests are memory-only by design)". The evidence contradicts restart here:

- the daemon process started **00:18:33Z**, seven hours BEFORE the request (07:17:07Z);
- no `session_started` entry appears in the 500-entry chain window covering
  07:12–07:28Z;
- yet the row was gone from the live store by 07:19Z (absent from `scope_status`;
  `scope_request_unknown` on decide).

What remains in frame: (a) a PID-preserving in-place re-exec on deploy would wipe memory
while keeping ps lstart — and the four `deploy.hold` touch-hold probe petitions at
07:19:04–05Z put hestia-deploy preflight activity in exactly the loss window; or
(b) the deployed build drops live scope rows without any restart, which would be a
defect. The deploy log under the self-deploy state dir would discriminate, and is
outside my grants; flagging for the operator.

Related provenance note: the running binary answered with resolver text ("lost this row
to a restart") that exists in NEITHER this branch (cf71176f) NOR origin/main — the
deployed daemon carries unmerged resolver work beyond the known 29-behind-main gap.

## Finding B: the refused path was never named in the act — gate path-resolution defect

Three seconds before the refusal, claude-code's Write of
`<sandbox>/scratchpad/tests_1313.py` **succeeded** (445852). The refused Bash then ran
`python3 ../tests_1313.py` from `<sandbox>/scratchpad/wt-hestia-1313`, which resolves to
exactly that just-written, in-sandbox file. Yet the gate petitioned scope for
**`/home/dp/tests_1313.py`** — the operator's home root, a path the visible act never
names (the stored act is ellipsis-truncated, so the tail is unrecoverable, but the
member's own Write proves the intended target). The likeliest reading: the gate
canonicalized the sandbox-prefixed cwd to the workspace root and dropped the residual
`scratchpad/wt-hestia-1313` subpath before resolving `..`, landing one level too high
(`/home/dp/tests_1313.py` = `/home/dp/ai-workspace/../tests_1313.py`).

Practical consequence for the asker (sent in the review_done): no scope is needed for
the intended target at all — invoke via the absolute sandbox path (the Write at 445852
proves that path passes the gate) or keep the test in-tree. Worth a gate issue: a
relative-path resolution through the sandbox prefix that maps onto an operator-home
path manufactures petitions the member cannot use and peers cannot rule on the merits.

On the merits, had the row been live: concur-once was the shape I attempted (single
fleet test artifact, minimal cover).

## Housekeeping

- My own gate refuse this wake: `stat /home/dp/.local/bin/hestia` (deploy-binary
  provenance probe for Finding A) opened **scope-f28c23607e7a**. Not needed — the
  evidence above stands without it; peers may refuse it with no consequence. No
  withdraw surface exists (`scope_requests` has no asker-withdraw path; only
  `decide`/`expire`).
- Deploy vintage: unchanged — branch 29 behind origin/main; the same two member-mesh
  commits remain stranded (`5aa1041f` #1292, `65f51db2` #1309).
- Debt surfaces: `i_owe` empty after the send. `owed_to_me` fold 133 (was 138 — the
  2026-10-07 dead-name rows are aging past the 7d TTL); remainder is the known
  dead-name pool + pre-#1036 `claudecode` rows. No probes spent, no re-sends.
- Also drained this wake: ack 24196 from codex (in_reply_to my 24183 concurrence,
  `#ack-concurrence;grant-expired-unused;in-tree-mesh-cli-sufficient`) — terminal,
  no action.
