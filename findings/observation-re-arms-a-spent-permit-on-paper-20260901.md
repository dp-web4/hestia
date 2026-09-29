# Observation re-arms a SPENT permit — on paper only (2026-09-01, wake CWMCu1)

**Claim.** `EscalationStore::mark_observed` (the #667 fuse) stamps `observed_at` on a record
that has already been claimed. The stamp moves `decided_horizon()` to `now + 600`, so the
asker seat's first attributed poll AFTER its own claim answers
`observation_started_claim_window: true` beside a fresh `claim_window_secs_remaining: 600`
about a permit that `is_claimable` — correctly — refuses. Enforcement was never wrong; the
account of it was.

## Instance

Escalation `cd0f8128ee32c02f`, opened 06:06:38Z by dp's interactive session (Bash write to
`/tmp/wt-collapse/plugins/claude-code/hooks/pre_tool_use.py`, marker `plugins/*/hooks`),
approved by operator +31s (reason `k`), claimed 06:08:14Z (`consumed_at: 1788242894`).
Both invited peers (codex, kimi-code) were out of credits — the corroborate-or-dissent
notices bounced (8061, 8062) and no factor landed.

| poll (UTC) | identity | `observation_started_claim_window` | `claim_window_secs_remaining` | `permits_write` |
|---|---|---|---|---|
| 06:10:39 | `--as claude-code` (the asker seat) | **true** | **600** | false |
| 06:11:13 | `--as claude-code` | false | 555 | false |

The second row shows the countdown is real (it decrements) and was anchored at my first
poll, two minutes after the claim spent the permit.

## Mechanism (origin/main `2ce595c`, `core/src/server/gate_escalation.rs`)

```
mark_observed:  plugin_id == caller && observed_at.is_none() && Approved && bar_met()
is_claimable:   Approved && bar_met() && consumed_at.is_none() && now < decided_horizon()
```

Two four-conjunct predicates that share three conjuncts. The one `mark_observed` lacks is the
one `claim()` sets. Its own comment says observation is only meaningful about "this record
could become claimable minus the clock" — a claimed record cannot become claimable at any
clock, so the omission contradicts the stated rationale, not just the observed behaviour.

`claim_window_secs_remaining` is a pure clock over `decided_horizon()` and does not read
`consumed_at` either (already on record: `findings/…poll-note…`, the "spent permit
publishes a positive countdown" case). What is new here is that the clock is **restarted**
by the poll on a spent row, and the poll **says so**.

## Why it matters

`observation_started_claim_window: true` is the one field on the poll that tells the asker
"your window is measured from THIS moment". Said about a spent permit it is the inverse of
[#667](https://github.com/dp-web4/hestia/issues/667)'s text problem: there the note said
"dead" about a grant that was revivable; here the field says "started" about a window that
cannot exist. A peer reviewing "which approval on this marker was spent?" reads a true
`observation_started_claim_window` + 600s and infers an unspent grant; `consumed_at` is the
only field that contradicts it.

Second, smaller: **no test in the tree calls `mark_observed` or reads `observed_at`**
(`grep -n observed_at` hits the field, `decided_horizon`, two constructors and the guard;
nothing under `#[cfg(test)]`). The #667 fuse shipped with its contract in prose.

## Fix (this branch)

- `mark_observed` gains `&& e.consumed_at.is_none()` (one line, rationale comment at the
  guard).
- `observation_does_not_revive_a_spent_permit`: first test of `mark_observed`. Spent row →
  `false`, no stamp, countdown still anchored at the grant; unspent control on the same
  store → `true`, stamp, countdown restarts (the #667 contract, now pinned).
- Sabotage arm: remove the conjunct → the first assertion is red.

Test result (2026-09-01 06:18Z, `cargo test --lib observation_does_not_revive`):

- green arm: `1 passed; 0 failed` (`GREEN-ARM rc=0`)
- sabotage arm (`&& e.consumed_at.is_none()` replaced by a comment): panicked at the first
  assertion, `a spent permit has no claimable future to observe` (`SABOTAGE-ARM rc=101`);
  conjunct restored via `git checkout` before commit.
- full `cargo test --lib` (2026-09-01 06:32Z, `hestia/.wt/observed-spent`): `739 passed; 0 failed; 1 ignored` (the ignore is pre-existing, `criterion_edge_resolution_populates_the_lct_on_the_row`).

## What this does NOT change

The running daemon (`v0.0.4-559-gda0613b`, built and restarted 2026-08-31 20:18:46 PDT)
predates this branch; merging changes nothing until a rebuild + restart
(`ref_deployment_index`: shipped ≠ in force). The #667 revival of an UNSPENT grant is
untouched and still open as a design question.

## Conduct note

I produced this instance by polling my own seat's decided row `--as claude-code`, which my
own record (`findings/review-7325.md`) says not to do. "Decided and spent" felt exempt; it is
not — the stamp still lands, and this file is what the stamp looks like.
