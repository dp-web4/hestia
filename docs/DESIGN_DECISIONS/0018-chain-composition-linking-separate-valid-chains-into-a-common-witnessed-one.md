# 0018 — Chain composition: linking separate valid chains into a common witnessed one

**Status:** exploration / thread-opener (NOT a settled decision — the mechanisms are the open work)
**Date:** 2026-08-10
**Author:** claude-code (CBP), opening the thread at dp's direction
**Frames it:** dp, 2026-08-10 — *"the LCT is a TOKEN. To be truly viable it needs to live on at
least one (preferably more) blockchain that is witnessed across multiple nodes… the bootstrap is
not a blocker — one chain one node is better than nothing, witnessed as such. But linking of hubs
into communities that compose chains, that is the real power. I don't think we've addressed those
mechanisms yet — linking previously separate but valid chains into a common one."*

---

## 1. Why this is the real power, not a feature

An **LCT is a token.** A token's value is not in being *asserted*; it is in being **witnessed across
independent nodes**. A token witnessed by one node is a self-attestation. The same token witnessed
by many independent nodes is *trust* — because forging it now requires colluding across parties that
do not share an interest.

So the trust gradient is a **witness gradient**:

```
self-attested (0 witnesses)  <  one node, one chain  <  one hub witnesses me  <  many independent
                                  (the bootstrap)        (hub-and-spoke today)     communities compose
                                                                                    (the real power)
```

Everything Hestia has built lives at the left three rungs. The fourth — **communities composing
their chains so a token gains multi-community witness** — is unbuilt, and it is where the token
becomes viable in dp's sense. This decision opens that thread.

## 2. What exists, measured (2026-08-10)

| rung | mechanism | state |
|---|---|---|
| atom | per-node witness chain (`SqliteChainStore`, hash-linked, genesis at bootstrap); LCT minted + **locally** witnessed | **built** — #324 makes `init` mint the sovereign LCT into it |
| hub-and-spoke | `lct_publish` → a hub registry ingests (5-check) so "presence becomes witnessed presence" | **built, one-directional** — the hub witnesses my LCTs; my chain does not witness the hub's, and two members' hubs do not witness each other |
| **composition** | two separate valid chains link into a **common** witnessed history; a token on chain A gains chain B's witness | **absent** — grep of the witness/storage layer for anchor / cross-witness / checkpoint / federate / compose finds **nothing** |

The nearest existing primitive is a *tell*, not an implementation: `hub verify-ledger` says, unprompted,
that a chain verifying internally proves nothing about completeness — *"removing entries from the tail
leaves a chain that verifies; compare the head hash against an independently-recorded value."* **That
independently-recorded value is a cross-witness. The tool names the need and nobody built the recording.**

## 3. The core difficulty, stated honestly

**Two valid histories do not linearize into one.** Chain A and chain B each have an independent total
order; there is no single "common chain" that is their merge without picking a global clock nobody has.
So "link into a common one" cannot mean *concatenate* or *merge-sort*. It must mean one of:

- **(a) Mutual head-anchoring.** A periodically writes B's current head hash into A's chain, and B
  writes A's into B's. Neither history changes; each becomes a **witness of the other's head at a point
  in time.** A token on A, once A's head (which covers it) is anchored into B, is transitively witnessed
  by everyone who trusts B. This is the smallest real composition, and it is exactly the
  "independently-recorded value" `verify-ledger` asks for.
- **(b) A community chain (chain-of-chains).** When hubs link into a community, a **higher chain**
  witnesses the member chains' heads on a cadence — a checkpoint tree. Member chains stay
  locally valid and sovereign; the community chain composes them by witnessing, giving every token
  under it multi-community validity without merging histories. This is how "hubs compose chains."
- **(c) Both, at different scales.** (a) is peer-to-peer composition (two communities cross-anchor);
  (b) is hierarchical composition (many communities under a witnessing community). MRH suggests both:
  trust composes along the relevancy horizon, which is neither purely flat nor purely hierarchical.

## 4. The mechanisms this thread must design (the open work)

1. **The anchor record.** A chain event kind — `chain_anchor { foreign_chain_id, foreign_head_hash,
   observed_at, signer }` — signed by the recording chain's key. This is the atom of composition and
   the smallest first increment. It composes cleanly with #313 (act-digest / signed chain): an anchor
   is just another signed act, so **B2's signature column is the prerequisite** — an unsigned anchor
   witnesses nothing.
2. **Bidirectional binding & liveness.** A one-way anchor is hub-and-spoke again. Composition is
   *mutual* — the handshake by which two chains agree to witness each other, and what it means when one
   stops (a community leaving is a real event, not a fault).
3. **Trust transitivity + its bound.** If A anchors B and B anchors C, is a token on C witnessed for A?
   Transitivity is the power *and* the attack surface — unbounded, it launders trust through one
   compromised community. This is where **T3/V3 and MRH stop being ornamental**: the composed witness
   is weighted by the trust tensor along the path, and the MRH bounds how far a witness propagates.
4. **Conflict / fork.** Two chains that compose may hold contradictory records about the same LCT
   (a key rotation seen differently, a revocation one side missed). Composition needs a **contested**
   state, not a silent winner — the same discipline as everywhere else: refuse to resolve what should
   be surfaced.
5. **Genesis vs join.** A chain born alone (the #324 bootstrap) and a chain that composes on day one
   are different. The bootstrap must remain valid and later *compose without re-genesis* — "one chain
   one node" grows into the fabric, it is not thrown away for it.

## 5. Where it sits, and the roadmap correction

`PRD_GOVERNANCE` §12 files this under **Sprint 7 — "the hub seam (coordination, not construction)."**
That label is wrong, and this decision is the correction: **chain composition is construction, and it
is the construction that makes the token viable.** Coordination (member-mesh, notices) rides *on top of*
composed chains; it is not a substitute for them. The sprint should be re-scoped from "wire the hub
seam" to "compose chains," with §4's five mechanisms as its spine.

It also re-frames the identity vertical (0014, #313, #318): the act-digest and signed chain are not
only for local accountability — they are **the substrate composition requires.** An anchor is a signed
act over a foreign head; without #313's signed-act contract there is nothing to anchor with. So the
dependency is explicit: **#313 → B2 signed chain → chain_anchor → composition.**

## 6. What this decision commits to now

Only the framing and the first increment:

- **Adopt the witness gradient (§1) as the trust model's spine** — trust is measured in independent
  witnesses, and the roadmap's north star is moving tokens rightward along it.
- **First increment: the `chain_anchor` event (§4.1)**, once B2's signed chain lands — a chain can
  record another chain's head as a signed, witnessed act. That alone moves us from hub-and-spoke to
  the first real peer composition, and it is small.
- **Everything else in §4 is open**, and this doc is the place they get designed. Mutual binding,
  transitivity-with-a-bound, fork/contested, and compose-without-re-genesis are named as the hard work,
  not hand-waved as done.

## 7. The honest status line

We have built the **atom** (a locally-witnessed token) and the beginnings of **hub-and-spoke** (a hub
witnesses my tokens). We have **not** built the **fabric** (communities composing chains so tokens gain
multi-community witness). The fabric is the real power, its substrate is the signed chain we are already
building, and its first brick is one signed record of a foreign head. This decision names the gap so the
fleet stops mistaking the atom for the fabric — the exact error this session's deployment-truth and
"merged ≠ in force" findings kept catching, now at the layer that matters most.

---

*Filed by claude-code (CBP), opening the deepest thread on the map at dp's direction. Grounded: the
witness-layer grep returns no composition primitive; `lct_publish` is one-directional; `verify-ledger`
names the cross-witness it lacks. The mechanisms in §4 are the open work — this is a thread-opener, and
it wants GPT and every seat that has thought about MRH/T3-V3 to build it out, especially §4.3's
transitivity bound.*
