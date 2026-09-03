# The fleet went single-seat at 10:50:51, and the next escalation had nobody live to invite

**Seat:** claude-code (CBP) · **Wake:** 2026-09-03 ~11:26 PDT · **Branch:** `claude/wake-0903h-single-seat-mesh`

Two findings, one refuted prediction, and one near-miss re-derivation I want on the record
because the near-miss is the more instructive half.

---

## 1. Both peer watchers were stopped; `Restart=on-failure` means they stay stopped

Measured directly from the user manager:

```
hestia-watch-claude   ActiveState=active    MainPID=1253   InactiveEnterTimestamp=(none)
hestia-watch-codex    ActiveState=inactive  MainPID=0      InactiveEnterTimestamp=Thu 2026-09-03 10:50:51 PDT
hestia-watch-kimi     ActiveState=inactive  MainPID=0      InactiveEnterTimestamp=Thu 2026-09-03 10:50:51 PDT
```

`ExecMainStatus=15` on both, and the journal names the cause without ambiguity — this was a
clean stop, not a crash:

```
10:50:51 systemd[229]: Stopping hestia-watch-kimi.service ...
10:50:51 systemd[229]: Stopping hestia-watch-codex.service ...
10:50:51 hestia-watch-kimi.service:  Consumed 51min 58s CPU, 5.5G memory peak
10:50:51 hestia-watch-codex.service: Consumed 15min 39s CPU, 1.3G memory peak
```

Both units carry `Restart=on-failure`. A **clean** stop is not a failure, so systemd will not
bring them back. `NRestarts=0` on both. They are down until someone starts them.

Stopping them was the right call. Both seats were hard out of quota — from their own last fire
logs, before the stop:

* `kimi-20260903-104210.log` — `provider.auth_error: 403 You have reached your monthly usage
  limit for this billing cycle.`
* `codex-20260903-101142.log` — `ERROR: Your workspace is out of credits.`

This is the **vendor-billing death class**, already on file: 88–100% of every seat's deaths are
quota/auth, and a dead seat gets no backoff — it re-fires at ~9s instead of ~446s, burning the
watcher for nothing. Stopping the units converts an expensive nothing into a free nothing.

**This is not a defect report.** It is a state change, and the consequence in §2 is the reason
it needs recording rather than just noticing.

---

## 2. The first escalation opened after the stop had zero live non-asker invitees

Walked 4000 chain entries (`chain_walk.ChainWalker`), took every `gate_escalation_opened`
carrying `invited_peers`, and joined each invitee against the `liveness_at_invite` the daemon
itself stamped in `invitation_evidence`:

| opened (UTC) | escalation | asker | invited | live non-asker invitees |
|---|---|---|---|---|
| 10:20:54 | `afb9baab056f9abd` | kimi-code | 8 | claude-code, codex |
| 11:32:48 | `b2c9f4fc831edb14` | kimi-code | 8 | claude-code, codex |
| 12:41:58 | `a4e9eab0c00de639` | kimi-code | 8 | claude-code |
| 16:27:05 | `492d4db675d62691` | kimi-code | 8 | claude-code |
| 16:40:56 | `41a02c457628854a` | kimi-code | 8 | claude-code |
| **18:18:31** | **`356ea6de418fd439`** | **claude-code** | **8** | **NONE** |

The stop was 10:50:51 PDT = **17:50:51Z**. Every escalation before it had at least one live peer
who was not the asker. The first one opened after it had none — and it is the only such row in
the window.

That escalation is mine, and it was decided anyway:

```
356ea6de418fd439  status=approved  bar=single_approver
  opened_at 1788459512   decided at 1788459527  by: operator  reason: 'k'
  factors: 1
    - operator [operator_session] concur
```

**Eight peers invited, zero of them live, decided in 15 seconds by the operator.** The one
recorded factor is the operator, not a peer.

### Why this matters beyond one row

A downstream instrument reading this escalation sees `invited_peers: 8` and zero peer factors.
That is the same shape as *"eight peers were asked to look and none did"* — the reading that
supports "peer review is busy but loses a race to the decision." Here the true statement is
**there was no live peer to invite**. The two causes are not distinguishable from the
invitation count and the factor count alone.

They *are* distinguishable from data already on the chain: `invitation_evidence[].liveness_at_invite`
is stamped at open. This is consistent with the earlier result that `liveness_at_invite` on the
open predicts the factor (unknown: 0/45). What is new is only that the predictor has now
**saturated** — with one live seat, no escalation can carry a live non-asker invitee, so for the
duration of this outage every escalation is structurally unreviewable and will look like
peer indifference in any factor-keyed statistic that does not join on liveness.

**Practical consequence for anyone reading the corpus later:** escalations opened between
2026-09-03T17:50:51Z and whenever codex/kimi credits refresh should be excluded from, or
stratified separately in, any peer-participation rate. They are not evidence about reviewer
behaviour.

**What this does NOT show.** N=1 after the boundary. I am not claiming a rate, and I have not
shown that any published number was actually computed over a single-seat window — only that
the confound is live now and that the field needed to detect it is already recorded.

---

## 3. Refuted prediction: I expected the mesh not to know its peers were down

I predicted the invitation path would keep treating the stopped seats as ordinary quiet peers,
because `resolve_invitation` builds the pool from every id that ever connected and fails open.

**Refuted.** `tools/liveness_is_the_watcher_not_the_member.py` run during the outage:

```
codex        dormant   touch age 2586s   not live (dormant) — already excluded
kimi-code    dormant   touch age 2582s   not live (dormant) — already excluded
claude-code  live                        agrees (live and acting)
DIVERGENT: 0 of 10 seats I am waiting on
```

Touch ages of ~2585s match the 10:50:51 stop to within the poll interval. Liveness tracked the
stop correctly and the seats are excluded from the waiting set. The instrument was right and my
prediction was wrong.

The fail-open in `resolve_invitation` is real and separately documented — 41 of 48 invitation
rows in this window (85.4%) went to an id recorded as `dormant` or `unknown` **at invite time** —
but that is the known residue problem, not a failure to observe the stop. Liveness is computed
correctly; it is simply not consulted as a gate on invitation.

---

## 4. Near-miss: I nearly re-derived a merged fix by grading my own checkout

Worth more than the findings above, because it is a trap I have written down and walked into
anyway.

The wake primer tells every seat that `tools/process_vintage.py units` is what distinguishes a
missing `open_petitions` key. I ran it from the shared working tree:

> `hestia-watch-claude: active as pid 1253 but THIS invocation has emitted no ARTIFACT level line
> yet (it is hourly) — vintage NOT MEASURED. ... wait for the next level line.`

I then confirmed at the source that the watcher emits `startup_sha256=… startup_origin=…
disk_sha256=…` while `ARTIFACT_RE` required those two fields **adjacent**, and that
`startup_origin` was inserted by a merged commit. Live journal for the current invocation: **2**
ARTIFACT lines present, both unparseable. The tool was telling me to wait for a line that had
already arrived twice.

All of that is correct — and all of it was already fixed. `origin/main` parses the line as a
`k=v` bag (`ARTIFACT_ANCHOR` + `ARTIFACT_FIELDS`); the repair landed in #880, and my own #892 was
closed as a duplicate of it. What I measured was **my checkout**, not the code.

The controlled comparison, same journal, same second, differing only in file version:

| version | verdict |
|---|---|
| shared working tree (`kimi/wake-0903f-…`, pre-fix) | `vintage NOT MEASURED … wait for the next level line` |
| `origin/main` (post-fix) | `[ok: matches-startup]  in force: 0c5611f` |

`git diff --stat origin/main -- tools/process_vintage.py` → 12 insertions, 75 deletions;
`grep -c ARTIFACT_ANCHOR` in the tree → **0**.

### The part that is still live

This is not only my mistake. The primer prescribes a **relative path**, and the shared working
tree is a single checkout that sits on whichever seat's branch was last worked. Right now that is
`kimi/wake-0903f-604-kimi-cell-stale`, which predates the fix. So the merged repair is not in
force **at the invocation site the primer names** — any seat that follows the primer literally
from this tree gets the pre-fix reader and its confidently wrong "wait for the next level line."

"Shipped is not in force" already covers committed → merged → rebuilt → restarted. This adds a
level below all of them: **the working tree's branch**. A fix can be merged, correct, and tested,
and still not be what runs, because the path that invokes it resolves against a checkout nobody
advanced.

The cheap mitigation is to name the tool by an absolute path or resolve it against `origin/main`
in the primer text, rather than assuming the tree is on main. Recording rather than patching the
primer here — the primer generator is not this seat's to edit unattended.

---

## 5. Accountability self-audit

```
surface: read-only diagnostics (systemd show, journalctl, chain walk, escalation_read)
act: none consequential — no writes outside /tmp and this findings file
S: low/reversible   R: n/a   W: n/a   O: n/a   A: n/a
V: §2 table reproducible via chain_walk over gate_escalation_opened + invitation_evidence;
   §1 via systemctl --user show; §4 via the two-version comparison, control built in.
verdict: PASS — reporting only. No seat restarted, no credits spent on peers, no gate acts.
```

**Deliberately not done:** I did not restart the codex/kimi watchers. Both seats are out of
quota, so restarting would resume the no-backoff re-fire burn against seats that cannot answer.
That is the operator's call, and it should follow a credit refill, not precede it.
