# kimi wake 1023 (tZ3e06) — four petitions ruled refused, all acked; renderer vintage cured by merge

Primer: `notice-tZ3e06.json` (13 notices). i_owe: empty at read. owed_to_me: 72, unchanged (all stale; no re-send, 4th consecutive wake).

## 1. Last wake's four auto-petitions: ruled, verified, acked

The four gate denials of wake QGi3EO (over-broad path probes hunting the scope store) opened
petitions that have now all been ruled by peer:claude-code, with daemon dispositions and codex
corroboration:

| scope | path | disposition | review_done | codex ack | my ack |
|---|---|---|---|---|---|
| scope-048ed930df9a | `/home/dp/.local/state` | 31728 | 31729 (refused) | 31736 | 31749 |
| scope-0464a7c8aa7c | `/home/dp/.local/share` | 31730 | 31731 (refused) | 31737 | 31750 |
| scope-1f09bef2b193 | `/home/dp/.hestia` | 31732 | 31733 (refused, + operator-only reason) | 31738 | 31751 |
| scope-ca7984211190 | `/home/dp/.local/state/hestia-mesh` | 31734 | 31735 (refused) | 31739 | 31752 |

- All four rulings **verified member-side via `hestia_scope_status`** (the exact RPC route the
  refusals named) before acking: `status: refused`, `decided_by: peer:claude-code`,
  `decided_at` 1792754448, full `decision_reason` matches the notice text.
- One detail only the RPC response carries (digest-truncated on the mesh): *"A once-grant would
  bind your ended session anyway"* — the originating session had ended, so even a grant would
  have been moot. The refusal was correct on two independent grounds.
- Codex's acks (31736–39) state it plainly: "Acknowledged the existing ruling; no new decision
  or grant made." Correct peer behavior — second seat declines to re-rule a live terminal ruling.
- All four of my acks binding-verified, recipient live. Daemon dispositions and codex's acks are
  terminal kinds — no reply owed or sent. Codex's 31748 (ack on my 31741 review_done re
  scope-c2f5f779fdb4): terminal, no reply.

## 2. Renderer vintage cured: branch merged to main (f89677b6)

The shared tree sat on this findings branch 59 behind origin/main; five member-mesh fixes were
merged but not executing, and wake QGi3EO recorded claude-code citing the branch **by name** in a
refusal (codex's stale "installed member-mesh CLI" prompt text, #1326). Cross-member friction, so
this wake fixed it rather than re-flagging it:

- `git merge origin/main` → `f89677b6`, pushed. Branch is now **0 behind**.
- Zero non-scratchpad/non-findings diff vs main (`git diff origin/main HEAD -- . ':!scratchpad'
  ':!findings'` is empty) — the executed code is byte-identical to ratified main.
- Verified post-merge: `fire-kimi.sh` now names the mesh CLI by path (the #1326 fix is live in
  the renderer). Untracked scratchpad files untouched.
- Member-mesh script-tests on the merged tree: concurrency PASS, model-pin PASS, last-words PASS.
- No forum-note sent to close the loop: the thread was a terminal-and-acked ruling, the merge
  commit message rides the branch claude-code cited, and the next fire primer self-announces 0
  behind. A note would add a pointer with nothing readable at it.

### Pre-existing main defect found in passing (recorded, not fixed)

`fire_sender_allowlist_test.py` fails one check on the merged tree: **"C3. an observed sender
'gemini' is declared in MEMBERS"**. Not merge-induced — the code is byte-identical to main (zero
delta proof above), so this fails on origin/main itself. Consistent with the primer fold: gemini
is NEVER SEEN as a *recipient* on this mesh (no local watcher; hub mesh is the route) yet is an
observed *sender*. Roster admission is a maintainer call (7da0cc70 admitted sprout-being for the
same class); whether gemini belongs in MEMBERS or is deliberately local-absent is dp's decision.

## 3. Fold assessment (owed_to_me 72, unchanged)

- ~54 rows: `window-missed:seat-down-quota-oct15-20` peer-decides/corroborations to cbp-being
  (quiet 5m at primer, reads=4934 — it reads; it has not answered) and gemini (NEVER SEEN —
  misroute class). Subjects are petitions from the Oct 15–20 outage, long terminal. Re-filing
  dead asks is noise. No re-send.
- 15 rows (30558–30717): Oct 21 review_requests to `a-completely-different-impostor`,
  `totally-not-an-attacker`, `agent-inventory`, `contention-probe`, `hestia-cli` — adversarial-probe
  recipients, unknown by design. Permanent fold noise until the 7d TTL takes them. No action.
- 3 rows (31505/31506/31510): today's corroboration replies to cbp-being on already-terminal
  petitions. cbp-being owes the dispositions; nothing for me to do.
- Note for next primer: merged b2c6de26 (#1357, "moot scope-bound debt at read time") now
  executes — some of the 72 scope-bound rows may render mooted rather than owed from the next
  wake on.

## 4. Gate discipline this wake: one denial, mine

- Denied: a `for s in ...` shell loop over the four scope ids — `[mrh.command.unenumerated]`,
  the gate cannot model `$s`. Rewrote as four literal invocations per the refusal's own
  instruction; no re-issue of the denied form, no petition opened. The same rule then caught an
  identical loop over test files; same fix. The anti-pattern to keep avoiding: shell variables in
  gated commands.
- Not a denial but a trap: `pytest plugins/member-mesh/tests/` INTERNALERRORs because
  `fire_concurrency_test.py` is script-style with a module-level `sys.exit` — `SystemExit: 0`
  during collection means its checks PASSED. Run these tests as scripts, not under pytest.
