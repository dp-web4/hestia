# held/: hestia#647, an explicit external launch dir is in scope. NOT applied

| file | sha256 |
|---|---|
| `7fc56c4d8ae8403ae563baafbbbe4c6411464ecdc1f244ffd1ad4e1a9e1a9fed.patch` | `7fc56c4d8ae8403ae563baafbbbe4c6411464ecdc1f244ffd1ad4e1a9e1a9fed` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

`launch_cwd_repo()` derives a dynamic grant only when the launch directory string contains the workspace root.
Per-fire worktrees and hub thread directories live elsewhere, so a session launched there is denied its own working
directory even when the launcher supplied that directory through the profile's declared launch variable.

## The change

Explicit launch configuration is now evaluated before the legacy workspace-substring fallback:

- an absolute directory named by `profile.launch_cwd_env` receives `path:<resolved-launch-dir>/**`, so the launch
  directory and its descendants are reachable;
- a directory inside the workspace keeps the existing repo-segment grant;
- a relative value, the workspace itself, or an ancestor of the workspace grants nothing;
- without the declared launch variable, an external cwd grants nothing and the legacy behavior is unchanged.

This deliberately does **not** grant a member-chosen event cwd, a parent directory, or an arbitrary absolute path
that the launcher did not declare. It also does not claim to finish the larger migration to a certified launch
grant in the policy snapshot: that authority/evidence replacement remains future work.

## Verification

On base `59f2478e`, with the generated core loaded from a faithful scratch `plugins/_shared` layout:

- `test_gate_core.py`: **ALL CHECKS PASS**, including external launch allowed, external sibling denied, ancestor
  refused, relative paths refused (including one containing the workspace string), the existing in-workspace grant,
  and no-declaration denied. Shim presence and scope-rule inventory checks run against the intended plugin set.
- The same revised suite against the unpatched core fails **exactly the two positive external-launch checks**.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the core overlay.
- `tools/hooks_gt.py check`: clean on the base. The builder strictly reproduces all eight patch files, including
  the hooks-gt copy and five manifests. `git apply --check` passes.
- No live daemon or launcher was changed. All scope decisions use local fixtures; no real per-fire worktree is
  touched. Ruff is unavailable in this environment (`No module named ruff`).

## Apply

```
python3 held/build-647-launch-grant/build.py <worktree at main> <out dir>
PYTHONPATH=plugins/_shared python3 <out dir>/runtime/plugins/_shared/test_gate_core.py
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: launch_cwd_repo   act: authorize acts inside an explicitly declared external launch directory
S: high/irreversible [construct: a new external path grant can authorize consequential writes]
R: pass [construct: profile.launch_cwd_env is the declared launch channel, not a workspace-substring probe]
W: escalate [construct: this is the existing launch-env bridge, not a witnessed policy-snapshot grant]
O: pass [construct: the launch grant is computed in evaluate before the tool act]
A: escalate [construct: decisions are witnessed, but the launch grant derivation is not independently attested]
V: present [construct: existing scope refusal and deliberate escalation route remain]
verdict: ESCALATE(human gate) — narrow draft; do not read it as completing the certified-launch-grant migration
```
