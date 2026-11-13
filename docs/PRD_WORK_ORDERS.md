# Work orders: declared file-set approvals

Status: PROPOSED for review, not implemented and not a closure claim for #602.

## 1. The defect is the unit of authority

Single-act act binding is necessary: an approval must not move from an `Edit` to a `Write`, a
new destination, different bytes, another tool, or another session. But it makes every hunk a
new act even when the operator has already decided that the whole fix is wanted.

The measured costs are the two halves of #602:

- second and later hunks carry different act digests, so a member must ask again after an
  approval the operator already made;
- repeat resplices carry the same digest, so the member asks again even when nothing about the
  act changed.

A marker-only grant would close those cases by opening an unsafe bypass. The remedy is not to
widen an act; it is to let the operator approve a **closed work order** while retaining exact
per-hunk identity and a complete spend ledger.

Scope reservations (`scope_claim_spend_all`) already establish the useful protocol discipline:
reserve before the act, commit only after final evidence commits, release when the act is
refused, and make an uncertain outcome visible. They are the model to reuse, not a new source of
approval semantics. Path-scope grants and governance-file work orders remain different objects.

## 2. Requirements and non-goals

A work order MUST:

- be opened and decided once for a closed set of paths and operations;
- permit repeated writes, including different bytes and repeated identical resplices, within
  the approved set and a declared claim budget;
- bind every hunk to its canonical request, tool, operation, session, and measured payload;
- record every claim and its outcome, so "approved N files, M writes landed" is inspectable;
- refuse an undeclared path, operation, tool, payload, or session, with no fallback to a
  marker-only approval;
- fail closed on order expiry, claim-budget exhaustion, and an uncertain prior outcome;
- leave single-act escalation semantics unchanged.

It MUST NOT:

- authorize a path outside the set, a different operation, or an unrelated act such as a
  service restart;
- turn a bounded/redacted display summary into an authorization key;
- treat a claim receipt as proof that the write landed;
- silently repair an unknown prior execution by allowing another execution;
- create a second, differently named family of scope approvals. Work-order events are explicit
  `gate_work_order_*` records and never masquerade as `scope_once_*` events.

## 3. The order object

```text
WorkOrder {
  id: String,
  subject_plugin_id: String,
  host_session_id: String,
  entries: [{ path: absolute-path, op: create | edit | delete | chmod }],
  max_claims: u32,
  claims_used: u32,
  status: pending | approved | withdrawn | expired | exhausted,
  opened_at: u64,
  expires_at: u64,
  order_digest: sha256(canonical_order_preimage),
}
```

The set is closed at open time. Paths are normalized absolute paths; duplicates collapse before
canonicalization. Entries sort by `(path, op)`. `max_claims` is required, shown to the decider,
and counts **per order, not per path**. The decider sees the file set, every operation, the
claim budget, the session, and the expiry before approving.

`order_digest` is SHA-256 over canonical JSON containing version 2, subject, sorted entries,
claim budget, and host session. It does not include a display reason or invocation id, so an
identical retry finds the same order. A changed set, budget, subject, or session is a different
order.

A legitimate order might contain one hook file `(edit)` and its new test `(create, chmod)`, with
`max_claims = 12`. The first file may be edited repeatedly and the test may be created, changed,
and chmodded, but the thirteenth committed claim fails closed.

## 4. Per-hunk identity is not weakened

Each gated write presents its canonical request from the common gate (the N6/#600 shape):
`{v, tool, input, cwd, session}`. The daemon validates the tool and live host session and
computes the hunk digest itself. Display summaries are for humans only.

For each hunk the daemon independently verifies:

- `realpath(input.path)` equals one declared `entries.path`;
- the requested `op` matches that entry;
- `tool` is appropriate for the operation;
- the canonical session equals the order's live host session;
- `canonical_act_digest` is the digest of the presented canonical request, not a caller-chosen
  digest or a truncated/redacted summary.

For `create` and `edit`, the daemon measures `payload_sha256` over the exact new bytes and
requires the same bytes at reserve and commit. For `chmod`, it records the requested mode and a
digest of the mode transition. For `delete`, payload is explicitly null; path, op, and canonical
request remain bound. A change in any of these is a different hunk, not permission to open a
parallel order automatically.

## 5. Reserve, commit, release

A claim uses an `op_key` derived from the order, invocation, path, and canonical hunk. The
protocol mirrors scope reservations rather than inventing a new lifecycle:

1. **Reserve.** Before execution, validate the order and hunk and append
   `gate_work_order_reserved` with order id, `op_key`, hunk digest, and reservation expiry.
   Retrying the same `op_key` returns the existing reservation and never increments
   `claims_used`.
2. **Commit.** Only after the final decision evidence commits, append
   `gate_work_order_claimed` with order id, `op_key`, hunk digest, measured payload/mode,
   `action_id`, and the new `claims_used`. This is the claim's spend record.
3. **Release.** If the act is denied or its evidence cannot commit, append
   `gate_work_order_released` and leave `claims_used` unchanged. The order remains usable.
4. **Outcome.** The post-tool outcome joins `action_id`, so the ledger distinguishes a claim
   from a landed write. A claim with no outcome past the settle window is
   `started_never_completed`, not success.
5. **Lapse.** An uncommitted reservation that expires is `unknown`, never clean. It consumes
   the claim budget conservatively so a timed-out write cannot silently execute twice. The
   operator sees the unknown row and must reconcile it rather than the daemon guessing.

The order stays approved until its time expiry, withdrawal, or claim-budget exhaustion.
**There is no per-path exhaustion.** Repeating an identical resplice with a new invocation is
valid while `claims_used < max_claims`; repeating the same invocation is idempotent and does not
increment it.

## 6. Failure contract

| case | required result |
|---|---|
| undeclared path or op | refuse; open a separate escalation if requested |
| different tool or session | refuse before reservation and before any spend |
| payload/mode changed after reserve | refuse commit; keep the original claim unspent and the mismatch visible |
| order expired | refuse; no claim and no "already approved" rendering |
| `claims_used == max_claims` | refuse as `exhausted`; never slide into single-act semantics |
| duplicate `op_key` after commit | return the original receipt, not a second spend |
| duplicate `op_key` while reserved | return the existing reservation, not a second counter increment |
| previous outcome unknown | refuse new execution and require reconciliation |
| reserve/commit/release reply lost | lookup by `op_key`; never infer success or failure from silence |
| restart | restore order, reservations, claims, and outcomes with no duplicate spend |

An undeclared write does not consume or mutate the order. Every refusal leaves state
bit-identical except for its witnessed diagnostic.

## 7. Operator surface

At decision time the operator sees subject, session, complete `(path, op)` set, claim budget,
and expiry. Approval is bound to that exact view, including its digest; changing any part
invalidates the approval.

Afterward, the order view shows each reservation and its state, each claim's hunk digest and
measured payload/mode, each outcome `action_id`, and whether the write committed, was released,
is still in flight, or is unknown. `claims_used/max_claims` is per order. The ledger is not a
counter inferred from approved petitions: it is the actual chain of reservations, claims,
releases, and outcomes.

## 8. Acceptance matrix

1. Open and approve one order for two files. A second hunk of the first file claims with no new
   ruling; a create and chmod of the second file also claim.
2. Re-edit the first file with different bytes, then repeat the identical resplice in a new
   invocation. Both commit and are separately visible; no new ruling occurs within budget.
3. An undeclared path, wrong op, wrong tool, wrong session, or changed payload after reserve
   fails closed and leaves `claims_used` unchanged.
4. Repeat the same `op_key` after reserve and after commit. The first returns the reservation,
   the second returns the original receipt, and the counter does not move.
5. Let the order expire, and separately reach `max_claims`. Both refuse the next hunk without
   converting it to a single-act approval.
6. Deny the act after reservation. Release leaves the order and budget usable.
7. Lose the commit reply. Lookup returns the actual receipt; it neither replays the write nor
   doubles the counter. Losing the outcome produces `started_never_completed`, not success.
8. Restart between reserve and commit, then repeat the request. Reservation, counter, and
   outcome remain exactly once.
9. Compare single-act fixtures before and after this change. Their behavior is unchanged.
10. Inspect the operator view after several hunks: every claim has its payload/mode and outcome
    link, and the budget is the number committed, not the number of petitions.

## 9. Implementation shape

1. Add a durable work-order store beside `EscalationStore`, with explicit order status,
   reservations, claim counter, and replay. Do not overload `Escalation.consumed_at`: that field
   is single-use and has the wrong meaning for repeat work-order claims.
2. Add daemon open/reserve/commit/release/lookup handlers using the validation and canonical
   digest discipline above. Keep current single-act handlers and API behavior unchanged.
3. Make the common gate produce the canonical hunk and `op_key`, while adapters only render the
   resulting decision. Publish shared sources and ground-truth mirrors through
   `tools/hooks_gt.py`.
4. Add the decision and ledger views to the existing escalation UI, not a second approval queue.
5. Prove the matrix in store tests, real handler tests, executed-shim tests, and a real daemon
   restart. Deployment acceptance separately proves that the installed engine and daemon are the
   bytes just tested; source convergence alone is not deployment proof.

The migration introduces no flag day for single-act approvals. Existing rows keep their current
semantics. Work-order rows use a new event family so a reader never confuses a repeat work-order
claim with a single-act approval being spent twice.

## 10. Accountability self-audit

```text
surface: gate work orders   act: approve or execute a governance write under a declared set
S: high/irreversible [construct: order approval and per-hunk commit]
R: pass [construct: canonical request, live host session, and operator/peer decision; loopback is not authority]
W: escalate [construct: A1 session plus operator/peer approval; no new key-bound identity is claimed]
O: pass [construct: order and hunk validation before reservation; reserve before execution; evidence before commit]
A: pass [construct: order digest, hunk digest, measured payload/mode, counter, and action_id in the witnessed record]
V: present [construct: undeclared/mismatched/expired/exhausted/unknown fails closed; withdrawal and release remain available]
verdict: ESCALATE(human gate)
```

## 11. Non-claims for this draft

This document defines the contract and test plan; it implements none of them. It does not close
#602, establish deployment evidence, or claim that the existing scope reservation events already
provide work orders. The next PR after review should implement the store and reserve/commit /
release lifecycle with the acceptance matrix above, rather than a marker-wide permit that would
reopen the #600 class.
