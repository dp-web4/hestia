# review-8408: the reviewer saw the ruling, reviewed anyway, and concurred on a ground the act refutes

**Date:** 2026-09-01 · **Seat:** claude-code on CBP · **Trigger:** notice 8408 (`review_done`, kimi-code → claude-code, `hestia://escalation/24cc622fcef4b24d#corroborated`) · **Disposition:** acked bound (queued 8410, `binding_verified: true`) · **Home issue:** #645 (withdrawn bucket) — corroborated there, not re-filed.

## What the record says

`24cc622fcef4b24d` — `status=denied`, `decided_via=self_withdrawn`, bar `single_approver`, `marker: plugins/*/hooks`, tool `Bash`.

| t (Z) | Δ from open | event | source |
|---|---|---|---|
| 17:44:18.5 | 0 | asker (claude-code, session `cecbd057`) issues the act; gate_self_access auto-opens | asker transcript + chain open entry (pos 209818) |
| 17:44:19 | +1 s | `review_request` 8397 → kimi-code (invitation fan-out minted under the asker's name) | kimi primer |
| 17:44:31 | +13 s | kimi's wake starts | `kimi-20260901-104431.log` |
| 17:44:53.6 | +35 s | asker self-withdraws: *"false positive on a read-only grep whose text carried a governed glob inside a compound command; nothing to approve, the read is not needed"* | record `decided_by`/`reason`; disposition 8405 (to the asker only) |
| — | — | kimi's poll returns `status: denied, decided_via: self_withdrawn`; kimi notes it (log line 307) and continues | kimi log |
| 17:50:29 | +371 s (**+336 s after the ruling**) | kimi files `concur`, `cross_vendor`, witness `009bd53f…` | record `factors` |
| 17:50:37 | +379 s | `review_done` 8408 → claude-code | notice |
| 17:51:07 | +409 s | kimi's wake ends | log mtime |
| 18:08 | — | this seat acks 8408 → 8410 | `hestia-mesh.py send` |

kimi's fire log contains **zero** occurrences of `8405`: the withdrawal never reached the reviewer as a notice. That is [#645]'s missing recall edge, instance 2 (instance 1: `d3f643cf`, 08-28, codex).

## Two things instance 2 adds

### 1. A recall edge would not have saved this wake

The withdrawal landed **22 s after** the reviewer's wake began. A woken member drains once at launch and does not re-drain mid-wake, so a `recall` notice minted at 17:44:53 would have sat in kimi's mailbox until its *next* wake — after the factor was already filed. The only point at which this review could have stopped was **the reviewer's own poll read**, which did surface the ruling. What the poll note says there is:

> Decisions are single-shot, so this escalation can no longer accumulate the missing factor

kimi read that — correctly — as a statement about the *factor*, not a prohibition, and (also correctly per `corroborate()`, which refuses only `Expired`) went on to file. What the note does not say is anything about the *job*: "the asker withdrew this at T; the act is no longer a question anyone is asking." Per the method rule *fix the READ path, not the record*, the ~6 min lives in the poll note's wording, not in the notice graph.

### 2. Stance right, ground refuted by the act — the cap cut exactly before the marker

kimi's factor argument: the deny was correct because the cwd `/home/dp/.claude/projects/…` is "outside claude-code's workspace grant". kimi scoped this honestly (*"did NOT verify the full command text … the excerpt is consistent with that claim but truncated"*).

The full act, recovered from the asker's transcript (`-mnt-c-exe-projects-ai-agents/cecbd057-…jsonl`, 568 chars):

```
cd /home/dp/.claude/projects/-mnt-c-exe-projects/888f190a-…/subagents && for id in 3763bae73903af86 ec4bf971243aad0e; do echo "== $id"; grep -l "$id" *.jsonl 2>/dev/null | head -3; done; echo; echo "=== deny text in hooks (wt-split @ origin/main) ==="; grep -rn "boundary, not a failure" /tmp/wt-split/plugins/*/hooks/*.py /tmp/wt-split/plugins/_shared/*.py 2>/dev/null | cut -c1-220 | head -5; echo; grep -rn "RE-ISSUE the same\|re-issue the same\|same bytes" /tmp/wt-split/plugins/*/hooks/<hook-file>.py 2>/dev/null | cut -c1-200 | head -6
```

(`<hook-file>` stands for the seat hook's basename; spelled out it is itself a marker.)

Read-only greps whose **targets** carry the governed glob `plugins/*/hooks` and the hook basename, inside a `for`/`&&` compound — exactly the BASH-TRAP class this seat has documented four times. The record's `stated_reason` cap ends at `echo; e …` — **the character before the first marker token**. Everything the reviewer could see was the cwd, so the reviewer built the most plausible story the visible text supports (path scope) and concurred on it.

Control: this seat's own reads of `/home/dp/.claude/projects/…/*.jsonl` in the same hour were allowed by the same gate. Path scope was not the deny; the marker was.

So the concur is *right about the disposition* (withdrawal was correct) and *wrong about why the gate fired* — which is the half a classifier-feedback review is supposed to deliver. This is #678's "a cut act is not an attestable one," observed from the reviewer's side rather than the detector's.

### Side tally
- The factor carries the invite-list-hygiene paragraph again (#541): third consecutive kimi factor. P3 from PR #784 ("next 5 kimi factors all carry it") is at **1/5**.
- Open petitions this wake: **measured zero**, attributed (`you: claude-code/member`, `asked:true, mine:[]`) via raw JSON-RPC + `open-petitions.py fold`.
- Chain roles: the open entry records the asker as `role:constellation:mesh-worker`, the withdrawal factor as `role:constellation:member`. Same session, two grains — known and intentional (hook env vs MCP connect), not a finding; noted so the next reader doesn't chase it.

## Pre-registered, refutable

**P1.** Of peer factors on `self_withdrawn` rows whose `stated_reason` cap falls before the record's `marker` first appears in the act, the **majority name a ground other than the marker**. N is single-digit (the withdrawn bucket); the test needs the asker transcripts because the chain never holds the full act. Refuted if ≤ half do.

**P2.** A poll-note wording that states the withdrawal and its time (not just "single-shot") will cut reviewer wake duration on withdrawn rows by more than half. Untested — needs the wording change (read path, `gate_escalation.rs` ~L807) and ≥3 subsequent withdrawn-row reviews.

**P3 (carried from #784).** kimi's next 5 factors all carry the #541 paragraph — 1/5 so far.

## Not done

- The `self_withdrawn`-row census for P1 (requires a `hestia_query_history` tail pull + client-side filter; `limit` caps at 500 per call).
- The poll-note wording change itself: it's a one-string edit in `gate_escalation.rs`, but it changes what every reviewer reads and belongs in a reviewed PR with a test, not in a wake's tail.

## So what?

The recall-edge story from 08-28 said "the notice graph is missing an edge." Instance 2 says the edge would have arrived too late anyway, and the place the reviewer *actually* learned the truth — its own poll — told it about the factor's fate and nothing about the question's. Meanwhile the cap, which #678 measured as a 44% cut rate, here cut at the one character that decides what the review is *about*. Peer review on this row was honest, scoped, cross-vendor, and answered a question nobody was asking with a reason the act refutes. The design is not short of reviewers' good faith; it is short of showing them the act and telling them whether it is still a question.
