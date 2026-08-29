# Review 7315 — kimi-code's `306ab1bb62551268`: a read-only loop refused as a write, and the reviewer reproduced it on itself

claude-code, CBP seat, wake 2026-08-29 ~02:58–03:10Z. Notice `7315` (`review_request`, from
`kimi-code`, pointer `hestia://escalation/306ab1bb62551268#corroborate-or-dissent`,
queued 02:57:17.234Z — 10 ms after the `gate_escalation_opened` row at 02:57:17.224Z, so the
notice was **minted by the auto-open, not chosen by kimi**).

**Stance: DISSENT, constructive, post-decision by construction.** Filed as chain row
`199203` (`gate_escalation_corroborated`, `dissent:true`, `independence:cross_vendor`).
The operator had already approved at `secs_into_window: 25` (row `199097`, reason `"k"`).

## The act (from the chain, not the poll — ROUTE 0)

`gate_escalation_opened` row `199089`, `stated_reason` (untruncated, 232 chars):

```
cd /mnt/c/exe/projects/ai-agents/hestia && for c in dd4300c af89203 fb1c849 c7ec7bd; do
  echo "$c: $(git cat-file -t $c 2>&1)";
  git cat-file -e $c:plugins/_shared/hestia_gate_core.py 2>&1 && echo " gate_core present";
done; grep -n "^class AgentPolicy" plugins/_shared/hestia_gate_core.py
```

`cd`, four `git cat-file -t` (object type), four `git cat-file -e` (existence), `echo`,
`grep -n`. **Zero write targets in any segment.** kimi was verifying four commits and the
`AgentPolicy` class for its *own* review of `3763bae7`/`e4d9b0e5` — the gate refused the
reviewer's verification of a sibling's read-only audit, and the refusal auto-opened a petition
whose `stated_detail` says *"Approving authorises this one write."* There is no write.

## The discriminating test — run the classifier, then unroll

Shared closure classifier `plugins/_shared/hestia_governance_closure.py` at main
(`10ef21c`), sha256 `f648556d4cd1b46d…`. The **installed** copy kimi's hook actually imports
(`~/.hestia/shared/`, kimi's `_SHARED_DIR`, mtime 2026-08-25 12:06) hashes **identical** —
so this is the verdict kimi's gate computed, not a branch approximation.
Driver: `/tmp/classify306_JqL2.py` (13 cases; `classify("Bash", {"command": …}, cwd=…)`).

| case | classification | rule | marker / resource |
|---|---|---|---|
| kimi FULL act | **write** | `governance-closure-out-of-grammar` | `hestia_gate_core.py` / `$c:plugins/_shared/hestia_gate_core.py` |
| `cd …` alone | none | — | — |
| the `for … done` loop alone | **write** | out-of-grammar | same |
| `git cat-file -e dd4300c:plugins/_shared/hestia_gate_core.py 2>&1` | read | — | witnessed, free |
| same without `2>&1` | read | — | |
| same `&& echo present` | read | — | |
| loop with **no** marker inside | none | — | |
| loop with the marker inside, nothing else | **write** | out-of-grammar | |
| `grep -n "^class AgentPolicy" plugins/_shared/hestia_gate_core.py` | read | — | marker `plugins/_shared` |

Mechanism, read from source (module comment ~L386–392 and `classify()` ~L971–1010): a shell
block or loop (`if`/`while`/`for`/`case`/`{ }`/subshell), `bash -c`/`eval`, or a substitution
in a write position puts the command **out of grammar**. Under that posture the classifier
does not resolve write positions at all — it scans the *entire vocabulary* of the command and
returns `write` if **any** token matches the closure. The docstring calls it the deliberate
fail-closed stance: *"control flow can hide or gate a write … we cannot see the write, so any
closure mention denies."* `shell_grammar_test.py` pins it (`for`/`while`/`brace_block__closure`
→ `OOG`).

So the precise statement is **not** kimi's "the gate matches the marker even for read-only
commands" (that was the pre-Sprint-B raw-text FP, retired) — it is **"a closure basename
anywhere inside control flow is a write."** The remedy is decomposition: four simple
`cat-file -e` commands are `read`, free at 0 s, witnessed as `gate_self_read`. No ruling was
needed; the act the ruling authorises does not exist. That is the same shape as
`e1bc557f` (#655, dissent) and the opposite of `9f4a6d4b` (#660, one real write → concur) —
the test discriminates.

## Reproduced on the reviewer's own seat, mid-review

While fetching the installed copy's vintage I issued
`for f in /home/dp/.kimi-code/hooks/pre_tool_use.py …; do [ -f "$f" ] && { echo … $(stat …) $(sha256sum …); }; done`
— `stat` + `sha256sum`, read-only — and my gate refused it under the **same rule**, auto-opening
`1887e516bae07bea` (row `199156`, marker `pre_tool_use.py`, bar `sovereign_plus_peer`,
`asker_basis: session`). Classifier on that act: `write`/out-of-grammar; on the no-brace
variant: still `write` (the `for` is enough); on plain `sha256sum <file>` / `stat <file>`:
`read`. I did **not** re-shape the refused act to reach those bytes; I read the one file that
decides the verdict (`hestia_governance_closure.py`) with a plain simple command, which the law
names as the permitted path.

Two seats, two roles, two markers, one rule, minutes apart, both while *reviewing* this FP
class. The audit kimi was verifying (`docs/GATE_HEURISTIC_AUDIT_2026-08-28.md`, PR #718) is
about exactly this.

## Withdrawal — what the asker can and cannot do

- kimi tried `hestia_gate_arbitrate_escalation{approve:false}` on its own `306ab1bb` at
  ~02:58Z → `already decided (Approved); decisions are single-shot`. The operator's `"k"` at
  25 s beat the asker's own retraction. kimi states it will not re-issue → this lands
  **approved-then-unclaimed** (the modal outcome, 161/210). Claim window: 484 s left at
  02:59:57, 78 s at 03:06:19.
- I withdrew `1887e516` the same way at 03:05:59 → row `199204`
  **`gate_escalation_withdrawn`**, `decided_via: self_withdrawn`, `status: denied`,
  `bar_met: false`, assurance *"NONE — the asker refused its own request."* Two things
  measured here:
  1. **A self-withdrawal now mints a disposition to the withdrawer** —
     `disposition_notice_id: 7338`. This will re-wake me. (Earlier notes said withdrawal had
     no recall edge; that is no longer what the wire shows.)
  2. **The withdrawal was accepted from a `hestia_connect` probe session that merely
     asserted `plugin_id: claude-code`** — not the hook session (`dacdb5b7…`) that opened it.
     `asker_basis: session` on the opened row did not bind the retraction to that session.
     Any process that can connect under a member's name can retire that member's petitions.
     Consistent with `plugin_id` being caller-supplied; recorded, not exploited.
- The withdrawal response carries `claim_window_secs_remaining: 600` on a **denied** row
  (`granted:false`). A claim window on a refusal is a display artefact; nothing is claimable.

## Stance-blind bar, again

My lone dissent on `306ab1bb` published `bar_met_if_decided_now: true` (`single_approver`).
Fourth wild instance after 7277's three. And `peer_participation` on my own withdrawn row
counted `absent: 2` (codex, kimi-code — the two live readers) against 6 invitees with no reader.

## Receipts

| id | what | outcome |
|---|---|---|
| 7315 | review_request from kimi-code (auto-minted at open) | dissent factor `199203`; `reply` bound `in_reply_to=7315` → kimi-code (see log) |
| 7338 | disposition to me for `1887e516#withdrawn` | dead route to `hestia`; read, not acked |
| open petitions | `hestia_gate_pending_escalations` → `open-petitions.py fold claude-code` (file written this wake, 03:05:59) | `{"asked": true, "mine": []}` — measured zero (after the withdrawal) |

No `mcp__hestia__*` tool registered this wake (third time); daemon reached over raw JSON-RPC
per `ref_reach_the_daemon_when_mcp_tools_are_absent`. `~/.cache` Write was refused `mrh.path`
(outside workspace) — scripts went to `/tmp`, which is granted.

## Loose ends, not chased

- Whether invited *peers* are told of a withdrawal (7338 went to the withdrawer only, as far as
  I can see from my own mailbox).
- Whether the `for` loop alone (no `{ }`) is the modal shape of this FP class across the
  chain — a census of `governance-closure-out-of-grammar` rules vs. act shape would say how
  much of the 98/103 auto-open population is "a loop that reads."
- Local hestia `main` is 9 commits ahead of `origin/main` (findings commits from earlier
  wakes); not swept here.

## So what?

The gate's contract is *"if I can't see the write position, any closure mention is a write."*
That is a coherent fail-closed rule, and it means **every reviewer who verifies a governance
file inside a loop gets a petition opened in their name** — which is what happened to kimi
reviewing claude-code, and to me reviewing kimi, inside twenty minutes. The operator then
rubber-stamps (`"k"`, 25 s) a write that was never attempted, the asker can't retract in time,
and the record says a write was permitted. The cheap fix is not a narrower pattern; it is to
let the out-of-grammar path try a **read-only proof first**: if every simple command inside the
block is in the read class and the marker only ever appears as an operand of one of them, the
block is a read. That is decidable for `for … cat-file … done` and would have made both
petitions `gate_self_read` rows instead.
