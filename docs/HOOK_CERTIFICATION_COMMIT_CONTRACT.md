# Hook certification: commit and recovery contract

2026-10-24. Proposed slice 3b, following the
[read-only candidate preflight](HOOK_CERTIFICATION_PREFLIGHT.md).
This incorporates the independent ordering review on
[#1157](https://github.com/dp-web4/hestia/issues/1157#issuecomment-6374889713).

**Design plus executable model, not an implemented certification service.**
There is no new endpoint, vault schema, live-chain writer, projection reader,
startup repair, or automatic recovery action here. #1157 remains open.

## Evidence boundary

The first implementation should use the chain-witness envelope proposed in
[#1322](https://github.com/dp-web4/hestia/pull/1322), not introduce a second receipt
format. As of reviewed head `3eddb071`, the boundary-loss and temporary-snapshot
repairs have been source-reviewed; the author reports 42 chain tests passing.
Activation on an existing unsigned chain is still held separately. Merely merging
a signing primitive would not authorize migration or establish that a running
chain actually signs.

Certification must require a signed authorization row on its actual running
chain. A wholly unsigned history can satisfy `signatures_authentic()` in that
proposal: the predicate means there are no signature failures, not that a required
signature exists. A valid signature from a self-declared witness is likewise not
operator authority. Bind and verify:

- an authenticated operator principal and authority for this member and act;
- the exact reviewed candidate, revalidated at selection time;
- operation ID, reason, member, and expected prior certification ID;
- exact chain ID, position, row hash, expected witness identity/key and applicable
  policy evidence, including the operator authorization evidence reference;
- durability covering that exact row, not merely a previously flushed row.

The first authority-bearing cut refuses candidates with nonempty
`unverified_dependency_labels`. Content-matching dependency bytes do not establish
their claimed publication provenance. Candidate revalidation cannot establish
publication origin on its own either; the operator's review needs an independently
established provenance basis. Unknown authority or unavailable evidence is a hold,
not a fallback to a local identity, unsigned row or invented successful outcome.

## Transaction, one pending operation per member

Use a per-member record separate from legacy installed-file expectations.
Serialize the prior-selection check and the selection save under the same lock;
also use the vault's persistent-generation compare-and-swap across processes.
Different operation IDs sharing the same prior ID must not both proceed.

1. Validate authority, candidate and expected prior. Persist a pending reservation
   bound to the whole request. Do not change the selected certification.
2. Append an authorization intent bound to that reservation. It records what was
   authorized, not a claim that selection already happened.
3. Establish its durability before the selection save. Reuse the existing vault
   pre-save barrier, but prove with an adapter test that it covers this exact row.
4. Revalidate candidate, authority and prior under the selection lock. Persist the
   new selected record bound to the authorization evidence. A failed setter must
   not expose a new in-memory selection just because it mutated memory before I/O.
5. Observe the persisted outcome and witness it separately. Only then close the
   pending operation. An incomplete outcome record remains visible and blocks a
   competing operation until explicit reconciliation.

The last selected certification is distinct from transaction closure: if the
selection persisted but the effect receipt did not, report that distinction.
Certification still does not install or execute anything. Future projection
readers need their own authority, byte-validation and recovery review; this model
does not declare any state safe to project into a live harness.

Identical completed retries return the historical result. They must not restore
an older selection after a later certification. Reusing an operation ID with a
different candidate, member, actor, reason or prior ID refuses. An identical pending
retry discovers pending state; it is not an implicit authorization to resume it.
Explicit resume/reconciliation must recheck current authority.

Abandonment is a witnessed outcome, not deletion of the reservation. A selected
operation cannot be labelled abandoned to conceal its effect. Changing a selected
certification back requires a new authorized operation naming its actual prior.

## Crash/recovery matrix

| Stop or failure | Persistent evidence to inspect | Required behavior |
| --- | --- | --- |
| Before/after pending save | Vault generation and reservation | No new selection; distinguish absent from pending |
| After append, before durability | Surviving chain row and reservation | Never infer durable authorization from the old process's memory |
| After durable authorization, before selection | Signed row plus old vault selection | Leave prior selected; no startup promotion |
| Barrier failure | Durable frontier and vault generation | Refuse selection; invalidate uncertain in-memory state |
| Selection save before rename | Reloaded vault still names prior | Do not expose the tentative in-memory selection |
| Selection save after rename, response lost | Reloaded selection and exact signed row | Validate persisted selection; keep outcome incomplete until reconciled |
| Effect append/save interrupted | Selection, durable effect receipt, pending/closed record | Report/reconcile actual state; do not reselect blindly |
| Abandon after durable intent | Durable abandonment plus unchanged prior selection | Close explicitly; do not erase authorization history |
| Missing/invalid authorization on restart | Selected reference and unavailable/invalid evidence | Reader refuses; no fallback to “latest” or to an older selection |
| Concurrent or stale request | Member reservation, expected prior, vault generation | Reject without mutation; no two pending operations per member |

For ambiguous persistence, do not guess whether an error happened before or after
rename. Disable the uncertain in-memory reader and reload persistent state.
The generation and chain references determine reconciliation, not a success flag.
Evidence inspection may be read-only on restart; executing resume/abandon is an
explicitly authorized operation, never a consequence of finding a pending record.

## Executable model and its limits

Run `python3 -B tools/hooks_gt_commit_contract_test.py`.
The test file models one member, independent chain/vault persistence, volatile
appends, a durable frontier, compare-and-swap, and save errors on both sides of a
simulated rename. The tests assert outcomes across the cuts above, including lost
responses and replay after a later certification. Everything is in memory; it
does not open a vault, run a hook, access a daemon or require a signing key.

This is an executable specification, not proof of production behavior. Signature
validity and operator authority are fixture inputs; list positions stand in for
full chain references; string IDs stand in for reviewed digests. It does not test
cryptography, real write ordering, OS failure semantics, interprocess locking,
candidate parsing, multiple-member isolation or filesystem races. There is no
production import or adapter. A passing model does not close any of those gaps.

The first real implementation must reproduce this matrix against the actual vault
and chain, with failure injection around pre-save barrier, serialization, rename,
directory sync, memory publication and response. Also test real principal and
witness mismatch, unsigned authorization, missing/corrupt blobs, cancellation,
concurrent processes, cross-member isolation, and preservation of non-certification
vault fields. Hold activation until those tests and independent review pass.

## Delivery boundary

Next: settle the signing activation boundary, implement and review per-member
pending/selected records plus a side-effect adapter, then introduce an authorized
endpoint. Keep startup/restore projection in slice 4. Neither a contract model nor
operator authorization to certify constitutes permission to deploy hooks.
