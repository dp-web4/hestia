# held/: hestia#670, workspace resolution is explicit and absolute paths are normalized. NOT applied

| file | sha256 |
|---|---|
| `94dec1752a9c80bcdedfdc2a103c42a33a2f39111672daa6b1c650ce80996ac4.patch` | `94dec1752a9c80bcdedfdc2a103c42a33a2f39111672daa6b1c650ce80996ac4` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

With no environment override or `.hestia-workspace` marker, `detect_workspace()` returned cwd. Absolute scope
paths were then located by `cmd.split(workspace)`, so moving the process cwd could turn the denial domain into a
subdirectory or make it disappear.

## The change

- Unresolved detection returns `UNRESOLVED_WORKSPACE`. Bounded scope evaluation then refuses with `mrh.command`
  and an explicit configuration remedy: set `HESTIA_WORKSPACE`, or place `.hestia-workspace` in the actual root or
  an ancestor of the launch cwd. It no longer treats cwd as the denial domain.
- A valid environment override or marker preserves the existing resolution behavior. An explicitly unscoped `*`
  member keeps its current bypass of MRH scope (after the innate egress check).
- Absolute command candidates come from `_outside_candidates`, are normalized, and are compared at the workspace
  separator. The old command-text split is gone.

**Behavior change:** a bounded session with no valid workspace configuration now denies instead of evaluating
against whatever directory the hook happened to inherit. That is the intended fail-closed posture, not an
assertion that existing configured sessions must change.

## Verification

On base `59f2478e`, with the generated core loaded from a faithful scratch `plugins/_shared` layout:

- `test_gate_core.py`: **ALL CHECKS PASS**, including no-env/no-marker denial, valid env override, marker
  resolution from a child cwd, stale-env fallback, absolute-path refusal at root and other cwds, bare-token root
  control, and workspace-prefix sibling denial.
- The unpatched control fails at the missing `UNRESOLVED_WORKSPACE` constant.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the core overlay.
- `gate_evaluate_test.py`: **PASS, zero failures**.
- The builder strictly reproduces all eight patch files, including the hooks-gt copy and five manifests.
  `git apply --check` passes. Ruff is unavailable (`No module named ruff`).
- No live daemon, launcher, or real worktree was changed; scope decisions use local fixtures.

## Apply

```
python3 held/build-670-unresolved-workspace/build.py <worktree at main> <out dir>
PYTHONPATH=plugins/_shared python3 <out dir>/runtime/plugins/_shared/test_gate_core.py
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: workspace detection and absolute scope paths   act: admit or deny a scoped command
S: high/irreversible [construct: wrong domain selection can authorize an ungranted write or deny valid work]
R: pass [construct: unresolved configuration is a refusal, never reachability-as-authority]
W: pass [construct: existing vault/launch grant semantics are unchanged; no new grant is minted]
O: pass [construct: detection and normalized candidates are judged before the act]
A: pass [construct: unresolved denial names its configuration basis and reaches the decision record]
V: present [construct: configuration remedy plus existing deliberate scope escalation]
verdict: ESCALATE(human gate) — unconfigured bounded sessions now fail closed by design
```
