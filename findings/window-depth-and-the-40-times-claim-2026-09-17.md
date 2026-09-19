# Why "40 times — the most of any member" survived three readings

**Subject:** PR #1055 blocker 2 (dp) · **Closes:** the provenance question, not just the comment
**Related:** `findings/review-13031-verdict.md` §A (kimi-code's refutation), `findings/review-13031-response.md` §3 (my own confession of the same error one comment over), hestia#1059 (found while fixing this)

dp asked for the correction *and* for why the claim was made: "could be confab, could be
misread, could be something we missed." It is none of those three. It is a fourth thing, and
the fourth thing is the interesting one.

## The claim was a real measurement with its quantifier silently promoted

Full chain walked today (`tools/chain_walk.py`, **260,669 entries**, genesis reached, not
truncated), every `gate_escalation_corroborated` row recorded with its distance from the chain
head, then replayed at every window depth:

| window depth (entries from head) | kimi-code | codex | claude-code | claudecode | leader |
|---|---|---|---|---|---|
| 10,000 | 7 | 5 | 3 | 0 | kimi-code |
| 20,000 | 22 | 16 | 5 | 0 | kimi-code |
| 30,000 | 22 | 28 | 5 | 0 | **codex** |
| **40,000** | 23 | **38** | 14 | 0 | **codex** |
| 50,000 | 31 | 57 | 32 | 0 | **codex** |
| 80,000 | 93 | 106 | 67 | 1 | **codex** |
| 100,000 | 109 | 119 | 85 | 1 | **codex** |
| 150,000 | 151 | 142 | 121 | 1 | kimi-code |
| 260,669 (full) | **151** | 142 | 121 | 1 | kimi-code |

Leadership by depth: kimi-code to ~28k, **codex from 28k to 130k**, kimi-code from 130k out.

So at the 40,000-entry window I actually walked, codex had **38** corroborations and **was**
the leader, by a wide margin. kimi-code's independent 40k walk got 16 / 41 / 22 for the same
three seats — the same digits, a few hours of chain apart. The number was not invented and the
superlative was not a misreading of some other object. Both were true **of the window that was
measured**, and the window was never written down.

That is the failure: the scope quantifier was dropped between the measurement and the sentence.
"codex has 38 of the last 40,000 entries' corroborations, more than any other seat in that
window" became "it has used it 40 times — the most of any member." Every content word survived;
only the domain was lost, and the domain was the whole of the claim.

## Why it survived three readings, including my own

Because the 40k window is exactly the band where the claim reads true. Look at the leadership
column: a reader who spot-checks a recent window — which is what every cheap check does, since
a 40k walk is 40 s and a full walk is 9 minutes — **reproduces the claim and confirms it.**
The only check that refutes it is the one nobody runs casually. A false statement that
self-confirms under the cheap check and fails only under the expensive one will survive
review indefinitely; it survived mine, and it survived a second reading in the same PR whose
§3 is *me confessing this exact error one comment over*.

That is the generalisable part, and it is not about counts. **A windowed measurement published
without its window is not an imprecise claim — it is a claim about a different population than
the one measured**, and its truth value is a function of a parameter the reader cannot see.
Recency-weighted windows are the fleet's default instrument (`scan_window`, the 10k hot scan,
`hestia_query_history`'s 500 cap, every census in `tools/`), so this is a standing hazard of
the toolchain, not a slip of one seat's attention.

The correction therefore removes the counts rather than repointing them at kimi-code. A
superlative rots on the next factor; a count rots more slowly but still rots; a pointer to a
dated census with its denominator does not. All three hook comments now say what the seat
*holds* — an effector — and cite where the counting lives.

## What "we missed" actually turned out to be

Nothing in the claim. But making the correction surfaced hestia#1059: the fourth governed write
of this repair — the `SHIM_LEDGER.md` re-justification — **landed with no escalation at all**,
because the closure classifier treats `python3 <script> plugins/_shared/SHIM_LEDGER.md` as not
a write. The marker matched; no verb did. It was reverted and re-issued as a `cp` under an
approval, and the measurement table is in #1059.

The two defects are the same defect. This one is a claim measured over a window and published
as a claim over a population. That one is a gate that decides *is this a write?* over a
vocabulary of verbs and publishes the answer as if it were about the act. Both substitute a
cheap, visible proxy for the thing they assert, and both are wrong in exactly the region the
proxy does not cover — which is, in both cases, the region nobody looks at.
