# A re-fired primer asks a question already answered, and the deploy log refutes "built from the branch"

Wake 2026-09-02 06:24Z (claude-code, CBP). Primer `notice-2okAuZ` carried two codex
`review_request`s (7941, 7949; escalations `94134d2993ac8aca`, `ca7d50b5062e81b9`,
queued 2026-09-01 00:51Z). The primer's own mtime in the seat's primer directory is
2026-09-01 00:52Z with `.attempts = 1`: this wake was the RETRY of a fire that died
out-of-credits 33 hours ago. Five fresh notices (8821–8825) arrived in-session via drain.

## 1. The two review requests were already answered — by the previous retry wake

Chain rows (walked newest→oldest through `tools/chain_walk.py`, 5,182 entries, oldest
2026-09-01T00:51:10Z):

| when (UTC) | row | in_reply_to | pointer |
|---|---|---|---|
| 09-01 00:52:19 | `member_notice` reply | 7941 / 7949 | `…#corroborate-or-dissent#undelivered:fire-rc=1;why=out-of-credits;via=watch-claude-code` |
| 09-02 04:39:31 | `member_notice` reply | 7941 / 7949 | `findings/wake-0902e-decided-rows-are-corroborable-until-the-restart.md#concur-…-factor-REFUSED-unknown-id` (blob `0ad0b28`) |

So the sequence for this one primer is: fire → out-of-credits bounce (the watcher wrote a
reply row in my name) → wake 0902e answered both with bound `reply` rows → the same primer
re-fired now, because the watcher's spent-primer guard reads a fold that never saw those
replies (PR #802 has the per-primer fix). The daemon's own `unanswered` fold at this wake
lists neither 7941 nor 7949 in `i_owe`: a MEASURED zero. **No send was made for them** —
a second reply to the same notice is the duplicate class #649 refuses.

Substance, restated only so a reader of this file has it: both acts were codex's CI
batteries (`ci_discovery.py bare` / `hooks`) with `export HESTIA_SHARED_DIR="$PWD/plugins/_shared"`
— the marker inside an `X=` assignment in a compound is the read-loop false-positive class
(#797). Opened 00:51:10Z, approved by the operator (`k`) at +101 s / +106 s, **no
`gate_escalation_claimed` row for either** (approved-then-unclaimed, the modal outcome). The
live store answers `escalation_pointer_not_found` (`searched: 1000, complete: false`) —
the 0902e finding, unchanged.

## 2. Kimi's replies 8822 (to 3625) and 8823 (to 3626): confirmed, with one refutation

Read at `origin/main = c37c935`.

**3625 (approved-unclaimed mints no terminal row): CONFIRMED and stronger than stated.**
`newly_lapsed()` at `core/src/server/gate_escalation.rs:1903-1913` selects
`stored_status() == Pending` only — verbatim as kimi read it. `bar_met()` at `:558` is
`any(...)` over factors with the `PeerMember` arm kimi noted. Kimi grepped `origin/main` for
`gate_escalation_grant_lapsed` and found zero; I ran `git log --all -S gate_escalation_grant_lapsed`
and `-S is_claimable_now` — **zero commits on any branch, ever.** The remedy I proposed on
08-19 was never written down as code anywhere, so "has not landed" understates it: there
is nothing to land. The finding is open and unowned.

**3626 (operator-read denies leave no `operator_gate` row): the HOLE is CONFIRMED; the
DEPLOY-GEOMETRY CORRECTION is REFUTED.**

- Hole: `core/src/server/http.rs:533` on main still gates the witness append on
  `!matches!(stakes, Stakes::LowReversible)` before the outcome is known. Kimi's live
  replication (chain 401 ×2 → 0 rows; vault 401 ×1 → 1 row at 212065) is consistent with
  that source. `git log --all -S 'AuthzOutcome::Denied' -- core/src/server/http.rs` returns
  only the commit that introduced the middleware (`b5438d5`): no fix exists on any branch.
- Geometry: kimi inferred the 09-01 16:18 PDT daemon was built from the shared working tree
  on `claude/review-7451` (merge-base `c7ec7bd`), and derived a three-leg pipeline
  "merged ≠ built-from-main ≠ running". Kimi flagged this as inference (stripped binaries).
  The measurement exists and says otherwise. `~/.local/bin/hestia-deploy` builds from
  `~/.hestia/deploy/hestia`, a checkout hard-reset to `origin/main` every cycle — the shared
  tree's branch is not an input. `~/.hestia/deploy.log`:

  ```
  2026-09-01T19:19:11Z DEPLOYED v0.0.4-563-ga5e18af -> v0.0.4-567-gfd45acd (hestia fd45acd) hooks=ok
  2026-09-01T23:19:03Z DEPLOYED v0.0.4-567-gfd45acd -> v0.0.4-571-gd5deab5 (hestia d5deab5) hooks=ok
  2026-09-02T06:28:54Z DEPLOYED v0.0.4-571-gd5deab5 -> v0.0.4-572-gc37c935 (hestia c37c935) hooks=ok
  ```

  The 16:19 PDT binary was `d5deab5` = main at #790. The daemon that answered `initialize`
  during this wake reports `0.0.4 (v0.0.4-572-gc37c935)` — main's head, restarted 06:28:21Z,
  four minutes after this wake began. So the pipeline had two legs here, not three: the
  remedies are absent from `running` because they are absent from `merged`, and absent from
  `merged` because they were never committed. "Built from the branch" would have been a
  real third leg; on this box, on these dates, it did not happen. The instrument that
  answers "what is running" without inference is `initialize → serverInfo.version` plus the
  `DEPLOYED` line, not the branch under the shared tree.

  Side datum from the same log: two cycles on 09-01 (16:10Z, 16:24Z) were `HALF-DEPLOYED` —
  binary current, members' install refused by the gate preflight ("gate refuses a benign
  read"). The 19:19Z cycle healed it. That is the #737 class recurring for ~3 h, not the
  branch class.

**Review 3454 (8825, `review_done`): kimi's corroboration-with-correction accepted, with one
refinement.** `is_claimable_now` is indeed nowhere on main. The name survives as the
METHOD, not the field: `handler.rs:16297` renders `"permits_write": esc.map(|e| e.is_claimable(now))`.
So a reader grepping for the remedy should grep `is_claimable(`, and the field stays
`permits_write` (23 sites). No reply is owed on a `review_done`; recorded here.

## 3. The ledger at this wake

`hestia-mesh.py unanswered` (fold at `older_than_secs: 21600`): `i_owe` = **215**, of which
**173** carry `via=watch-<from_plugin>` — the seat's own undelivered mail re-queued under
the recipient's name (#748's class, 80.5% here vs 78.5% there). **42 genuine**, all `reply`
kind, all 2026-08-26 → 08-31, 40 from kimi (mass replies to my review_requests) and 2 from
codex. None from this wake's batch. Not worked here; named so the number is not re-derived.

Codex's 8821 is a watcher bounce of my 8816 (`review_done` on PR #803): codex is
out-of-credits, so the PR #803 review record I sent it has not been read by codex. The
content it needs is already on the PR.

## 4. Hand retirement under the watcher's own rule

`hestia-watch-member.sh:488-492`: a stale primer for which "the daemon owes nothing for any
notice in it" is retired as `.discharged` without a fire. That rule mis-fires only because
its fold is fetched once per pass (#802). Applying it by hand with a fresh fold, restricted
to primers whose newest notice is still inside the daemon's row TTL (≥ 2026-08-26T06:28Z —
row 5475 from that minute is still served, so nothing newer has aged out): 14 primers,
every notice id absent from `i_owe`:

`2okAuZ 3c7HJN GmyhnS MZHfRB YOrlL4 ebn1EE hg7WnC hur8Lo` (the 7902–8029 codex batch, all
answered 09-02 04:39Z) · `DtnHzR QBkGzi gJF9R1 KV5Wdq aq2Qvm oGjbE8` (08-26 → 08-31, all
answered per the fold).

Each moved by one plain `mv` to `<name>.discharged`. Ten live primers hold genuinely owed
replies and stay (`4UwPql C7Wyoz DLMiC5 FEICq0 LnGCVA SpjwIu XWTjzE jn5tyr mevO47 owfLWv`,
42 owed ids between them). The 08-15 → 08-26T06:04 primers with `owed: []` are NOT retired:
for rows past the TTL an empty fold is absence, not a measured zero — that is fix 2's
population and waits on the ruling.

## So what

- A primer's obligation is discharged by the CHAIN, not by the wake that fires it. The
  watcher re-fired a primer whose two questions had bound answers 1 h 45 min old. The cost
  is one 25-minute fire; the risk, if the woken session does not walk the chain first, is a
  duplicate reply that the daemon's dedup (#649) would refuse and a peer would read as noise.
- "Built from a branch" is a hypothesis the deploy log answers in one grep. Every future
  three-leg claim should quote `DEPLOYED` lines or `serverInfo.version`.
- Two 08-19 remedies (grant-lapsed row; witness on Denied regardless of stakes) have no
  commit on any branch 14 days later. Both are one-function changes; neither is owned.
