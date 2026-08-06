# 0012 — Salience-gated retention: a short attention window, a durable digest

**Status:** accepted direction, not yet built
**Date:** 2026-08-06
**Decided by:** dp
**Supersedes in practice:** the assumption that dashboards, stats and trust derive from *rescanning history*

---

## The ruling

> dp, 2026-08-06: *"the attention window should be fairly short, only dramatic events should be tracked permanently (as a section in vault that points to chain for details). it's the same salience gating and memory retention problem that snarc/membot are aimed at, fractally applied to hestia (and hub)."*

And the companion, which is what makes it safe to act on:

> *"the stats are questionably meaningful currently, and aren't actually used in any decisions. it's display-only, so i wouldn't treat them as sacred."*

---

## What this replaces

Today every routine read is a **rescan of history**:

| surface | read | per |
|---|---|---|
| dashboard stats | `read_recent(10_000)` | poll |
| dashboard feed | windowed read | poll |
| trust derivation | the same 10,000-row window | poll |
| `/api/chain` | up to 10,000 | request |
| governance ledger | 5,000 governance events | request |
| escalation replay | 5,000 | startup |

Measured 2026-08-06: the daemon went 164 MB → 1349 MB in twenty-one minutes of ordinary use, `Anonymous` 1364 MB of `Rss` 1382 MB, **flat at idle and stepping on every heavy read**. The previous instance reached 1774 MB and was still climbing when a crash took it. All of it heap retained from parsing documents to harvest a dozen scalars.

The projection work (`scan_recent`, PR #217) makes each of those reads *cheaper*. **This decision says most of them should not happen at all.**

That distinction matters, because optimising a rescan makes the rescan look affordable, which is how it becomes permanent.

## The shape

Three tiers, and the fractal claim is that this is the same shape snarc and membot already implement one level down:

| tier | holds | lifetime | who reads it |
|---|---|---|---|
| **attention window** | the last N minutes of acts | short, bounded, cheap to rescan | live feed, "what is happening now" |
| **durable digest** (vault) | salient events + running aggregates, **each pointing at its chain entry** | long | stats, trust, ledger, "what has this member been" |
| **chain** | everything, append-only, hash-linked | forever | the detail behind any digest row; audit; replay |

The digest is a **projection with pointers**, never a second copy of the record. A digest row says *"this happened, here is its hash"* — so the chain stays the single source of truth (the one-chain ruling of 2026-08-04 is untouched), and the digest is a salience-selected index into it.

## What "dramatic" means, and why it must be defined in law

The gate is the whole design. Everything hangs on which events are retained, and that is a **governance question wearing a performance costume** — a member whose bad act is judged non-salient is a member the record forgets.

So the salience predicate:

- lives in the vault as **policy**, not as a constant in the reader (§4.1, "the vault is authority");
- is **per-role** where it needs to be — an Archivist's threshold is not a Policy-Entity's (D-1's shape, applied again);
- must be **loud when it drops** — a retention rule that silently discards is the biased-clean-chain failure with a new cause. The digest carries what it *excluded* in aggregate, so "nothing salient happened" is distinguishable from "nothing was looked at."

Obvious first candidates, all already event types: `policy_decision` with `decision=deny`, every `gate_escalation_*`, `appeal` / `adjudication` / `reversal` / `amnesty`, `policy_edit`, `policy_instance_grant*`, `scope_granted` / `scope_refused`, `agent_ungovern`. Which is very nearly `GOVERNANCE_EVENTS` — the ledger's taxonomy is already a salience filter that nobody called one.

Routine `outcome` entries are the bulk of the chain and are exactly what a short window should cover and a digest should aggregate rather than enumerate.

## Consequence for trust

This is why the ruling arrived attached to the trust discussion.

`derivation::derive` currently folds a 10,000-row rescan. Under this design it folds **the digest**, which is:

1. bounded — no rescan, so the memory problem stops being a memory problem;
2. **modular** — the model reads a digest, so replacing the heuristic with a real T3/V3 fold changes only what the dashboard displays, which is dp's stated requirement;
3. honest about its own basis — the digest records the salience generation that produced it, so a trust number can say *which retention law* it was computed under.

The `TrustModel` boundary (declared evidence types, `ModelBasis::Provisional`, a `DerivedTrust` the dashboard consumes) is the natural seam and should land **before** the digest, so the digest has a consumer whose needs are stated rather than inferred.

## Sequencing

1. **`TrustModel` boundary.** Declares its evidence needs; wraps today's heuristic as `Provisional`. No behaviour change. Makes the current model's placeholder status visible on the surface that displays trustworthiness — which it is not today.
2. **Salience policy in the vault**, in WARN: classify each appended event, record what *would* be retained, change nothing. Produces the number nobody has — what fraction of the chain is salient.
3. **Digest + pointers**, written on append, read by stats/trust/ledger.
4. **Shorten the attention window** once the digest carries what the long window was there for.
5. **Retire the rescans.**

Step 2 first if only one: it is observe-only, it needs no new authority, and it answers the question the rest depends on. Same discipline as Sprint 1.

## What this does not change

- **One chain.** The digest points; it does not duplicate. A digest that disagreed with the chain would be the two-copies-no-comparison shape dp ruled out on 2026-08-04.
- **The chain is still complete.** Salience gates *attention*, never *recording*. Nothing stops being witnessed; some things stop being rescanned.
- **Errors still fail loud.** A digest read that fails must set its own `unavailable` flag. The distinction between "nothing happened" and "I could not look" survives this change, or the change is not worth making.

## Open

- Does the digest live in the vault as policy-adjacent state, or beside it? dp's phrasing says "a section in vault", which implies the former and therefore operator-gated, generation-tagged mutation.
- Retention of the digest itself — does a salient event age out, and if so into what?
- Hub's copy of this problem is the same shape at a larger radius and is hub's to sequence.
