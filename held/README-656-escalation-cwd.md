# held/: hestia#656, escalation detail carries write-time cwd evidence. NOT applied

| file | sha256 |
|---|---|
| `57d63986ba6784d2584ace369d91760c033c3d4c018e8119954100249f4d0b55.patch` | `57d63986ba6784d2584ace369d91760c033c3d4c018e8119954100249f4d0b55` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

The gate resolves a path-relative act using its event cwd and any literal `cd`, but the escalation record omitted
that location. A reviewer could not tell which worktree the act would change without guessing from shell style.

## The change

- `_bash_write_targets` can additionally record the effective cwd at each write append, so a trailing `cd`
  cannot move an earlier write's evidence to the command's final directory.
- The public `effective_cwd` helper returns per-write `(target, cwd)` pairs for a conservative supported subset,
  `fallback` for non-shell or absent command input, and `unknown` for subshells, pipelines, `||`, `pushd`, `cd -`,
  variable-based `cd`, out-of-grammar input, or a literal `cd` into a nonexistent directory. It never widens authority.
- `claim_self_write` accepts an optional `event_cwd` and appends resolved per-write locations or an explicit
  `UNKNOWN`/fallback basis to the existing free-text escalation detail. The common gate supplies it, using the
  process cwd when the harness omits one. All six shell-tool spellings are covered.
- Approval keys, `act_digest`, resolved targets, bar pricing, and callers that omit the new argument are unchanged.
  No stored schema migration is needed.

## Verification

On base `59f2478e`, with all three generated engine modules supplied through documented overlay seams:

- `seat_gate_boundary_test.py`: **PASS, 17 tests x 4 seats**. Direct input carries a fallback basis; literal
  `cd` and `..` forms carry resolved write-time locations; a trailing `cd` cannot overwrite them; `pushd`
  reports `UNKNOWN`. A further 15 review-shaped probes cover subshells, pipelines, `||`, `cd -`, variable-based
  `cd`, missing directories, and out-of-grammar input.
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
