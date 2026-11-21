# held/: hestia#656, escalation detail carries the act's cwd. NOT applied

| file | sha256 |
|---|---|
| `0ebffc80e0463cf4f250f1da8fcb02b1255d38f79cace287d8e4433f89cfa2b4.patch` | `0ebffc80e0463cf4f250f1da8fcb02b1255d38f79cace287d8e4433f89cfa2b4` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

The gate resolves a path-relative act using its event cwd and any literal `cd`, but the escalation record omitted
that location. A reviewer could not tell which worktree the act would change without guessing from shell style.

## The change

- `_bash_write_targets` can optionally return the effective cwd it already computes during write-target analysis.
- The public `effective_cwd` helper uses that exact resolver, falling back to the harness cwd when the command is
  not inspectable. It never widens authority and never introduces a second location rule.
- `claim_self_write` accepts an optional `event_cwd` and appends `Event cwd: <resolved path>` to the existing
  free-text escalation detail. The common gate supplies it, using the process cwd when the harness omits one.
- Approval keys, `act_digest`, resolved targets, bar pricing, and callers that omit the new argument are unchanged.
  No stored schema migration is needed.

## Verification

On base `59f2478e`, with all three generated engine modules supplied through documented overlay seams:

- `seat_gate_boundary_test.py`: **PASS, 17 tests x 4 seats**. Every real shim carries event cwd; direct,
  `cd`-then-write, and `..` forms carry the correct effective location; target resolution stays intact.
  The unpatched control fails the new detail assertions.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells**.
- `hestia_governance_closure_test.py`: **PASS, 39 tests**.
- `claim_self_write_test.py`: **PASS, 45/45 checks**.
- `closure_output_writes_test.py`: **PASS, 4 tests / 103 write-read pairs**.
- The builder strictly reproduces all 12 patch files, including three hooks-gt source mirrors and five manifests.
  `git apply --check` passes. Ruff is unavailable (`No module named ruff`).
- No live daemon or real escalation was opened; all daemon traffic is loopback stub traffic.

## Apply

```
python3 held/build-656-escalation-cwd/build.py <worktree at main> <out dir>
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: governance escalation detail   act: attach location evidence to an existing refusal record
S: med/reversible [construct: evidence only; no permission, target, or approval-key change]
R: n/a [construct: no new caller authority or reachability check]
W: pass [construct: existing witnessed claim identity and session binding are unchanged]
O: pass [construct: target resolution still precedes the claim and its recorded detail]
A: pass [construct: event cwd rides beside the same act and its resolved targets]
V: present [construct: the existing deliberate escalation and refusal route is unchanged]
verdict: PASS
```
