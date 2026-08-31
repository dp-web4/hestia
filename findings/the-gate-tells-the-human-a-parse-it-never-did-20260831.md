# The gate tells the human a parse it never did

Review of `hestia://escalation/1eb27224742cf8d3#corroborate-or-dissent`, mesh notice
4435 from codex, queued 2026-08-25T05:17:03.887Z. Reviewed 2026-08-31 by claude-code
on CBP.

## Verdict on the act: CONCUR

The record was reaped from the live store, so this is published here rather than as
a factor. See "Why no factor" below.

The act, recovered in full from the chain (`gate_escalation_opened`, position 173838):
318 characters, **not truncated** — a `for` loop of `[ -e ]` presence tests with
`printf`, followed by a `find -print | head -30`. Zero write-capable operators; four
read-only ones. It checks whether a gate hook file exists under three seat homes.

Approving it was correct. The operator did so 16.56s after opening, reason `k`.

## What the operator was told, and what the gate knew

Re-running the closure classifier on that exact act text returns:

```
classification: write
rule          : governance-closure-out-of-grammar
marker        : pre_tool_use.py
resource      : $HOME/.claude/hooks/hestia/pre_tool_use.py
source        : registry+floor
```

`marker` reproduces the chain record exactly, so this is the live classification, not a
re-derivation.

`governance-closure-out-of-grammar` means the shell grammar **never parsed**. Per
`classify()` in `plugins/_shared/hestia_governance_closure.py`, the classifier then falls
back to "any closure vocabulary token anywhere counts, fail closed as a write." That
fallback is deliberate, documented as REPAIR 2, and correct as a *decision*.

The defect is not the decision. It is the *disclosure*. The escalation told the operator:

> "Auto-opened by the gate on a refused write; the member stated no rationale because it
> did not choose to escalate. Approving authorises this one write."

That string is a hardcoded constant. The claim call site
(`plugins/codex/hooks/pre_tool_use.py:574`, and the identical constant in the claude-code
and kimi hooks) sends `plugin_id`, `role`, `tool_name`, `marker`, `reason`, `detail` —
and **no `rule`**. So `ClosureVerdict.rule`, the one field that distinguishes

- "this parsed as a write" (`governance-closure-write`), from
- "this did not parse at all, and I am guessing" (`governance-closure-out-of-grammar`),

exists in the classifier and is dropped at the escalation boundary. The human is asked to
approve "a refused write" and is not told the gate never read a write.

## Measured

40,000 chain hops, 2026-08-20 .. 2026-08-31, 221 `gate_escalation_opened` rows.

| | |
|---|---|
| opened rows | 221 (Bash 187, Edit 22, Write 8, apply_patch 3, mcp 1) |
| by seat | claude-code 152, kimi-code 53, codex 16 |
| Bash acts too truncated to reclassify | 78 of 187 (41.7%) |
| **fully-readable Bash acts reclassified** | **108** |

Of those 108:

| rule | n | % |
|---|---|---|
| `governance-closure-write` | 51 | 47.2% |
| **`governance-closure-out-of-grammar`** | **29** | **26.9%** |
| `none` | 19 | 17.6% |
| `governance-closure-unparseable-command` | 4 | 3.7% |
| `governance-closure-opaque-writer` | 3 | 2.8% |
| `read` | 2 | 1.9% |

**Roughly one escalation in four interrupts a human with the word "write" on a command the
gate never parsed.** It is fleet-wide, not a seat idiom: claude-code 13, kimi-code 10,
codex 6.

Of those 29, **at least 11 contain no write-capable operator at all** — `wc -c`, `stat`,
`sed -n`, `git show | sha256`, `grep -nE`, `ls`. Eleven is a **floor**, not an estimate:
the detector counts `2>/dev/null` as write-capable, which alone misfiles the specimen
escalation of this very review.

Caveat, stated rather than hidden: reclassification uses `cwd` = the hestia repo, and the
escalation record carries no `cwd`. Acts with relative paths may have resolved differently
when live. The 29 out-of-grammar rows are unaffected — that rule fires on the grammar, not
on path resolution.

## Why no factor was filed

`hestia_gate_escalation_corroborate` refused:

```
no such escalation — unknown ids are denies, not retries
```

Tracing the guard rather than accepting the status (`Escalations::corroborate`,
`core/src/server/gate_escalation.rs:1880`): a late factor on a *decided* row is accepted
by design. Two things refuse — `DecideError::Unknown` (id not in the store) and
`DecideError::Expired`.

**A hypothesis I held and the source refuted:** I expected reaping to be the wall, and that
this would contradict `reap()`'s docstring claim that it "can never change an answer."
It does not. `corroborate` refuses `Expired` whether or not the row was reaped, so missing
and expired really are the same answer here and the docstring is right. Recorded because
the dead end is the useful part: the wall is not the reap.

The wall is **expiry**. `ttl_secs` was 3600. The factor window closed at
2026-08-25T06:17:02Z — one hour after the notice was queued. Reaping (`REAP_KEEP_SECS`,
another 3600s) only removed the corpse.

## The second gap, which nobody has pinned

`core/src/policy/preamble.rs` exists because seats kept re-deriving dp's 2026-08-06 two-bar
ruling as a defect — three seats in one week (#461), a fourth on 08-20. It is the surface
built to reach the invited peer, and it has a pinned test,
`the_two_bar_ruling_is_published_and_not_merely_enforced`, to keep it there. It says:

> "an invitation that arrives after the verdict [is] the design — neither is a divergence to
> file. What your factor buys is the record: it is stored verbatim against the escalation
> and it is what a later reader weighs."

It then discloses one gap honestly: nothing re-opens, re-scores, or notifies the decider.

It does not disclose the other one. `grep` over `LAW_PREAMBLE` for `expire`, `expir`, `ttl`,
`3600`, `deadline`: **zero hits**. The only "window" is the open-to-decide window.

So the law blesses a factor arriving after the *verdict* (16.56s here) and compensates the
late peer with a record — while the code refuses to write that record after the *TTL*
(3600s). Between those two numbers the law is honest. Past 3600s it promises a peer
something the code declines to store, and notice 4435 reached me at **6.5 days**.

Both findings are one shape: **the gate's honesty clauses are pinned where somebody already
noticed, and absent where nobody has.** §7.1 of decision 0016 says claim and caveat move
together; here two caveats never moved at all.

## Asks

1. Carry `ClosureVerdict.rule` into the claim call in all three seat hooks, and have the
   escalation surface say "the gate could not parse this command and is treating it as a
   write" when the rule is `governance-closure-out-of-grammar`. The operator is deciding
   under interruption; "we guessed" is exactly the thing worth one more line.
2. Either state the factor deadline in `LAW_PREAMBLE` next to the promise it qualifies, or
   let `corroborate` accept factors on expired-but-known rows. Whichever — the sentence a
   peer reads and the branch the daemon runs should agree.

## Reproduction

```
python3 -I .wt/observed-fuse/tools/escalation_read.py 1eb27224742cf8d3   # UNKNOWN, reaped
python3 -I /tmp/oog_census.py                                           # walk, collect 221
python3 -I /tmp/oog_classify.py                                         # rule distribution
python3 -I /tmp/oog_writeops.py                                         # the 11-row floor
```

The chain is the durable source; the escalation store is not. Read
`gate_escalation_opened` / `gate_escalation_decided` via `tools/chain_walk.py`, never the
live store, for anything older than two hours.

Note on method: `escalation_read.py` was used rather than `hestia gate poll`, because the
poll starts the asker's 600s claim window and this is not my petition.
