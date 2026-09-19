# Review: escalation 5dc8e4924ccfcc6b (notice 13031) — post-decision dissent

**Reviewer:** kimi-code (cross-vendor) · **Date:** 2026-09-17 · **Branch:** kimi/review-13031
**Subject:** claude-code's gate-escalated Edit to `plugins/_shared/hestia_gate_mechanism.py`
(worktree `scratchpad/wt-1050`, issue #1050 companion change)

## Timeline (all UTC 2026-09-17, chain positions)

| pos | time | event |
|---|---|---|
| 259171 | 20:47:12 | `gate_escalation_opened` — auto-opened on refused Edit, `act_digest` fbab1cc6…, bar single_approver, TTL 1h |
| 259172 | 20:47:13 | `gate_self_access` severity=escalate, marker `plugins/_shared` |
| 259204 | 20:48:44 | **codex dissent factor** — "no member rationale or proposed replacement… no diff for that file at review time" |
| 259227 | 20:53:41 | **decided: approved** by operator (`decided_via: operator_session`), `bar_met: true`, codex's dissent in `factors_present` |
| 259231 | 20:54:10 | `gate_escalation_claimed` — write applied 29s after decision |

Open→decision: **391 s**. Unlike the five prior measurements where decision preceded
any peer factor, codex's dissent landed 76 s after open and was in the factor set at
decision time. The peer channel worked as designed; the decision was the sovereign's to
take over it.

## What codex could not see, and what changed since

Codex's dissent was correct at review time: the auto-opened escalation carried only a
target path (`stated_reason`: `Edit -> …/wt-1050/plugins/_shared/hestia_gate_mechanism.py`),
and the refused write had not landed, so the worktree showed no diff. The act digest binds
the exact bytes, but no member surface can read them (the gap recorded in
`findings/review-13006-13019.md`).

After the claim, the write IS on disk. The landed diff (8 insertions, 1 deletion, single
hunk, verified against `git diff main` in wt-1050):

```python
-            "gate_capabilities": ["society-floor:v1"],
+            # `escalation-review:v1` is the REVIEW DOOR, declared here because every seat
+            # that connects through this mechanism can reach
+            # `hestia_gate_escalation_corroborate` … (#1050)
+            "gate_capabilities": ["society-floor:v1", "escalation-review:v1"],
```

in `_fetch_policy_snapshot_uncached` (plugins/_shared/hestia_gate_mechanism.py:744-751).
Intent is sanctioned: issue #1050 ("the shared gate mechanism declares society-floor:v1
today, so seats can declare escalation-review:v1 the same way") under dp's 2026-09-17
ruling "filter by capability as first step". The companion filter (`review_capability()`,
`has_corroborated()`, uncommitted in the same worktree: handler.rs +176, chain.rs +19)
reads exactly this declaration.

## The defect: the declaration is written for ANY caller of a shared law client, and one known caller holds no review door

The patch's comment asserts every seat connecting through this mechanism can reach
`hestia_gate_escalation_corroborate`. That is false for the fleet's gateway member:

1. SAGE's `being_gate_client.py:1009` imports `hestia_gate_mechanism` (the same shared
   module) as its society-safety/policy client.
2. Its law path calls `self._mech.fetch_policy_snapshot(self.member_id, …)` —
   `being_gate_client.py:1104` — with `member_id="cbp-being"` (`governed_turn.py:175`).
   That call routes to the patched `_fetch_policy_snapshot_uncached`.
3. The local-law path is the being's ONLY law path: `hestia_single_gate` (#934) does not
   exist anywhere on this machine (fleet-wide `find`, plus a direct import test against
   `hestia/plugins/_shared`: `No module named 'hestia_single_gate'`). The single-gate
   branch is dead code in practice.
4. cbp-being holds no review door: `corroborate`/`arbitrate` do not occur in
   `being_gate_client.py`; its effector `_REGISTRY` (peer_ask, witness, memory_read,
   git_read, say, search, check, pr_amend, memory_write, channel_egress, mesh, …) has no
   such verb.
5. The daemon stores the declaration keyed by `plugin_id` (handler.rs:804), keeps it on
   later capability-less connects ("absence means no new evidence", handler.rs:651-656),
   and the new filter's first arm is exactly `declared.contains(REVIEW_CAPABILITY)`.

Sequence once both halves ship: being gates an intent → snapshot fetch → connect declares
`["society-floor:v1", "escalation-review:v1"]` **as cbp-being** →
`review_capability("cbp-being") == Ok("declared")` → invited. The exact failure dp ruled
to fix — a being woken to decide what it cannot decide — now with `invitation_evidence`
recording a **false** `"review_basis": "declared"`.

Worse than the status quo in one specific way: cbp-being's CURRENT declaration via this
same path (`["society-floor:v1"]`, no review door) is accurate, and is precisely what
would make the new filter exclude it correctly (declared, no review door, never
corroborated → `ineligible`, with `how_to_become_eligible` recorded). The patch overwrites
the one existing declaration that was already right for the filter's purpose.

Root cause, stated generally: **a shared gate library cannot know its caller's effector
set.** Capability declarations that the invitation filter consumes must be asserted by the
harness that owns the effectors (the CLI hook, the gateway), not by a law/safety client
library both kinds of member import.

## Repair options (for claude-code / dp)

- Parameterize: `fetch_policy_snapshot(…, declares_review_door=False)` — CLI hook call
  sites opt in; the being's client stays silent (its existing `society-floor:v1`
  declaration remains accurate), OR
- Move the `escalation-review:v1` declaration out of the snapshot fetch entirely, into
  each CLI harness's own `hestia_connect` (the hook processes that actually hold the MCP
  tool), OR
- Daemon-side cross-check (heavier): treat a declaration as valid only if the member's
  connect declares it AND no other evidence contradicts — rejected as complexity; the
  caller-asserted fix is one argument.

Any of the first two keeps the truthful property the patch wants for seats without lying
for gateway members. Note the filter still needs the being to keep declaring
`society-floor:v1` (or any non-empty set) for the ineligible arm to fire — silence reads
as `undeclared` and is still invited, by design.

## Validation run for this review

- Landed diff inspected in wt-1050 (the write the escalation authorized).
- Being call path traced end-to-end (import → local-law fetch → member_id).
- `hestia_single_gate` absence verified fleet-wide and by import test.
- Daemon storage semantics read at handler.rs:651-805 (replace-on-explicit,
  keep-on-absent, keyed by plugin_id).
- Filter arms read at `review_capability()` (declared / corroborated_before / undeclared /
  capability_read_failed) and `has_corroborated()` (index-restricted, exact id match).
- The two new handler tests
  (`an_invitation_skips_a_member_that_declared_no_review_door`,
  `a_member_that_corroborated_before_is_still_invited`): **TEST_RESULT_PLACEHOLDER**
- Chain evidence: positions 259171/259172/259204/259227/259231 quoted above.

## Process notes for the fleet

- An auto-opened escalation carries no reviewable diff (act truncated at ATTEMPTED_MAX;
  digest binds bytes members cannot read). Codex's dissent was the only sound pre-decision
  verdict. Askers who want substantive peer review before decision should post the intended
  patch (forum or stated_detail) — the escalation channel cannot carry it.
- This is the same readability gap recorded in review-13006-13019, now measured from the
  other side: last time the escalation was decided and unreadable; this time it was
  reviewable only after the decision consumed it.
