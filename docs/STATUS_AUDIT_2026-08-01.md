# Documentation status audit — 2026-08-01

**Auditor:** claude-code (CBP) · **Prompted by:** dp
**Method:** every claim checked against the running daemon, the chain, or the source on
this machine. Where a claim could not be checked, it says so rather than being softened.

> dp, 2026-08-01: *"currently hestia repo docs lead with 'verified presence for ai and
> humans'. that's the goal but we're short of that still. we do have multi-vendor agentic
> ai governance that is well along."*

---

## The finding, in one line

**The docs described the destination and the code arrived somewhere else — somewhere
better-evidenced.** The headline claimed universal presence; the thing that actually runs
every day, and has a year of scars behind it, is multi-vendor agentic governance. The
strongest part of the system was the least represented.

## Why this is the same defect the codebase keeps finding

A status table with one column — *Working* — cannot distinguish three different states:

1. exercised daily, with chain entries behind it,
2. code and tests exist, nobody has driven the path,
3. not built.

Collapsing those reports success while measuring nothing, which is the exact class this
repo has been cataloguing all week (`witness_append` gated by no rule; `ci_discovery`
buckets with no `UNACCOUNTED` check; a gate installed but not enforced). A README is a
surface like any other, and it had the defect it warns about.

So the table is now three tiers, and *plumbed* is a first-class answer rather than a
softer way of saying working.

## What was checked, and how

| Claim | Method | Result |
|---|---|---|
| "12 MCP tools" | `tools/list` against the live daemon | **29.** Stale by 17. |
| "Cross-platform app… the primary human interface" | `git log -- app/`, file count, observed use | 374 files, last substantive commit **2026-07-24**. The **web dashboard** is what is used daily. Demoted to *plumbed*. |
| "Constellation — Working" | 1,183 LOC, 21 unit tests; `hestia_query_history` over a 500-entry window | Code and tests real; **zero constellation events in the live chain**. Never driven on a real second device. → *plumbed*. |
| "Credential issuance — Working" | endpoints present and gated | No wallet round trip performed here → *plumbed*. |
| Multi-vendor governance | `plugins/` inventory + chain `plugin_id` distribution | Six vendor surfaces (claude-code, codex, kimi, gemini, cursor, openclaw). Two vendors with witnessed acts in the sampled window (`claude-code` 335, `kimi-code` 43). **Under-claimed, not over-claimed.** |
| Gate assurance | `docs/PRD_ASSURANCE.md`, `GATE_BYPASS_CATALOG.md` | A1 confirmed; ceiling now stated *with* the capability table rather than below it. |
| `#honest-status` anchor | grep | Exists. An earlier claim in session notes that it was a dead link was **my grep pattern being wrong**, not the doc. Recorded so the correction outlives the mistake. |

## What the audit could NOT verify

Stated rather than assumed:

- **Chain length.** `witness.db` is SQLCipher-encrypted and the counting API is behind the
  operator gate. "~86k" is an extrapolation from the last published figure (61k on
  2026-07-26) plus observed daily growth. It is not a measurement.
- **Whether the Tauri app still builds** against current daemon APIs. Not attempted.
  *Plumbed* is a claim about exercise, not about compilation.
- **Constellation on real hardware.** Absence of chain events proves it has not run *here*;
  it does not prove it fails.
- **Whether other fleet machines** exercise paths this box does not. The audit covers one
  reference machine.

## Changes made

1. **Headline rewritten.** Leads with multi-vendor agentic governance; names universal
   presence as the destination and says plainly that the project is short of it.
2. **Status split into Measured / Plumbed / Not built**, with the evidence column carrying
   *how we know* rather than a restatement of the claim.
3. **New "Hub membership" section** (dp: *"link it as key to hub access"*). Frames
   governance as the entry condition — a hub asks who/what-may-it/what-has-it-done, and
   Hestia is where those answers are made. Includes the limit: a hub should not treat
   Hestia's word as proof at A1; the product is inspectable evidence, not a verdict.
4. **Assurance ceiling moved next to the capability table** instead of below it, so nobody
   reads the capabilities without the A1 qualifier.
5. **Prior table retained** under *Superseded*, per the standing rule against deleting
   scaffolding — a stale claim that is visibly stale is more useful than one erased.

## Not yet done — for the next pass

- `docs/PRD.md`, `ARCHITECTURE.md`, `PROTOCOL.md` not audited. `PRD.md` predates the
  governance work and likely carries the same destination-first framing.
- The **Claude Code plugin README states PreToolUse gating is not built.** It is, and it
  denied nine commands on 2026-08-01. Directly contradicts the shipped code.
- No doc describes **escalation, per-member policy grants, the gate CLI, or the
  Temperament ladder** — all landed 2026-07-29..08-01, all user-visible, none documented.
- `README` "What Hestia is not" appears **twice** (§ at two heading levels).
- The gate's own `deny` text is user-facing documentation and was not reviewed here.

## The rule worth keeping

**Docs drift toward the pitch; code drifts toward the pain.** The gap is not dishonesty,
it is that nobody re-reads a headline after the work moves. The countermeasure is the same
one used everywhere else in this repo: separate *what is claimed* from *how we know*, and
make the second column mandatory. A status line with no evidence column will always
eventually be a wish.
