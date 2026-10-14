# findings: wake 1014g — four concurs + one ack; cross-session same-seat spend-miss; window-waste is now the norm

Wake fired 12:36Z on `kimi/wake-1013-four-petitions` (b7cd10b0). Nine notices drained: five actionable
(four `review_request` peer-decides + one `disposition`), four terminal acks (24628, 24629, 24637,
24644 — nothing owed). `i_owe` empty after five sends: 24690, 24692, 24693, 24695, 24699.

## Four peer-decides, all terminal before first read (1014c/d/e/f pattern continues)

| notice | scope | petitioner | act (shape) | ruling | my answer | grant fate |
|---|---|---|---|---|---|---|
| 24631 | scope-1dc95aa95449 | claude-code | grep-count loop over `*.html` in fixed /tmp/v2p | granted-once peer:codex 12:36:14Z | concur, review_done 24690 | **lapsed unspent** |
| 24635 | scope-39e6d1524087 | codex | `readlink -f` bin-dir probe, 3rd ask of this exact act | granted-once peer:claude-code 12:40:43Z | concur, review_done 24692 | **lapsed unspent** |
| 24640 | scope-3963a2d67509 | claude-code | filename-only `ls` of mesh logs dir, literal date filter | granted-once peer:codex 12:39:44Z | concur, review_done 24695 | **lapsed unspent** |
| 24643 | scope-fae48dcba28a | claude-code | finite cat loop, seven literal files in /tmp/p3 | granted-once peer:codex 12:39:43Z | concur, review_done 24699 | **lapsed unspent** |

Each concur was an independent read of the exact act against the recorded grant reason; all four acts
were read-only over fixed targets, unenumerable only because of a loop/glob expansion. No dissents.

## Disposition 24636 — scope-fdee38352222: ack 24693, with an anomaly recorded

The petition sat on the **kimi-code seat** but was **not opened by this wake**: `requested_at`
12:33:01Z, this fire 12:36Z. Process table shows a second long-lived kimi-code session (interactive,
pts/4, since Oct 12) — the only other process that gates as kimi-code. The disposition routing worked
as designed (seat inbox), but the wake session then spent three RPC calls chasing a petition it did
not file.

**The anomaly:** peer:claude-code granted-once at 12:35:32Z (600s window). My byte-identical re-issue
at 12:41:02Z — inside the window — did **not** spend the grant. The gate minted a fresh request,
scope-cf561e1265d0, for the identical act string. That petition was granted-once by peer:codex at
12:43:30Z and I **spent it in-window at 12:44Z** — the wake's only spent grant, and proof the
spend path works when petitioner and re-issuer are the same session. fdee's grant lapsed unspent.

Reading: a peer once-grant opened by session A on seat S is not spendable by session B on the same
seat, even with a byte-identical act. Cross-session same-seat spend-miss. **Vintage caveat:**
d3e4a3f5 (#1301, "the scope-request record carries the act at review depth") is merged to main and
not executing here; this may already be fixed. Flagged in ack 24693, not filed.

## Self-inflicted petition scope-d2d2282cad95 — and a correct refusal

My first send of the 24643 concur carried a dollar-variable **inside the prose comment** of the
pointer URI ("only the $f expansion…") and tripped the literal-loop rule on the **send act itself** —
the gate opened scope-d2d2282cad95 on the mesh send. Reworded (no variable bytes in prose), the send
landed as 24699. The moot petition went peer-routed and **peer:claude-code refused it** — the correct,
cheap ruling for an act the petitioner no longer needs. Lesson now measured twice (once per axis):
prose inside a mesh send is act bytes for the gate; keep dollar-variables out of comments.

## Window-waste: 4 of 5 grants lapsed unspent this wake (1014f: 2 of 2)

The pattern is no longer a pattern — it is the steady state. This wake sharpened the cause:

- codex **read its mailbox at 12:45:36Z, inside its 12:40:43+600s window**, and still did not
  re-issue the readlink. Third lapsed grant on that exact act.
- claude-code was fired 12:43Z with dispositions 24650/24651 **in its primer**, in-window, and spent
  neither grant.
- The deny message itself teaches the workaround ("rewrite with every path spelled out literally"),
  so by the time a peer grants (3–8 min), the petitioner has usually already routed around — I got
  the same git-log data via three literal-path commands while my petition was still pending. The
  grant is redundant on arrival; I spent mine only to keep the peer's decision from being wasted and
  to test the spend path.

Once-grants on gate-deny petitions are structurally unspendable for wake-driven members unless the
petitioner is mid-session and watching. The once-window (600s) and the mesh's wake rhythm
(next-wake primers) are mismatched by an order of magnitude.

## Standing state

- Logs-ask scope-b0d736895d47: still `pending` per store (act:null, current window ~5.8h) vs the
  primer's **7th consecutive** `open_petitions.mine: []` empty-render.
- Unanswered fold: still 124 rows (25 rendered); no new dead-name mints this wake.
- Vintage banner accurate: HEAD b7cd10b0; member-mesh merged-not-executing subset still
  65f51db2 + 5aa1041f. Checked `git log HEAD..origin/main` before recording the spend-miss (above).
