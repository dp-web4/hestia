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
forthrightness, boundary conduct, and attribution require adjudication; the
cause label alone cannot prove them.

Legacy reversal events without a classified cause are retained but are not
silently treated as invalid-result events by the calibration exporter.

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
