# held/: hestia#670, workspace resolution is explicit and absolute paths are normalized. NOT applied

| file | sha256 |
|---|---|
| `2c08e37ff4bec2734274d8332267e4d2383fa8639f2344397915b4a29f7d2f12.patch` | `2c08e37ff4bec2734274d8332267e4d2383fa8639f2344397915b4a29f7d2f12` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

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
- The original lexical workspace-split pass remains as a floor, including on `_Unmodelled` or when normalized
  parsing finds no candidate. `_outside_candidates` then adds normalized absolute spellings at the workspace
  separator. The rewrite only adds coverage; it cannot remove a prior refusal or let an unenumerated one-time
  approval widen to literal ungranted repositories.

**Behavior change:** once the common gate evaluates a bounded session with no valid workspace configuration, it denies
**every bounded tool call**, including no-path tools, instead of evaluating against whatever directory the hook happened
to inherit. The daemon-unreachable degraded read-only path is unchanged. That is the intended fail-closed posture, not
an assertion that existing configured sessions must change. Deployment requires a pre-flight of hook environments and
markers so configured sessions do not stop unexpectedly.

## Verification

On base `59f2478e`, with the generated core loaded from a faithful scratch `plugins/_shared` layout:

- `test_gate_core.py`: **ALL CHECKS PASS**, including no-env/no-marker denial, valid env override, marker
  resolution, stale-env fallback, absolute-path refusal at root and other cwds, and prefix-sibling denial. New
  discriminating controls cover sed writes, `PYTHONPATH`, data operands, and unenumerated-lift widening.
- `public_boundary_test.py`: **PASS**. `hestia_gate_mechanism_test.py`: **PASS, 35 tests**, including marker-based
  discovery and explicit unmarked-workspace resolution. The previously red grep/toolchain suite also passes.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the core overlay.
  `gate_evaluate_test.py`: **PASS, zero failures**.
- The builder strictly reproduces all 12 patch files, including two hooks-gt source mirrors and five manifests.
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
