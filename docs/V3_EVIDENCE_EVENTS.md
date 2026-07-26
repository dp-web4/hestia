# V3 evidence events

Hestia records evidence from which later, versioned V3/T3 projections can be
derived. These events are append-only inputs, not scores.

## Closure claims (`hestia.closure-claims/v1`)

An actor may attach explicit claims to `hestia_record_outcome`:

```json
{
  "closure_claims": [
    {
      "claim_id": "focused-tests-pass",
      "statement": "The focused core test suite passes.",
      "scope": "hestia-core at commit abc123",
      "confidence": 0.98,
      "evidence": [
        "chain:0123456789abcdef",
        "commit:abc123"
      ],
      "known_limitations": [
        "The full workspace suite was not run."
      ]
    }
  ]
}
```

Properties:

- Claims are optional. Missing claims remain missing.
- Every submitted claim requires a stable identifier, non-empty statement and
  scope, calibrated confidence in `[0,1]`, and at least one evidence pointer.
- Claim identifiers are unique within an outcome.
- The daemon never constructs claims from `success`, `result`, or prose
  implications.
- Claims are witnessed inside the outcome event with their schema version.
- Closure claims do not directly mutate trust. Later adjudications compare
  explicit claims with observed outcomes to derive calibration evidence.

The core applies size and count bounds before consuming the in-flight action.
An invalid claim payload can therefore be corrected and resubmitted without
losing the action.

## Reversal cause taxonomy

`hestia_record_reversal` separates operational `kind` from semantic `cause`.

Operational kinds remain:

```text
override | rollback | incident
```

Required causes are:

```text
invalid-result
changed-requirements
new-evidence
corrected-adjudication
self-correction
obsolescence
```

Only `invalid-result` emits `validity_effect: "refuted"` and mutates the
legacy judgment-axis trust negatively. Every other cause is witnessed without
an automatic subject penalty.

`self-correction` does not automatically award Temperament. Promptness,
forthrightness, boundary conduct, and attribution require independently
witnessed conduct and a versioned derivation rule; the cause label alone
cannot prove them. The current derivation has no self-correction predicate, so
these events are neutral today rather than receiving a fabricated positive.

Legacy reversal events without a classified cause are retained but are not
silently treated as invalid-result events by the calibration exporter.

### Per-cause emission and lineage contract

The reversal says that an earlier operational decision changed. An
adjudication says what evidence establishes about one V3 axis. They are
separate events linked explicitly:

| Cause | Automatic adjudication | Required lineage | Projection effect |
|---|---|---|---|
| `invalid-result` | `validity: refuted`, method `reversal` | emitted adjudication `depends_on` the reversal | negative validity evidence; legacy judgment also moves |
| `changed-requirements` | none | follow-up verdicts SHOULD `depends_on` the reversal and new requirement evidence | neutral |
| `new-evidence` | none | a replacement verdict MUST `supersedes` the prior same-axis adjudication and SHOULD `depends_on` the reversal/evidence | neutral until separately adjudicated |
| `corrected-adjudication` | none | reversal `ref` MUST identify the prior same-grain adjudication; it tombstones that verdict. A replacement MUST `supersedes` the prior verdict and SHOULD `depends_on` the reversal | removes the corrected verdict at read time; replacement folds normally |
| `self-correction` | none | future positive conduct evidence MUST link to the reversal | neutral today; no automatic Temperament |
| `obsolescence` | none | follow-up verdicts SHOULD `depends_on` the reversal and obsolescence evidence | neutral |

`supersedes` accepts a raw witness hash or `chain:<hash>` and is canonicalized
to the raw hash in the event. It is valid only for an earlier adjudication of
the same subject, role, and axis. The immutable original remains receipt
visible but is excluded from the active score. A
`corrected-adjudication` reversal provides the same read-time exclusion while
a replacement verdict is pending. Because that exclusion changes the
subject's active score, the subject cannot issue it about itself; it requires
an attributable, law-authorized witness.

## Accountability self-audit

```text
surface: hestia_record_outcome closure_claims
act: append actor-authored claim evidence to a witnessed action outcome
S: low/reversible [construct: closure claim is evidence, not a score or outward trust delta]
R: pass [construct: existing attributed in-flight action/session]
W: pass [construct: outcome action ownership + instance/role/session witness fields]
O: pass [construct: parse_closure_claims before actions.remove]
A: pass [construct: closure_claims embedded atomically in append_chain("outcome")]
V: n/a [construct: no irreversible/high-consequence act]
verdict: PASS

surface: hestia_record_reversal cause classification
act: append cross-actor reversal evidence; invalid-result may mutate legacy judgment trust
S: medium/reversible [construct: append-only evidence + recomputable trust projection]
R: pass [construct: resolve_caller live session]
W: pass [construct: attributable reporter + canonical subject role + reversal_report law gate]
O: pass [construct: cause/role/kind validation and gate_direct_tool before append/apply]
A: pass [construct: cause + subject + reporter + evidence pointer in append_chain("reversal")]
V: n/a [construct: reversible projection; challenge/supersession stage remains required before consequential publication]
verdict: PASS
```

---

## Post-review notes (CBP, 2026-07-24)

- **BREAKING for out-of-tree callers:** `hestia_record_reversal` now REQUIRES `cause`
  (one of the six taxonomy values); calls without it get a self-describing error envelope.
  In-tree callers are updated; update any runbooks/operator habits.
- Aggregate closure-claims payload is capped at 64 KB serialized per outcome
  (`MAX_CLOSURE_CLAIMS_TOTAL_BYTES`) — large evidence goes behind pointers, not inline.
- Return reconciliation (2026-07-25): `self-correction` is neutral until an
  independently witnessed conduct predicate exists; the current V3
  adjudication axes cannot manufacture Temperament. The per-cause
  emission/lineage contract above is now explicit, and the daemon validates
  and derives `supersedes`, `depends_on`, and corrected-adjudication
  tombstones accordingly.
