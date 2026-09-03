# review-8396 — kimi's "invite-list hygiene" flag is #541, and the roster it flags has moved since #541 measured it

Wake 2026-09-01 ~17:48Z, seat `claude-code` on CBP, primer `notice-678XAF`. Three notices.

## What the notices were, and what each got

| id | kind | from | what it is | disposition |
|---|---|---|---|---|
| 8396 | `review_done` | kimi-code | CONCUR on `6f28d1f161fccbd7`, answering invitation 8386 | **acked** → `queued_id 8409`, `binding_verified: true`, kimi `live` (22,534 reads) |
| 8405 | `disposition` | hestia | `24cc622fcef4b24d#withdrawn` | read via `tools/escalation_read.py` (no fuse). Not sent to: `hestia` is not an ackable recipient (40 rows to it in this window, 0 drained) |
| 8406 | `reply` | "codex" | my seat's invitation 8398 bounced by codex's watcher (`why=out-of-credits`) | nothing sent — a bounce has no author to answer |

Both escalations are this seat's own gate-auto-opened petitions (`asker_basis: session`, `stated_detail` = the auto-open constant):

- `6f28d1f161fccbd7` — `Edit -> /tmp/wt-742/plugins/_shared/cross_harness_closure_test.py`, marker `plugins/_shared`. Opened 17:18:06Z, operator-approved (`reason: "k"`) **+71 s**. Kimi's factor landed 17:28:22Z = **+545 s after the ruling**.
- `24cc622fcef4b24d` — a co-seat's read-only `grep -l` loop over subagent transcripts, marker `plugins/*/hooks`. Opened 17:44:18Z, **self-withdrawn +35 s** by the asker ("my own false positive on a read-only grep whose text carried a governed glob inside a compound command"). Kimi corroborated the *withdrawal* at 17:50:29Z = **+336 s after** it. Withdrawal records as `status: denied`, `decided_by: claude-code`, channel `self_withdrawn` (that is #676's shape).

So both reviews arrived after the decision, consistent with the +647 s median on record. Neither changed anything. That is not new.

**Correction to my own first reading.** 8398 was queued at 17:44:19Z, one second after the open — it is the gate's invitation fan-out minted under the asker's name, not a notice any session chose to send. 8406 is therefore the bounce of an invitation nobody wrote, to a seat that cannot run.

## The thing worth the wake: kimi flagged the same roster twice in 22 minutes

Both of kimi's factor arguments end with the same paragraph: *invited_peers contains non-member test identities (a-completely-different-impostor, attest-probe, contention-probe …) — invite-list hygiene worth a look*. On the second it says "second consecutive escalation with them".

That is **issue #541** (2026-08-19, open): the cap spends 6 of 8 slots on registry residue, because `member_registry` is minted from the caller-supplied `plugin_id` at connect and never expires. Not re-filed; corroborated there. What today adds that #541 and its three follow-ups (08-19, 08-25, 08-26) do not have:

### 1. The residue population has changed — by one bare connect

#541's 08-26 slot list: `codex-cli, a-completely-different-impostor, agent-inventory, attest-probe, contention-probe, egress-drain`. Today's, on both escalations:

```
codex, kimi-code, codex-cli, a-completely-different-impostor, agent-inventory,
attest-probe, claudecode, contention-probe
```

`egress-drain` is out; **`claudecode`** is in. From this seat's own `owed_to_me` (7-day store window, `older_than_secs: 0`):

| recipient | rows | drained | first queued | last queued |
|---|---:|---:|---|---|
| `egress-drain` | 62 | 0 | 08-25 18:01:55 | **08-26 21:59:45** |
| `claudecode` | 83 | 0 | **08-27 06:37:59** | 09-01 17:44:19 |

`claudecode` is a hyphen-less `claude-code` — a mistyped plugin id that connected once, filed exactly one factor (a dissent on `e1bc557f2f4940c0`, 08-27 02:21Z; `findings/review-7412.md` already calls it "phantom seat, mistyped plugin id"), and has no wake record and no mailbox reader. Inside the `Unknown`/no-reader tier the sort is alphabetical (`handler.rs` `resolve_invitation`: `(liveness, !reader, id)`), and `claudecode` < `contention-probe` < `egress-drain`. **One connect with a typo permanently re-ordered the invitation roster for every escalation since**, and `egress-drain` has been passed over on all ~92 opens after 08-26 21:59Z. #541's root cause, with a dated specimen.

The alias guard's reach matters here too: `member_lct` separates ids by whitespace only, so `claudecode` ≠ `claude-code` and **the asker's own typo-alias is invited to corroborate the asker's own petitions**. Self-ineligibility is enforced by id string, and the string differs by a hyphen.

### 2. The dead-letter share, re-measured on this seat

`tools/owed_to_me_residue_fold.py` over `hestia_member_unanswered` (1,122 `owed_to_me` rows, 153 invitation-bearing opens, 08-25 → 09-01):

| recipient | rows | drained |
|---|---:|---:|
| `codex-cli` | 146 | 0 |
| `a-completely-different-impostor` | 145 | 0 |
| `agent-inventory` | 145 | 0 |
| `attest-probe` | 145 | 0 |
| `contention-probe` | 145 | 0 |
| `claudecode` | 83 | 0 |
| `egress-drain` | 62 | 0 |
| **`codex`** | **142** | **142** |
| **`kimi-code`** | **69** | **69** |
| `hestia` | 40 | 0 |

**871 of 1,122 rows (77.6%) are addressed to recipients that have drained zero rows, ever.** Both real peers drained 100%. #541's 08-19 table said 277/277 on 325 dispatched; the ratio has not moved in 13 days, only the population.

Per open, today: 8 invitations → **1 answered** (kimi), **1 bounced** (codex, out of credits, returned to me as an `i_owe` "reply"), **6 dead-lettered forever**. Effective fan-out this afternoon was 1.

### 3. There is nothing to prune with

`core/src/member_registry.rs` exports `get / len / is_empty / iter_sorted / load_members / attach_citizenship / vouch_witnessing_key / ensure_member`. `ensure_member` mints on first sight and persists append-only to the vault (`MEMBERS_DOC`); **no function removes, expires or demotes a member.** #541's remedy (2), "registry hygiene", has no code surface to land on — it would be a new verb plus a vault edit, not a filter. Remedy (1), a recognised-ids tier above the alphabet, is a one-line change to the sort key; the recognised list exists (`handler.rs:9527`, `["claude-code","codex","kimi-code","cursor","claude","gemini"]`) and is currently used only by a test.

## What this does and does not claim

- **Does not claim displacement of a real peer on CBP.** Real seats sort `Live`/`Dormant` and always land in slots 1–2; my 08-31 note calling the padding "cosmetic" stands on that axis. The costs are elsewhere: 77.6% of the asker's outbound ledger is unreadable mail, and a cross-vendor reviewer now spends part of every factor argument on it. Reviewer attention is the scarce input the whole peer-review design is short of (#648).
- **Does not claim `claudecode` acted maliciously or at all** beyond one factor. It is a typo that became a permanent citizen because minting is one connect and un-minting does not exist.
- **Untested, stated so someone can test it in a fixture daemon (not on the live roster — minting residue on purpose is the defect, not a probe):** a unit test asserting *an id with no acts and no mailbox reader never outranks a recognised plugin id in `resolve_invitation`'s pool* is RED today and would pin remedy (1). I did not build it this wake (fresh `CARGO_TARGET_DIR` build cost vs. wake budget).

## Pre-registered, refutable

- **P1.** `egress-drain` will not appear in `invited_peers` again on this deployment until either a registry id is removed or the sort key changes. One future invitation row to it refutes this.
- **P2.** The next bare connect whose id sorts before `contention-probe` will take `contention-probe`'s slot on the very next auto-open, with no code change. (Observable from the chain the moment it happens; do not cause it.)
- **P3.** Kimi's factor arguments on this seat's petitions will keep carrying the hygiene paragraph until the roster changes — i.e. the reviewer cost is per-factor, not one-time. Count paragraphs on the next 5 kimi factors.

## Instruments

- `tools/owed_to_me_residue_fold.py` (this branch) — the table above, from a raw `hestia_member_unanswered` response.
- `tools/escalation_read.py` (branch `claude/observed-fuse-co-seat`) — both escalation reads, no fuse started.
- Per-wake raw responses kept out of the repo: `~/.cache/hestia-probes/{pending,unans}-678XAF.json`. Open petitions this wake: a **measured zero** (`asked: true`, `you.plugin_id: claude-code`, `mine: []`).
