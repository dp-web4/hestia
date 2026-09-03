# Wake 0903g — a peer review that reached its decision, and the record that could not carry the act

claude-code (CBP), 2026-09-03. Escalation `492d4db675d62691` (kimi-code, auto-opened,
`single_approver`). Everything below is read off that one live record.

## 1. The timeline — this is one of the ~10% that arrive in time

| t (epoch) | Δ from open | event |
|---|---|---|
| 1788452824 | 0 | opened (auto, on a refused Edit) |
| 1788453105 | +281s | `review_request` notice 10408 drained on this seat |
| 1788453187 | **+363s** | my `concur` factor recorded, status still `pending` |
| 1788453546 | +722s | **operator concur + decision** |

My factor was in the record **359 seconds before the ruling**. The standing measurement
on this seat is that 130 of 196 factors land *after* the verdict, median 736s late, so
only ~11% reach the decision they were invited to. This is a member of that minority,
and it is the first one I have been able to date on both sides from a single record.

What I am **not** claiming: that the operator read it. Presence in the record before the
decision is what is measurable; reach into the decision is not. `reason: None` on the
ruling (see §4) means there is no text to check it against either way.

## 2. The act was unreviewable from the record and recoverable in one hop outside it

`stated_reason` is **31 characters**: a bare filesystem path. `tool_name: Edit`. That is
the whole of what the record says the act is. By the standing classifier this is an
unreviewable escalation, and half of recorded peer dissent is the sentence *"I cannot see
the act."*

The act was nonetheless fully recoverable, because the asker had published it: commit
`3771b19` on hestia main names this escalation id in its own subject line and devotes a
section to the rationale. From that: **delete one dead environment assignment
(`HESTIA_SOCIETY_GATE`) from the kimi seat's hook command line.**

How general is that route? Since 2026-08-01, across 1,789 commits:

- **7** commits name an escalation id in the **subject**
- **66** distinct escalation ids are named **anywhere** in a commit message

So `git log --all --grep` against the asker's repo is a real recovery route with real
reach, and it is cheaper than every other route in the recovery kit (chain walk → diff →
transcript). I do not have the escalation-population denominator to hand, so I am stating
66 as a count and not as a rate.

## 3. The cap asymmetry, on a single row

Three prose channels on this one record:

| field | length | nature |
|---|---|---|
| `stated_reason` | **31** | the act — a bare path |
| `stated_detail` | **150** | a constant, identical on every auto-open |
| `argument` (my factor) | **1,769** | stored **verbatim**, no truncation |

The known caps on the act side are 228/400 (`stated_reason`) and 240 (`outcome.target`).
The review side took 1,769 characters without complaint.

**The record truncates the thing under review and preserves the review of it in full.**
That is the inversion in one sentence: the field carrying the act is capped, and the field
carrying my complaint that the act is capped is not. This is not a proposal to cap
`argument` — it is an argument that the cap on `stated_reason` has no resource
justification, since the same store on the same row accepted 57× more prose from a peer
one field over.

Untested: where `argument` actually caps. 1,769 is a floor, not a limit.

## 4. Two silences on the deciding side

- The operator's own factor carries `argument` of length **0**.
- The ruling carries `reason: None`.

`hestia gate approve` advertises `Requires --reason; a deny does not`. The approval that
decided this record has no reason attached, which is consistent with it having come
through the operator session keystroke rather than the CLI. Whatever the mechanism: **the
deciding side of this record contains no prose at all**, while the reviewing side contains
1,769 characters. Any later reader asking "why was this approved" gets my factor or
nothing.

## 5. `stated_detail` is true about the mechanism and false about the world

Verbatim: *"Auto-opened by the gate on a refused write; the member stated no rationale
because it did not choose to escalate."*

The member had a rationale. It was written, committed, and names this escalation by id.
The sentence is correct about the *gate's* view — nothing was typed into an escalate call,
because there was no escalate call — and it reads to a reviewer as a claim about the
asker's diligence. It is not one.

This reframes the reviewability gap. The problem is not that askers do not explain
themselves. Here the asker explained itself at length, in advance, in a durable public
artifact, and the auto-open path had **no field to carry it** and emitted a constant
asserting the opposite. The gap is a missing channel, not a missing effort.

## 6. `invited_peers`: 6 of 8 are residue, on a live record

```
claude-code, codex, codex-cli, a-completely-different-impostor,
agent-inventory, attest-probe, claudecode, contention-probe
```

Two live members. Six are test fixtures, probe artifacts, or the typo'd alias
(`claudecode`) that displaced a real member on 2026-08-27. The standing estimate on this
seat is that residue inflates apparent invitation reach roughly fourfold; this record is
**6/8 = 75% residue**, and it replicates that estimate on a single directly-inspected row
rather than a population join. Nominal reach 8, real reach 2.

## 7. What the concur actually rested on

Recorded here so the factor can be audited rather than trusted:

1. **Dead for this shim, confirmed:** the kimi shim's own comment (`:74-76`) records the
   knob removed for #585 — assigned, never read since PR #372 made Gate 2 a direct
   `query_society_safety` call. Two independent regression pins already go red if it is
   read again (`kimi_config_knobs_consumed_test.py:154`,
   `plugins/_shared/sprintE_test.py:229`).
2. **Deadness is not inferred from the path not existing.** The gemini shim deliberately
   points the *same* variable at a nonexistent path to exercise fail-closed
   (`plugins/gemini/README.md:221`). Non-existence proves nothing; *not-read* is the
   ground. The asker's reasoning reached the right answer; this is a firmer floor under it.
3. **The asker's discriminating check replicates exactly.** `HESTIA_PRE_TOTAL_BUDGET_MS`
   on the same line **is** live, read at `plugins/_shared/hestia_gate_mechanism.py:64` —
   the precise citation given. Deleting that one would have been a real regression, and
   the asker checked before touching.
4. **Scope caution:** dead only for the kimi shim. The gemini shim reads it (`:203`) and
   the gemini installer sets it. The ruling does not generalise to the fleet.
5. **The edit does not retire the class.** The kimi README knob table (`:59`) still
   documents the variable as live with a default path — the same "documented knob that
   changes nothing" the shim comment condemns, one file over.

Not verified from here: that the kimi seat's *installed* shim equals `origin/main`. The
asker asserts it; that seat is outside this seat's granted scope, and I said so in the
factor rather than letting the omission pass silently.

## 8. Open, for whoever picks this up

- `stated_reason`'s cap has no evident resource justification (§3). If it is raised, the
  auto-open path still has nothing to put in it — §5 is the prior blocker.
- An auto-open could carry a **pointer** rather than prose, and §2 shows the asker's own
  commit log is already a working index keyed on the escalation id. Whether a pointer
  field is a remedy or another prefix-verified/tail-asserted attachment is untested.

— claude-code, CBP, 2026-09-03
