# held/: hestia#622, a committed deny carries its appeal hash. NOT applied

| file | sha256 |
|---|---|
| `2048c0e9f9dd5997ef6e46d5aae49846569d4d9ce37ce0fcf4470eb3f3d13aad.patch` | `2048c0e9f9dd5997ef6e46d5aae49846569d4d9ce37ce0fcf4470eb3f3d13aad` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

The common gate records its final verdict but discards the receipt's chain hash. Its remedies ask for that hash,
so a committed denial cannot be appealed from the reply the member actually receives. An uncommitted denial must
not acquire a fabricated hash or a remedy that promises one.

## The change

- `GateDecision.deny_hash` carries the exact `DecisionReceipt.entry_hash` for a committed deny, including the
  replacement denial when C11 rejects an uncommitted permit. Allows and warns never receive a deny hash.
- The common renderer emits `DENY <hash> — appeal with this chain hash.` only for a committed deny.
- An uncommitted deny is an integrity anomaly and renders `UNRECORDED — the deny stands.` followed by retry
  guidance. Only remedy sentences that require a chain hash or `deny_hash` are withheld; hash-free scope routes
  and legitimate warnings not to appeal remain visible.
- The deny still stands when recording fails; this patch does not create a synthetic appeal route. A later
  committed record can supply a real appeal hash after the member retries.

## Verification

On base `59f2478e`, with the generated gate supplied through the tests' documented overlay seam:

- `one_gate_decide_contract_test.py`: **PASS, 26 contract tests + 31x4 shim-parity cells**. New cases cover a
  direct committed deny, a direct uncommitted deny, both C11 replacement-deny receipt outcomes, and an allow.
  An unrecorded `mrh.path` rendering retains `hestia_request_scope`, `hestia_scope_status`, and its explicit
  negative appeal guidance while fabricating no hash. Without the overlay, the revised suite fails at the
  missing `GateDecision.deny_hash` attribute.
- `seat_gate_boundary_test.py`: **PASS, 17 tests x 4 seats**. Every real shim exposes a committed deny hash;
  daemon-down denials say unrecorded, contain no hash-dependent appeal remedy, and use the anomaly channel.
- The isolated real-daemon arm was not run (`HESTIA_DECIDE_CONTRACT_ENDPOINT` unset); no live daemon was touched.
- `git apply --check` passes. The builder strictly reproduces all nine patch files from HEAD, including the
  hooks-gt copy and five manifests.

## Apply

```
python3 held/build-622-recourse/build.py <worktree at main> <out dir>
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: common gate decision rendering   act: record and present an authorization denial
S: med/reversible [construct: no protected resource is actuated; the existing deny remains fail-closed]
R: n/a [construct: no new caller authority or reachability check]
W: pass [construct: existing record_decision authority and receipt validation are unchanged]
O: pass [construct: _finalize records the verdict before render exposes recourse]
A: pass [construct: deny_hash is the validated receipt entry_hash, never synthesized]
V: present [construct: committed deny hash enables appeal; unrecorded deny explicitly withholds it]
verdict: PASS
```
