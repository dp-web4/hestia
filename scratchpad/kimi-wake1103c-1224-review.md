**Late independent verification — kimi-code, exact head `a197e8523c2aec17cfdf574f521488864526b4a1`. CONCUR; no new blocker.**

I ran the recut locally:
- `gate_parity_runner_test.py`: 26 checks passed.
- `one_gate_decide_contract_test.py`: 25 decide contracts plus 31×4 shim parity passed; the real-daemon arm was skipped.
- Targeted runner: on all four seats, both missing-patch acts deny with escalatable `governance-closure`, both present-patch controls allow, 4/4 rows agree, 0/8 expected mismatches and zero degraded cells.

The three-file delta against the integration base retains the explicit both-arms-deny assertion and absent-fixture controls. Exact-head GitHub checks are all green (10/10). The PR has since merged as `0ff331e02112c8364ce19ea6324b0133a0505d22`.

I did not rerun the full 34×4 matrix, so the eight already-reported expected-value mismatches in two pre-existing rows remain outside this verification; they are not presented as clean expected-value evidence. No governed gate source was changed or applied.
