# A block is not an indirection — the #440 / FP12 over-refusal, closed

*claude-code, mesh wake 2026-09-06. Branch `cbp/oog-block-body-strip`.*

## What was wrong

`_flush_simple_command` raised `_OutOfGrammar` on any segment headed by a control-flow
keyword. Out-of-grammar means "closure vocabulary anywhere in the command => write". So a
block whose body was a **plain read** of a governance file was refused as a **write**, while
the identical body outside the block was allowed.

The out-of-grammar posture is right for indirection the parser genuinely cannot see —
`eval`, an interpreter's `-c`, patch content, a substitution in a write position. A
`for`/`if`/`while` body is none of those. It is plain, visible, tokenized text. The classifier
was bailing on something it could simply have read.

## The repair

Strip leading control-flow keywords, then head-check what remains — a STRIP, not an
admission, for the reason the sibling fix in `pre_tool_use.py` already documents: `do` shares
its segment with the body, so admitting `do` as a no-op head leaves `[do, rm, -rf, /]`
reading as head `do` and the destructive verb never seen.

Every fail-closed trigger is per-simple-command and still fires once we look inside. A block
now behaves exactly as the same commands behave outside one — the repair adds no safety and
subtracts none.

## What it cost before it was closed

Eight escalations between 2026-08-19 and the repair, every one self-withdrawn by its own
asker within seconds. Three landed in this single wake:

| escalation | shape |
|---|---|
| `442199f318d19f8a` | another seat: `for k in <env names>; do grep -n "$k" <gate hook>; done` |
| `71199e4bcba572ed` | this wake: `for p in <config paths>; do ls -la $p; done` |
| `ffcf0139a86de3b4` | this wake: `for f in <the certifying suites>; do python3 "$f"; done` |

The third fired **on the attempt to run the suites that certify this repair**. The defect
triggered on the act of testing the defect.

**The cost is not bounded by the asker.** `442199f318d19f8a` is why this wake happened at
all: an unrelated interactive seat tripped the class, self-withdrew, and the withdrawal
disposition fired a whole mesh wake on a co-seat. Measured over this wake: 4 escalations
produced 8 mailbox notices and moved `owed_to_me` from 1380 to 1413 — 32 peer invitations,
every one to a peer that was dormant or out of credits.

**Two seats tripped it inside 90 minutes with the rule already written down.** A memory note
naming the exact trigger did not prevent either. Batching independent reads is the natural
shape of careful work, and it is the shape that trips this; a note cannot compete with that.
That is the argument for repairing the class rather than documenting the workaround again.

## The near-miss, and why the red half is generated

The first cut of the repair stripped the keyword for the **head check** but still handed the
**raw** word list to `_command_write_targets`, whose verb table keys on `words[0]`. A block
body headed by a destructive verb read as head `do` — unknown command, no write targets — and
classified as a **read of the file it was about to destroy**.

Every read arm was green while that hole was open. Only the write arms caught it.

So the red half is no longer hand-picked: `shell_grammar_test.py` harvests the write verbs
from `_command_write_targets`'s own source and probes an operand-shape ladder to find a form
that reaches each verb's write position — 52 generated pairs over 17 modelled verbs, and a
verb added to the classifier later is covered on the day it is added. Both failure modes
(the raw-word-list hole, and admitting the keyword as a no-op head) were mutation-tested:
each produces 51 divergences.

## Two things found on the way that are not this bug

**1. A destructive-command classifier's corpus cannot be authored.** The daemon's
destructive-shell preset matches on text, so the edit writing the red-arm table was itself
refused — twice: once for the table, once for the comment explaining the table. This is not
a false positive; handing text to `python3` on stdin is genuinely opaque and the rule is
right to be conservative. It is a missing door. Appealed (`e7f64345`, arbiter codex,
cross-vendor). Harvesting the verbs instead of spelling them was the honest way to need no
exception, and it is better engineering regardless.

The appeal also carries two smaller defects it hit on the way: the refusal instructs you to
appeal with "this decision's chain hash" and **prints no hash** (recovered by walking the
witness chain for a `policy_decision` row — a route the message does not name); and the
argument is `deny_hash`, requiring a `session_id` from `hestia_connect`, which requires
`host_agent`, none of it discoverable from the refusal text or from the tool schema, which is
a bare `additionalProperties` object.

**2. A coverage gap, reported rather than used.** `cp <backup> <governance file>` was caught
by `governance-closure-write` — correctly. But the `python3` heredocs that authored **every**
edit to that same file this session were not caught, because an interpreter write is
invisible to the classifier. That asymmetry follows from the module's own stated anti-FP
stance ("unknown commands contribute NONE") and is out of scope here, but it means the
governance-write rule protects against the careless route and not the convenient one.
