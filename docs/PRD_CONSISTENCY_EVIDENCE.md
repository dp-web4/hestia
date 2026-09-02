# PRD — Consistency Evidence, Adjudication, and Reputation

**Status:** proposed · **Date:** 2026-09-02 · **Origin:** `tools/grounds_vs_acts.py` / PR #809

## 1. Purpose

Hestia can increasingly observe two different things about a participant:

1. what the participant states as grounds, constraints, beliefs, or reasons; and
2. what the participant actually does, as witnessed by the action chain.

PR #809 demonstrates that these registers can diverge for long periods without either register being false on its own. A participant can act correctly while carrying an inaccurate explicit model, correct its prose before its conduct, correct its conduct before its prose, or produce language that merely resembles a contradiction.

This PRD defines how Hestia should turn those divergences into inspectable evidence, route them through adjudication, and only then permit them to affect contextual reputation.

The core invariant is:

> **Detection is not adjudication, and adjudication is not reputation.**

This extends `PRD_ASSURANCE.md` FR-4: reputation derives from the active adjudication graph with provenance, never from raw counts.

## 2. Non-goals

- No generic hypocrisy detector.
- No direct reputation debit from a regex, classifier, LLM judgment, or candidate count.
- No global reputation score.
- No requirement that all natural-language statements be indexed.
- No deletion of historical evidence when a statement is corrected.

## 3. The evidence model

### 3.1 Consistency axis

A **consistency axis** defines one bounded question in a versioned form:

- `axis_id` + `axis_version`;
- statement extractor/predicate;
- conduct selector;
- join/classification function;
- evidence requirements;
- known miss/false-positive classes;
- permitted adjudication outcomes.

PR #809's first axis is `escalation_corroboration_terminality`: stated claims about whether factors can be filed on terminal escalations versus witnessed factor filing.

A second materially different validated axis is required before this structure becomes a stable generic API.

### 3.2 Statement evidence

A statement candidate MUST retain:

- author identity and role/context if known;
- source record identifier;
- immutable content hash;
- exact evidence span or typed proposition;
- extraction method/version;
- timestamp and supersession/correction relation if known;
- visibility class.

Typed grounds carried inside governed records SHOULD be preferred over prose extraction. Prose mining is an evidence-discovery mechanism, not a privileged truth source.

### 3.3 Conduct evidence

Conduct evidence MUST resolve to witnessed records and carry enough information for an independent reader to reproduce the classification:

- chain/event identifiers or hashes;
- subject and role/context;
- event type + relevant fields;
- event time/order;
- referenced terminal/decision/related acts;
- chain head/genesis or equivalent observation anchors;
- extractor/version.

Cached or projected data is acceleration only; it MUST preserve references back to canonical evidence.

## 4. Consistency case

A detector MAY create a durable `ConsistencyCase` when both sides of an axis expose a divergence surface.

Minimum conceptual fields:

```text
case_id
subject_lct
role_lct / context
axis_id
axis_version
statement_evidence[]
conduct_evidence[]
observation_anchor
opened_at
status: open | adjudicated | superseded | withdrawn
supersedes / superseded_by
adjudication_ref?
```

Creation of a case means only: **adjudication is warranted**.

It MUST NOT mean contradiction, deception, fault, or reputation loss.

## 5. Incremental evidence cache

PR #809 validates full head-to-genesis traversal as a deep-audit method. Routine operation MUST instead support O(delta) refresh.

### 5.1 Chain cache

An incremental chain cache SHOULD retain:

- chain identity/genesis anchor;
- cached `head_hash` and `head_position`;
- completeness flag + observed span;
- parser/schema/tool version;
- normalized relevant event records;
- optional derived indexes keyed by axis, subject, role, and related object id.

Refresh procedure:

1. read current head;
2. if current head equals cached head, do nothing;
3. walk backward from current head until cached `head_hash` is reached;
4. verify every hash link;
5. merge only newly observed entries;
6. atomically publish the new cache and high-water mark.

If the cached head cannot be reached, chain identity differs, continuity fails, or the parser/schema contract is incompatible, the cache MUST be invalidated and rebuilt.

The cache MUST never be treated as independent evidence.

### 5.2 Statement cache

Statement extraction SHOULD maintain a manifest keyed by:

- source id/path;
- content hash;
- author attribution;
- extractor version;
- supersession state.

Only new or changed records require rescanning.

## 6. Adjudication

A `ConsistencyCase` enters the existing adjudicator ladder rather than inventing a parallel verdict system.

Adjudication MUST be able to distinguish at least:

- no contradiction / extractor false positive;
- contextual exception;
- mistaken stated grounds;
- mistaken conduct;
- stale grounds later corrected;
- unresolved ambiguity / insufficient evidence;
- deliberate or repeated misrepresentation only when evidence actually supports that stronger finding.

Adjudication itself is a witnessed record with provenance and MAY be appealed/superseded under existing governance law.

The detector SHOULD expose evidence, chronology, known limitations, and correction relations. It SHOULD NOT recommend a moral interpretation.

## 7. Reputation integration

### 7.1 Hard prohibition

**Raw detector output MUST NOT directly modify T3/V3 or any standing score.**

This includes:

- candidate count;
- divergence count;
- post-terminal count;
- LLM classification confidence;
- regex match count;
- age of an unresolved case.

### 7.2 Adjudicated bridge

Only a valid adjudication MAY emit an R7 reputation observation/delta.

The mapping from adjudication outcome to tensor dimension, magnitude, decay, and role scope MUST be society-law controlled.

The evidence graph SHOULD preserve distinctions such as:

- self-discovery and prompt correction;
- correction after peer challenge;
- repeated recurrence after correction;
- contextual exception correctly explained;
- refusal to correct an adjudicated false claim;
- conduct that precedes conceptual correction;
- stated model that precedes behavioral correction.

These are not equivalent observations and MUST NOT be collapsed into a single "consistency score."

### 7.3 Explainability requirement

Every reputation value affected by consistency adjudication MUST be traceable:

`current role-context standing -> applied R7 observations -> adjudications -> consistency cases -> source evidence`

A score without that path fails the Hestia assurance model.

## 8. Privacy and scope

Evidence visibility MUST never exceed the visibility of its source merely because an analyzer can read it.

- private or role-scoped statements remain private/role-scoped;
- derived case summaries MUST avoid leaking protected source text;
- adjudicator eligibility must satisfy the source evidence's access law;
- exported/federated reputation may carry adjudicated outcome + provenance references without exporting private evidence itself.

Consistency analysis MUST NOT become a surveillance bypass.

## 9. Operational surfaces

Hestia SHOULD eventually expose:

- open consistency cases for the local participant/fleet;
- case evidence + chronology;
- adjudication status;
- corrections/supersessions;
- cache high-water marks and completeness;
- per-axis detector version and coverage limits.

Operator UX MUST distinguish:

- **candidate**;
- **adjudicated finding**;
- **reputation consequence**.

## 10. Acceptance criteria

Before this PRD is considered implemented:

1. PR #809's axis runs incrementally without full chain traversal during routine refresh.
2. A cold rebuild and incremental refresh produce identical conduct classifications for the same head.
3. Cache continuity failure provably forces rebuild rather than silently accepting divergence.
4. Statement cache invalidates on content change and extractor-version change.
5. A detector can create an inspectable case without changing reputation.
6. A known false positive can be adjudicated clear with zero reputation consequence.
7. An adjudicated case can emit an R7 observation only through society law.
8. The resulting role-context reputation can be traced back to the adjudication and source evidence.
9. Corrections supersede active propositions/cases without deleting history.
10. A second materially different consistency axis validates the generic case schema before it is frozen.

## 11. Relationship to PR #809

`tools/grounds_vs_acts.py` remains a bounded research instrument and reference implementation for the first axis. It SHOULD NOT absorb this PRD's full framework.

The correct evolution is:

1. merge the bounded instrument;
2. make its evidence acquisition incremental;
3. validate a second axis;
4. extract shared case/evidence contracts;
5. connect adjudicated outcomes to the existing R7 path.
