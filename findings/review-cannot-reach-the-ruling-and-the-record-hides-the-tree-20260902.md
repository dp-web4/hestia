# Review cannot reach the ruling — and the record hides the tree

**Wake 2026-09-02 ~03:14–03:20 UTC (claude-code on CBP).** Ten notices: codex's
corroborate-or-dissent on its own `git restore` escalation (`20a452f79efa2bef`), seven
dispositions on the co-seat's slice-3 petitions, two codex review_done bindings.

## 1. A mesh-woken reviewer with every tool pre-built still lands +827s after the ruling

The review_request was queued at 03:02:20, the operator ruled at 03:05:33 (193s after
open), and my factor landed at 03:19:20 — **+827s post-ruling**, right at the corpus
median of +736s. This wake was close to a best case: the reader, `claimable.py`, the
chain walker and the daemon client all existed from prior wakes; no tooling was built on
the critical path. The latency is structural: notice→wake→drain→read→verify is minutes
while a `single_approver` operator rules in ~3. Under the current wake cadence, peer
review **cannot** reach the decision for operator-decided rows regardless of seat speed —
codex-speed was already ruled out; this rules out tooling-readiness too. If factors are
ever to inform rulings (not just audit them), the bar or the ruling has to *wait* on
invited peers, or review stays a post-hoc audit channel by construction.

## 2. The escalation record has no cwd — so a relative-path act cannot be located, only bounded

`20a452…`'s act is `git restore --worktree -- plugins/_shared/hestia_gate_mechanism.py
plugins/codex/hooks/pre_tool_use.py plugins/kimi/hooks/pre_tool_use.py`. Full text on the
wire (no cap), single command, three named files — and **unlocatable**: neither the
record nor any chain row carries a cwd, and all three paths are relative. The same bytes
are near-noop cleanup in a scratch worktree and a live-gate-source revert in the shared
tree. I filed CONCUR with that bound stated explicitly (post-state sha-verified where
visible; wt-slice clean at `fac72bf` with all three files byte-identical to the reviewed
scratchpad sources; grant consumed per `claimable.py`, not burned). This is the
"reviewer sees 22–53% of the act" problem in a sharper form: for relative-path acts the
missing dimension is not a truncated tail but the *tree*. Remedy candidate: record cwd
at open — it is known to the hook, costs one field, and turns this bound into a check.

## 3. The unclaimed grants were both marker-in-compound false positives

Of the co-seat's seven approved petitions, the five write-shaped acts (one Edit, four
`cp`+commit) were all consumed; the landed bytes sha256-match the scratchpad sources
3/3. The **two that expired unclaimed** (`927adb…`, `1c085bb…`) were both read-only test
loops — `for t in plugins/…/gate_*_test.py …` — classified as writes because marker
basenames sat inside `for`/`&&` compounds (the exact trap in
`fb_marker_path_in_compound_shell_pages_operator`, now paging dp from the co-seat too).
So in this batch, "approved-then-unclaimed" wasn't abandonment or recast: it was the
gate escalating acts whose grant the asker never needed to spend as-approved. A third
mechanism for the unclaimed-modal population (161/210), separable here only because the
acts' read-only nature is visible in their full text.

## Also on the record

- Open petitions: measured zero (`hestia_gate_pending_escalations` asked, count 0) — the
  primer's producer omitted the key again.
- Corroborate on a DECIDED row: accepted, recorded, `independence: cross_vendor`,
  witness `36f1378573437fed`.
- All ten notices answered with verified bindings (review_done to codex + nine acks).
