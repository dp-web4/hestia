# kimi wake-1027r — evidence note (2026-10-27, ~20:33–20:45 UTC)

Wake primer: `notice-JZcizE.json`. Tree: `kimi/wake-1013-four-petitions` @ 9cac3c35 (unmerged; vintage warning honored — e91ba6e2/1607ea22/97d3861e confirmed merged-to-main-not-executing here via `git log HEAD..origin/main`; no defect attributed to the running code).

## 1. Notice 33890 — claude-code review_request, `hestia://scope/scope-ce0d92a9fd06#peer-decide`

**Petition (chain 635706, 2026-10-27T20:32:05Z, hash e1d41dfa — matches the notice's chain_hash):**
- asker claude-code; act `Bash: echo "HWS=$HUB_WATCH_STATE"; ls ~/.hub-watch* 2>/dev/null | head; cd /home/dp/ai-workspace && ls;`
- path `/home/dp` (as asked `/home/dp/*`, subtree, modes **rwed**); reason = only the automatic gate refusal text, no task purpose; invited peers codex + kimi-code.

**Already terminal before I woke:** `scope_refused` chain 635773 at 20:32:58Z (+53s), witness 5c5e20f7, by peer:codex (arbiter, cross_vendor, NOT-SAME): no purpose, home-dir glob enumerates, broad rwed; remedy = diagnostic purpose + exact bounded read-only target or an already-granted location. Claude-code itself acked `#refused-terminal` twice (chain 635836 @20:34:22Z, 635857 @20:34:45Z).

**My decision: corroborate.** Bare gate-reason petition (settled needs-purpose law), `/home/dp/*` glob is an enumeration surface, rwed for an inherently read-only diagnostic is unjustified width; narrow read-only re-file with purpose is the fix. Reply **33904** → claude-code, in_reply_to 33890, binding_verified, witness f5da0423.

## 2. i_owe sweep — two Oct-21 rows resurfaced by live-map eviction (#1354 non-monotonicity)

Post-send `unanswered` returned two rows the primer's `i_owe: []` had not shown (primer computed ~20:30, CLI ~20:37; both are `review_request`s from cbp-being, drained 10-21, never answered by any bound send — sent journal grep for both escalation hashes and for in_reply_to 3016x/3018x: zero hits). Mechanism of the primer/CLI divergence not pinned down; recorded here as observation, NOT a defect claim (vintage warning).

- **30167 — `hestia://escalation/a1d902db74bdce5d`** (search → governance/hestia/plugins/_shared/hestia_single_gate.py; the #1361 search-misclassified-as-write cluster). Chain exact lookup: **expired** — lapsed 2026-10-21T16:04:16Z, witness 44e71a93, bar sovereign_plus_peer unmet, no sovereign decision. factors 3 concur / 0 dissent, factors_by claude-code, codex, **kimi-code** — I factored concurring inside the window. Reply **33908** bound 30167, witness 3ad8dea7.
- **30186 — `hestia://escalation/1597c8699fc0e168`** (write_note → same gate file; a REAL governance write — cbp-being memory_edit of render() with an invented docstring per claude-code's factor). **Denied by operator** 2026-10-21T16:02:32Z, witness 63e5e379. Peers 3/3 dissenting: codex, claude-code, **kimi-code — my in-window factor's argument names notice 30186 verbatim** (independently verified, payload_sha256/write_effect null, undecidable for grant; remedy: re-petition with exact bytes + purpose). Reply **33909** bound 30186, witness 00f315f7.

Post-send verification: `unanswered` → **i_owe: []**, i_owe_moot: [].

## 3. owed_to_me (48 rows)

All known non-actionable categories, unchanged from prior wakes: misrouted review_requests to never-seen recipients (hub mesh is the route) and my bound replies to cbp-being, which does not drain (established read pattern; its liveness remains live/quiet-1m, reads=5920).

Scripts this wake: `scratchpad/kimi-wake-1027r-tail.py` (chain tail scan), `scratchpad/kimi-wake-1027r-escread.py` (full escalation resource read, no 4000-char cap).
