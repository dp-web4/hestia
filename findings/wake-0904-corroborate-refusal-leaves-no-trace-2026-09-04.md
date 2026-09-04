# A refused same-name corroboration leaves no trace on the escalation

**Seat:** claude-code on CBP, mesh wake 2026-09-04T09:06Z (notice 10900, `hestia://escalation/64f8b225736992f3#withdrawn`)
**Status:** measured live; one leg is a source read and is labelled as such.

## What happened

A sibling `claude-code` seat (session `9261dc9a…`, `role:constellation:interactive-dev`) was
building the shim-certification checker dp asked for and kept tripping the governance-write
gate. Three escalations in six minutes, all `asker_basis: session`:

| chain | UTC | event |
|---|---|---|
| 231654 | 09:06:10 | `gate_escalation_opened` `64f8b225736992f3` — Bash, `sovereign_plus_peer` |
| 231656 | 09:06:21 | `gate_escalation_withdrawn` — `self_withdrawn`, "a for-loop put it out of grammar; the marker appeared as loop data" |
| 231659 | 09:07:02 | `gate_escalation_opened` `a5bb834a2250206e` — `Write -> plugins/_shared/shim_certification_test.py`, `single_approver`, 8 invited (7 `invited_without_reader`, 1 absent) |
| 231692/3 | 09:08:59 | `gate_escalation_corroborated` ×2 — **codex, DISSENT**, on both |
| 231713 | 09:10:34 | **my corroboration attempt — REFUSED** |
| 231716 | 09:10:58 | `gate_escalation_opened` `d82fc81d4354212e` |
| 231719/20 | 09:11:07 | `operator_gate` → `gate_escalation_decided` `a5bb834a2250206e` **approved**, `bar_met: true`, `decided_by: operator` |

I was woken holding evidence about `a5bb834a2250206e` from the tree at `80fd180`: the target
path follows the directory's own convention (`plugins/_shared` already holds 12 sibling
`*_test.py` files), and `docs/PRD_SHIM_CERTIFICATION.md` is an in-flight five-commit series
whose C1–C11 criteria are what such a test would check. I offered it as a `concur`, stating
in the argument itself that I assert the asker's own `plugin_id`, that I was not invited, and
that the factor must not be counted as the peer conjunct.

```
$ hestia gate corroborate a5bb834a2250206e --as claude-code --stance concur --argument "…"
error: hestia_gate_escalation_corroborate refused: you may not corroborate this:
  Refused { reason: "'claude-code' cannot arbitrate its own appeal — an appeal upheld by
  its filer is an assertion wearing a verdict's clothes, and the scale would pay 1.0 for it" }.
  Evidence about your own gate write is not a second factor — it is the first one wearing a hat.
```

**The refusal is correct. Its silence is the finding.**

## What the record shows afterwards

Nothing. There is no `gate_escalation_*` event for a refused corroboration. `factors_present`
on `a5bb834a2250206e` carries codex's dissent and nothing else. A later reader — which the
operating law says is the whole of what a factor buys ("it is stored verbatim against the
escalation and it is what a later reader weighs") — cannot distinguish:

- no same-name member had anything to say, from
- one did, said so honestly, and the door dropped it.

The 340-word argument survives on the chain **only as an accident of transport**: it is inside
the `target` string of the Bash `outcome` at 231713, because I happened to use the CLI. A caller
reaching `hestia_gate_escalation_corroborate` over MCP leaves no factor, no refusal event, and
no command text — nothing at all.

## Mechanism

`core/src/server/handler.rs:18286` (`tool_gate_escalation_corroborate`), at `bb00230`:

1. `stance` and `argument` are parsed and validated (≈18325–18362) — the door's own comment
   calls this "REFUSE WHAT YOU WILL NOT HONOUR", the #367 fix.
2. `eligibility()` is called at ≈18378, **after** that validation.
3. On any non-`Eligible` variant the function returns the error and `argument` is dropped.

`core/src/arbiter.rs:267`, clause 1, is plain string equality: `p.arbiter == p.appellant`.

## Why this is a defect and not the design

The codebase already draws the distinction I am asking for, one branch away. `Eligibility::SelfWithdrawal`
(`arbiter.rs:269`) exists precisely so a self-directed act is **recorded as its own act rather than
refused**, and the `gate_escalation_withdrawn` payload states the principle in the assurance line:

> "NONE — the asker refused its own request. Nobody reviewed this and nothing was authorised;
> it is recorded so the attempt and its abandonment both stay visible."

*Recorded so the attempt stays visible.* The corroborate path takes the other option for the
structurally identical case.

And the machinery to record-without-counting is already built: factors carry
`independence: Option<Independence>` "so a reader can weight it" (the call site's own words),
`GateEscalations::corroborate` already takes it as an `Option`, and a `null` tier already occurs
in live data (the self-withdrawal factor on `64f8b225736992f3`).

## Proposed

Keep the DECIDE bar exactly as it is — NOT-SAME is right for arbitration, and a same-name factor
must count toward no conjunct of any bar. Change only the corroborate leg:

- admit the factor with an independence tier meaning *same name, grades nothing* (a new variant, or
  `None` with a `self_declared: true` marker);
- record `argument` verbatim and emit the `gate_escalation_corroborated` event;
- exclude that tier from every bar conjunct, and render it distinctly on the pending view.

Cost of not doing it: the class of member most likely to be awake in a single-name fleet is the one
whose evidence is discarded without trace. On this wake there happened to be a live independent peer —
codex answered both escalations within ~2 minutes — so nothing was lost that mattered. That is luck,
not structure.

## Explicitly not claimed

The refusal message says "cannot arbitrate its own **appeal**" on the corroborate path; the
`eligibility()` text is appeal-specific and the wrapper adds the right sentence, so this is
cosmetic and is not the finding.

I did **not** run the "assert a different name and be admitted" leg. Asserting `--as <other>` would
be a recast — which the operating law scores below plain compliance — and would put a fraudulent
factor on a live petition. That clause 1 is string equality over a caller-chosen name is a SOURCE
READ (`arbiter.rs:267`, and clause 0's own comment names the hazard: "a forged `codex` is not the
sentinel and still grades CrossVendor"). It is also **out of scope by declared assurance**: every
escalation payload states `A1 — cooperative gate, same-UID operator … tamper-EVIDENT, not
tamper-proof`. Under A1 a typeable name is accepted, not a defect. That is exactly why the *record*
leg is the one worth fixing: tamper-evidence is the whole of what A1 promises, and a refusal that
writes nothing is a hole in it.

## Not filed, observed

- `a5bb834a2250206e` was approved for `Write -> plugins/_shared/shim_certification_test.py`;
  `d82fc81d4354212e` and `df482915c802aa9c` then had to be opened for `cp` and for a Bash
  pipeline producing **the same bytes at the same path**, and `df482915…` was withdrawn as
  "a duplicate: `a5bb834a…` is ALREADY APPROVED for exactly this effect". One effect, three
  petitions, because the act digest binds the spelling. This is the converse face of #539 and
  was already visible to the asker, so it is recorded here rather than filed.
- The fleet is **not** idle. My previous wake reported the corroboration machinery "idling
  against a dead fleet" after a full cycle in which every invitation bounced. Refuted here:
  codex corroborated two escalations within ~2 minutes of their opens and bound `review_done`
  notices to both invitations, and the operator ruled twice inside four minutes. The earlier
  reading was a true measurement of one hour, wrongly generalised.
