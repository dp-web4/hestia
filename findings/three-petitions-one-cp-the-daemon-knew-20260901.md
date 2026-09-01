# Three petitions for one `cp` — and the daemon knew after the first

**Seat:** claude-code (CBP), mesh wake 2026-09-01 15:17Z · notices 8302, 8314 (dispositions
`c9af97ae9c0140bb`, `364b94dd28300468`) · records read through `resources/read` (the
non-fusing route), acts recovered from the asker's own transcript, census via
`tools/chain_walk.py` (10,000-event page, 2026-08-29T19:15Z → 2026-09-01T15:20Z).

## 1. What happened, to the second

One sibling claude-code session (`888f190a…`) wanted one write: copy a regenerated
`install-members.new.sh` over `deploy/install-members.sh` in its worktree. That is a
governance marker, so the gate refuses and escalates. Here is every attempt:

| UTC | act (shape) | gate | petition | operator |
|---|---|---|---|---|
| 14:53:43 | `cp A B` | deny, **WITNESS FAILED**, no petition | — | — |
| 14:54:00 | `cp A B` (same bytes) | escalate | `db0b02` opened | approved 14:54:11, reason `k` |
| 15:01:08 | `hestia gate poll db0b02` → `approved` | | | |
| 15:01:38 | `cp A B && echo LANDED` | escalate | `c9af97ae` opened; **`db0b02` listed live, 153s left** | approved 15:01:51, `k` |
| 15:02:31 | `cp A B && echo LANDED` | **claimed** (40s after decision) | | |
| 15:04:51 | `cp A B && echo LANDED` (source regenerated) | escalate | `364b94dd` opened | approved 15:05:02, `k` |
| 15:06:13 | same | **claimed** (71s) | | |

Four attempts, three petitions, three operator keystrokes, two claims. The write that
landed is the 15:06:13 one (`install-members.sh` mtime 15:06:13Z; commit `39a3fb9` on PR
#747 at 15:06:58).

`db0b02` burned. Not by asker death, not by a lapsed clock — the asker polled it, read
`approved`, and 30 seconds later re-issued **with `&& echo LANDED` appended**. Since #539 the
claim is keyed on `sha256(command text)`; the appended echo is a different digest, so the
gate opened a fresh petition instead of spending the approval that was 153 s from its
window's end. The refusal the asker had read said *"RE-ISSUE the same write"*. It re-issued
the same write. It did not re-issue the same bytes.

## 2. The daemon knew, and told the chain

The `gate_escalation_opened` payload of `c9af97ae` carries:

```json
"decided_awaiting_claim": [{"escalation_id": "db0b02256b3eb7d5",
                            "act_digest": "c887c034…", "marker": "deploy/install-members.sh",
                            "claim_window_secs_remaining": 153}]
```

`opened_payload` (`core/src/server/handler.rs`) has computed this since #366, under the
comment *"CLOSING THE LOOP FOR A LIVE SEAT … the refusal answers the question it just
provoked: what of mine can I already spend?"* It is written to the **chain**. The **response**
the claim door returns to the hook — the one surface the refused member is certainly
reading — does not carry it (`claimed`, `permits_write`, `escalation_id`, `expires_at`,
`decide_within_secs`, `retry_within_secs`, `bar`, `invited_peers`, `invitations`,
`asker_basis`, `how_to_decide`, `how_to_wait`, `then`). And no seat hook reads it: `grep
decided_awaiting_claim plugins/` → 0. The field was computed *for* a live seat and delivered
*to* a ledger the live seat does not open at refusal time. Two lines below it in the same
function the code warns: *"An invitation nobody is told about is a label."*

The same is true of `how_to_wait`. dp asked on 2026-08-27 for the refusal to tell the asker
how to wait; the daemon has returned `how_to_wait` pointing at `tools/await_escalation.py`
since `ee56f93` (#667). `grep how_to_wait plugins/` → 0 — claude-code, codex and kimi print
`how_to_decide` and nothing else from the envelope. The sibling never saw the word
(`grep -c` over its transcript: 0) and polled with `hestia gate poll` 16 times, the primitive
`await_escalation.py`'s own docstring says does not work.

## 3. How often (census)

Over 68 opens in the page:

- **21** (31%) opened while a same-seat approval was still claimable.
- Those 21 listed **39** live approvals. **4** were later claimed. **35 burned.**
- 61 approvals in the page, 23 claims (38%) — the approved-then-unclaimed modal outcome
  the earlier findings describe, now with one of its mechanisms named: **the asker edited
  the command between the petition and the re-issue.** Each burned row is an operator
  keystroke spent for nothing and, since the operator has never said no (now 268/268 on this
  seat's window), a second keystroke to follow.

The `chain_walk` reader pages 10,000 events; the span above is what that page covered on
this day. It is a window with a drifting left edge (see `hop budget is not a window`) — the
driver is three lines and the numbers reproduce on the same page, not on a different one.

## 4. The listing can lie — one row in the census does

`decided_awaiting_claim` is built from `claimable_for(plugin_id, now)`:

```rust
e.plugin_id == plugin_id && e.act_digest.is_some() && e.is_claimable(now)
```

`claim()` spends on:

```rust
e.plugin_id == plugin_id && e.marker == marker && bound == asked && e.is_claimable(now)
```

One conjunct apart — `marker`. The comment above `claimable_for` quotes the four-conjunct
predicate and the filter beneath it implements three; the comment in `opened_payload`
promises *"same predicate `claim()` spends against, so this cannot advertise a claim that
would fail."* The census has exactly one row where the new open carried the **same digest**
as a listed live approval, and it is the counterexample: 2026-08-31 17:13Z `7079b9f6`
(marker `pre_tool_use.py`) approved; 17:18:41Z the same bytes came back classified under
marker `plugins/*/hooks`, `033e052e` opened with `7079b9f6` listed at 289 s, the claim
missed on the marker, dp approved `033e052e` too, `7079b9f6` burned. Same member, same
digest, same five minutes, two keystrokes. Whether the marker spelling moved because the
gate was redeployed between the two attempts (that seat was landing the collapse that
afternoon) or because two rules match the path, the listing said *spendable* and the spend
said *no*.

## 5. A fourth keystroke, mine

While reading `/tmp/wt-collapse` I ran a compound shell line (`cd … && { git status; …; ls
deploy/install-members.sh; sha256sum … }`). Read-only, every command in it. The marker
basename inside `&&`/`{ }` is a WRITE to the gate — the exact trap my own memory names and
that has paged dp three times before. `f470e81a3851475a` opened at 15:20:22Z; I moved to
retire it and got *"already decided (Approved); decisions are single-shot"* — dp had
approved it at 15:20:49Z, 27 s after open, on a 220-char view that showed `git status`,
`git log`, `ls`, `sha256sum`. I did not re-issue: the act needed no approval. That row will
expire approved-and-unclaimed, and it is a third mechanism for the modal outcome, after
asker death and command-text edit: **a false positive the asker declines to spend.**

## 6. What this changes

- **Daemon (PR with this finding):** the claim-door refusal response now carries
  `decided_awaiting_claim`; `then` says *byte-for-byte, under the same marker, keyed on
  sha256(command text)*; the two comments now state the three-vs-four conjunct gap with the
  counterexample instead of denying it.
- **Hooks (#772, not a PR — a seat cannot ship its own gate):** print `how_to_wait`; print
  the daemon's `then` instead of a hardcoded *"RE-ISSUE the same write"*; when the new
  field is non-empty, say *"you already hold approval `<id>` for `<digest[:8]>` under
  `<marker>`, N s left — re-issue THOSE bytes"*. This is the same shape as #770 (the
  `how_to_decide` line is refused as typed): the daemon composes the right remedy and the
  hook prints a different one.
- **Not changed:** `claimable_for` keeps its cross-marker scope. Adding the marker conjunct
  would make the listing honest at the cost of hiding an approval a member could spend by
  re-issuing under the marker it was granted on; rendering `marker` with the row (already
  done) plus saying so in the response is the smaller move. A test that pins *"a listed
  row is spendable under its own marker"* would be the next one to write.

## Refuted, untested, held

- *"Only a dead asker burns an approval"* — **refuted**: `db0b02`'s asker polled it and
  read `approved` 30 s before burning it.
- *"`decided_awaiting_claim` reaches the live seat"* — **refuted** on the response schema
  and on `grep` over three hooks.
- *"The listing cannot advertise a claim that would fail"* — **refuted** by one row; whether
  the marker drift on that row was a redeploy or a dual match is **untested**.
- The census rate is **one page, one day**; the 31%/35-burned numbers are not a trend.
