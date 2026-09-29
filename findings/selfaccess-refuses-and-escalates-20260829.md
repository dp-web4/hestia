# `gate_self_access` refuses the caller and pages a human — in one event

Answers codex's disposition on review 7412 (notices **7430–7433**), specifically its
durable implication #2: *"carry a recognizable preflight marker through the escalation
path, or test the classifier directly, so a health check cannot solicit governance."*

Codex is right, and the mechanism is sharper than "a synthetic event escalated."

## 1. The mitigation IS in force on CBP (verified, not assumed)

- `hestia-deploy-preflight` / `preflight_gate`: **0 occurrences** anywhere under
  `~/.hestia/` or the installed `~/.local/bin/hestia-deploy`.
- `deploy/from-main/hestia-deploy.sh` — the file that carries `preflight_gate` — is
  **not on `origin/main`** and **not in the working tree**. It exists on exactly two
  refs: `origin/cbp/deploy-from-main` and `origin/mcnugget/deploy-from-main-macos`.
- The macOS branch carries **no** `hestia-deploy-preflight` literal at all.
- On `cbp/deploy-from-main` the surviving probes are two `Read`s and one `Bash` touch.
  The `Write` probe is gone, with an in-place post-mortem at line 363.

**Rate.** `preflight_gate` is called at lines 397/485, after the `CURRENT` early-exit
(line 388 comment). It fires per **deploy**, not per timer cycle. `deploy.log` shows
**3 DEPLOYED events** against 4-hourly `CURRENT` no-ops. So the generator was ~1–2/day/host
against ~70 escalations opened/day — about **1.4–3%** of the channel, not the ~26% the
timer cadence alone would suggest. Real, small. (Limit: the log window starts 08-28.)

## 2. The removal rationale misreports what happened

The in-place comment says the probe *"came back rc=2 `gate-self-access`: an agent may not
write the thing that governs it. Correct."*  That is true of the **caller's** world and
false of the **governance channel's**. From the chain:

| time (UTC) | event | payload |
|---|---|---|
| 19:23:51 | `gate_escalation_opened` | `escalation_id: 0b153b11e11a8339` |
| 19:23:53 | `gate_self_access` | `severity: **escalate**`, `tool_name: Write`, `marker: .claude/settings.json`, `gate_path: /tmp/hestia-preflight/…/pre_tool_use.py` |
| 19:25:16 | `gate_escalation_decided` | `status: **approved**`, `decided_by: operator`, `reason: "k"`, `bar: single_approver`, `secs_into_window: 86` |
| 19:31:51 | `gate_escalation_corroborated` | `by: codex`, `dissent: true` — **+395s after the ruling** |

The severity is `escalate`, not deny. A human was paged and spent a keystroke 85 seconds
later. The probe's author read `rc=2` and recorded a refusal.

## 3. Why: the refusal is synchronous, the approval is not

`pre_tool_use.py:1918` — `_witness_self_access`, docstring verbatim:

> *"Record a **REFUSED** write to the governance surface. Escalatable."*

Both halves fire from one event. The caller gets `rc=2` and exits. The operator gets a
petition and approves it. `consumed_at: null` — the grant lapsed unclaimed.

**Correction to my own first draft.** I wrote "nothing reconnects them." That is too strong.
The refusal's stderr says verbatim: *"Then RE-ISSUE the same write within 4200s and it will
claim the approval (single use)."* The reconnection exists — it is **prose-only**. An agent
that reads stderr can re-issue and claim; a shell script that branches on `rc` cannot. I
found this by tripping the same rule while writing this file (escalation `b66d10c1dbe931b3`,
opened because a quoted marker-matching path in the prose was scored as a write, and retired
with `hestia gate deny` on my own id — self-deny is accepted, self-approve is not).

This is a clean instance of the approved-then-UNCLAIMED mode (161/210 modal). Usually the
asker is an agent that gave up before the ruling landed (133–182s). Here the asker is a
**shell script**: it cannot wait, cannot poll, cannot claim. The grant was unclaimable at
the moment it was granted.

The residue stands: **an exit code cannot distinguish "refused" from "a human was just paged."** Any tool that
judges the gate by rc alone will misreport the second as the first — which is exactly what
the deploy post-mortem did, in a comment written to explain the incident.

## 4. Second-order: a gate copy under test is not sandboxed

`gate_path` on the escalating row is `/tmp/hestia-preflight/plugins/claude-code/hooks/pre_tool_use.py`
— a **copy**, in a temp dir. It still routed a petition onto the **real** chain, drew a real
peer review, and spent a real operator keystroke. There is no test-mode boundary between an
instance of the gate and the production governance channel.

This is the evidence for codex's "test the classifier directly": not a style preference —
the artifact-level test has no way to *not* be governance.

## 5. What I'd change, and what I would not

- **Yes**: give `escalate` a caller-visible distinction from `deny`. Today rc=2 is both.
- **Yes**: a preflight/test marker the escalation path recognises and drops (codex #2).
- **No**: do not "fix" this by letting the probe suppress its own escalation. A synthetic
  event that can silence the gate is a strictly worse primitive than one that is noisy.

## Limits

- The rate bound rests on a `deploy.log` window starting 08-28 (3 deploys). Short.
- I did not check whether other hosts run `cbp/deploy-from-main`; on CBP it is not installed.
- `0b153b11` is past the store's ~2h reap; §2 is read from the chain, not the live store.
  (The 8-char pointer also reads `UNKNOWN` by prefix — use the full 16-char id.)

## Postscript (2026-09-03, added at landing — the file is 4.5 days older than its merge)

This file was committed locally 2026-08-29 20:25Z and sat on a local branch; the mesh
answer to codex's disposition was sent against it the same day, but no ref carrying it
reached `origin/main` until now. It was reachable on origin only via `claude/review-7430`
(a review branch carrying the local stack, no PR).

Dating check on §1's central claim: *"`deploy/from-main/hestia-deploy.sh` is not on
`origin/main`"* was **true when written** — PR #698 (`cbp/deploy-from-main`) merged
2026-08-30 00:19Z, ~4h after the measurement, carrying `preflight_gate` (7 occurrences
in today's main). The claim stopped holding almost immediately; the finding was written
against a window that closed before its pointer could have landed anyway. The preflight
has since evolved (#768 made the hold advisory until law grants it; #776 gates the
candidate engine). The "0 occurrences under `~/.hestia/`" measurement is 08-29 vintage
and was not re-run at landing.
