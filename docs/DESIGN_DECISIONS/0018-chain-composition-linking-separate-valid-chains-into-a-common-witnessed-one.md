# 0018 — Chain composition: separate valid chains become a common witnessed evidence graph

**Status:** exploration / thread-opener — not a settled transitivity policy
**Date:** 2026-08-10
**Authors:** claude-code (CBP), cleaned/amended by GPT NOT-SAME review
**Frames it:** dp, 2026-08-10 — *"the LCT is a token. To be truly viable it needs to live on at
least one (preferably more) blockchain that is witnessed across multiple nodes… the bootstrap is
not a blocker — one chain one node is better than nothing, witnessed as such. But linking of hubs
into communities that compose chains, that is the real power."*

---

## 1. The thing being composed is evidence

An LCT is useful only to the degree its history can be independently witnessed and checked.
A local chain is already better than an unwitnessed assertion: it gives one node a durable ordered
history. A second independent chain recording a checkpoint of that history adds a new fact:

> another witness observed this exact chain state at this point in time.

That improves provenance and resistance to undetected rewriting. It does **not**, by itself, convert
witness count into trust.

Two witnesses may share an operator, model, key custodian, cloud failure domain, or upstream data.
Ten correlated witnesses can therefore add less evidence than two genuinely independent ones.

So the roadmap should not say:

```
more witnesses = more trust
```

It should say:

```
more independent, relevant, attributable witnesses = a richer evidence graph
T3 / V3 / MRH decide what that evidence means for a particular relying party and act
```

**Composition preserves evidence first. Evaluation comes later.**

## 2. What exists

| rung | mechanism | state |
|---|---|---|
| local atom | one node, one hash-linked witness chain | built |
| hub observation | `lct_publish` lets a hub ingest/witness an LCT | built, one-directional |
| cross-chain checkpoint | one chain durably records another chain's precise state | absent |
| evidence-path evaluation | relying party evaluates multi-hop witness paths under MRH/T3/V3 | absent |
| community composition | communities checkpoint / cross-witness member chains | absent |

The nearest existing primitive is already named by `hub verify-ledger`: internal chain verification
cannot detect a truncated tail; the verifier needs the head compared against an **independently
recorded value**. That independently recorded value is the first composition primitive.

## 3. Two valid histories do not need a common total order

Chain A and chain B each have their own valid total order. Composition must not manufacture a global
clock or merge-sort them into one synthetic history.

The correct base structure is an **evidence graph**:

- nodes are chain states / checkpoints;
- an edge says one chain observed another chain at a precise coordinate;
- each edge has an observer, authority, time, and signature;
- paths can later be evaluated for relevance and independence;
- contradictory edges remain visible rather than being normalized into one winner.

A community chain can be a higher-level checkpoint log over many member-chain heads. Peer chains can
also cross-checkpoint directly. These are compatible graph shapes, not competing global-order models.

## 4. First brick — signed cross-chain checkpoint

The first implementation increment is intentionally non-transitive and is split into #328.

Semantic record, version 1:

```
cross_chain_checkpoint_v1 {
    foreign_chain_id,
    foreign_position,
    foreign_head_hash,
    observed_at,
    observer_lct,
    observer_authority,
    foreign_genesis_hash?   // or equivalent stable chain-identity binding
}
```

The checkpoint means only:

> observer O, acting under authority A, observed foreign chain C at position P with head H at time T.

It does **not** mean:

- C is trustworthy;
- every act before H is endorsed by O;
- A trusts anyone who trusts C;
- B witnessing C automatically makes C trusted by A;
- two chains have merged;
- a fork has been resolved.

A checkpoint is **evidence, not delegated authority.**

## 5. Signature dependency

An unsigned checkpoint is only another assertion. The checkpoint must eventually be a signed act over
stable, independently reproducible bytes.

Dependency:

**#313 stable ActDigestV1 contract -> B2 signed chain record -> #328 checkpoint primitive.**

#313 therefore must freeze semantic signed fields rather than inherit `serde_json` bytes from a
foreign Rust struct. A composed fabric amplifies any ambiguity in signed bytes; it does not hide it.

## 6. Independence is an observed property, not a witness count

When a relying party later evaluates an evidence graph, it needs information about witness failure
domains, not only identities.

Examples of potentially correlated witnesses:

- two agents on one host under one operator;
- two hubs using one cloud account / KMS root;
- two models receiving the same upstream signed feed;
- two nominal communities whose checkpoint keys share one custodian.

T3/V3 can carry assessments of competence, evidence quality, behavior, and value. MRH bounds which
entities and paths are relevant to the relying party's current decision. None of those should be
collapsed into the checkpoint atom itself.

The checkpoint graph should preserve enough provenance that later evaluation can ask:

- how many distinct failure domains witnessed this state?
- how stale are their observations?
- are witnesses mutually dependent?
- what authority did each observer actually hold?
- is this path relevant inside this decision's MRH?

## 7. Transitivity is a policy question over paths

Suppose A checkpointed B and B checkpointed C.

The graph can truthfully say:

```
A observed B@h1
B observed C@h2
```

It must not silently upgrade that to:

```
A trusts C
```

Any derived statement across the path is an evaluation made by a relying party under an MRH and a
policy. Different parties may rationally assign different relevance/weight to the same evidence graph.

This is where bounded transitivity belongs: **in evaluation, not in the storage primitive.**

The first safe rule is therefore no automatic transitive trust at all. Build the graph before pricing
its paths.

## 8. Forks and contested state

Composition makes disagreement more visible, which is useful.

If two observers record competing heads for the same stable chain identity at the same/overlapping
position, both assertions remain legible. The system may label the state contested; it must not silently
choose “latest,” “most witnesses,” or “highest score” as truth.

Likewise, later revocation/key-rotation disagreement is evidence to surface, not noise to erase.

## 9. Genesis and joining

A one-node chain remains valid when it later joins a wider fabric. Composition must not require
re-genesis or replacement of the local history.

The sequence is additive:

**local chain -> externally checkpointed local chain -> mutually/community-witnessed evidence graph.**

That is important operationally: bootstrap can be weak and honestly labeled weak without being a dead
end.

## 10. Roadmap correction

`PRD_GOVERNANCE` currently puts this near the “hub seam (coordination, not construction).” That framing
is too small. Cross-chain composition is construction of the evidence substrate on which later
coordination and trust evaluation operate.

But the construction is **not** “make a common chain.” It is:

1. stable signed acts;
2. stable signed chain state;
3. signed checkpoint edges;
4. contested-state representation;
5. witness-path / independence representation;
6. MRH/T3/V3 evaluation over those paths;
7. community checkpoint structures where useful.

## 11. What this decision commits to now

Only three things:

1. **Use an evidence graph, not merged histories, as the composition model.**
2. **Build #328 first:** a signed, non-transitive cross-chain checkpoint assertion after the signed-act
   substrate is stable.
3. **Do not encode automatic trust propagation into the checkpoint primitive.** Preserve provenance so
   later policy can evaluate paths honestly.

Mutual binding, liveness, failure-domain independence, community checkpoint trees, contested-state
resolution policy, MRH path semantics, and bounded transitivity remain open work.

## 12. Honest status

Hestia has a local atom and the beginnings of hub observation. It does not yet have a multi-community
witness fabric.

The first useful step is smaller than “federation” and more precise than “trust”: one signed chain
records exactly what it observed about another signed chain. Once those facts exist, the hard questions
about independence, relevance, and transitivity become answerable without inventing authority by
implication.

---

*Thread opened by claude-code (CBP) at dp's direction. GPT amendment removes unrelated onboarding code
from the branch and narrows the first brick to provenance. Implementation issue: #328.*
