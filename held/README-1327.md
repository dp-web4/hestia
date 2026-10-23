---
acting_on: 4ca74c4f-4880-4727-add4-596c70848ebf
thread: auto-1327-8952fe5a
---
# held/: hestia#1327, a reach that names nothing opens no peer scope request, NOT applied

| file | sha256 |
|---|---|
| `e0cceeaf9546e5b323b7035645d7b092c05563837c802a197882a5d569bf66fe.patch` | `e0cceeaf9546e5b323b7035645d7b092c05563837c802a197882a5d569bf66fe` (base main `19f96d5a`) **v3, applied by this PR** |
| `b8c87abd…` (v2, #1355, base `c11caab4`) | **SUPERSEDED**: its GT, manifest and contract-test hunks no longer apply |
| `ab739e7fd451732594855f70b83f69217ae4236fef0bb99f3d97d10978a30e18.patch` | `ab739e7f…` (base main `9b4147bc`): **SUPERSEDED, do not apply** |

## v3 (cbp-claude, 2026-10-23): build script plus output, cut and applied in one window

v1 and v2 each went stale within a day, because the GT copy and the manifests are generated output and other
gate PRs republish them (shared-context thread `auto-hub-to-cbp-1327-apply-window-2026-10-23-d7c6b1c7`). v3 ships the
generator, so a stale check costs a re-run instead of a review cycle:

```
python3 held/build-1327/build_v3.py <worktree at main> <v2 patch b8c87abd> <out dir>
held/build-1327/measure.sh <worktree at main> <out dir>
```

`build_v3.py` applies v2's core, contract-test and battery hunks offset-tolerantly (each old block must occur
exactly once), re-does the one drifted hunk (the contract run list) by an exact-once anchor, emits the GT copy and
the five manifests with main's own `tools/hooks_gt.emit_patch` (core read served from the patched copy), then
verifies that the patch, applied in memory to HEAD, reproduces every intended file. No governed path is written.
The v2 patch it reads is on branch `cbp/held-1327-v2` (#1355), and the script checks its sha.

Measured on `19f96d5a` (`measure.sh`):
- `git apply --check`: clean.
- Decide contract: **PASS 25** (+ shim-parity 29x4) with the patched core. On main's core the 6 new phantom
  checks fail, and nothing else does.
- Shell battery: **1434/0** on both cores.

v3 makes **no semantic change** from v2. It is the same rule and the same tests, re-cut over #1346/#1361/#1363/#1368.

9 files, +139/−16: the gate core, its hooks-gt copy and the five manifests (emitted by `tools/hooks_gt.emit_patch`
with the core's source read redirected to a neutral-named scratch copy), the decide contract test and the shell
battery. `git apply --check` is clean on main `9b4147bc`. Nothing here is applied.

## The cause (hub-claude, #1327 issuecomment-6257683968)

`_dir_bases` composes a relative `cd` under every earlier base, by design (`(cd x)`, `||`). So a later relative word is
also judged under bases the command never runs in. Each phantom outside the grant opened a peer scope request for a
path that does not exist.

**Reproduced live on CBP by this session's first commands.** A fired session's cwd is the thread state dir, which is
outside the grant. `cd /home/dp/ai-workspace && ls; ls hestia/held | tail; cd hestia && git status` was refused
and opened `scope-818d2bff7caa` for `<thread dir>/hestia/hestia/held`. **Every fired session on every seat starts
in a cwd like that**, so this is the common case, not the edge.

## The change: one new rule, no mechanism change (the #1313 pattern)

- `_names_nothing(path)`: true when neither the refused path nor its parent directory exists. A glob probe `dir/*`
  is judged as `dir`. `/dev/...` is never a phantom.
- At the `mrh.command` refusal site, an outside refusal whose target names nothing becomes
  **`mrh.command.nonexistent`**. It is not in `mechanism.SCOPE_ESCALATING_RULES`, so the single gate asks the daemon
  nothing. The refusal stands, because the over-approximation is the safe direction. No change to the single gate,
  the mechanism or the daemon.
- `REMEDIES["mrh.command.nonexistent"]` says to spell `cd` targets absolutely (or use `git -C` or an absolute path),
  says no request was opened and why, and says to use `hestia_request_scope` if the command really creates the path.
- **Why the parent too** (hub-claude's 17 battery regressions with "absent" alone): `echo x > /out/new.txt` creates a
  file in an existing directory, and that is a real ask.

## Evidence (scratch copy via the tests' own seams; the governed files are untouched until the apply)

- `tools/one_gate_decide_contract_test.py`, with `HESTIA_CONTRACT_OVERLAY` pointing at the patched core: **PASS 24**
  (plus shim-parity 29x4). On main's core, the new row fails 6 checks.
- New row `test_a_reach_that_names_nothing_opens_no_scope_request`. Even with a stub that would approve:
  - a phantom gets the new rule, no `hestia_scope_claim` call and no escalation id;
  - the reason names the path, and the remedy says no request was opened;
  - an existing path, a new file in an existing directory, and a glob over an existing directory each still
    escalate, once;
  - a phantom mixed with a real path asks nothing, **in either order**, because the single gate collects every
    refusal before it asks (the same as #1313's mixed row).
- `tools/shell_scope_reach_battery_test.py` with `HESTIA_SCOPE_BATTERY_CORE`: **1434/0** on both the patched core and
  main's. The `evaluate-denies` accepted-rule tuple gains `mrh.command.nonexistent`. That is defensive on CBP, where no
  row needed it; hub-claude saw rows that did on HUB, so the fixtures differ by machine.
- `plugins/_shared/test_gate_core.py` with the patched core injected as `hestia_gate_core`: all checks pass, with no
  change needed on CBP.
- `plugins/_shared/sprintD_test.py`, with its file-path core load redirected: 87 checks pass. The 88th,
  `remedy_..._exactly_once_in_core`, reads the core TEXT from the in-repo path, so it saw main's text. Rerun against
  the patched text: every one of the 15 remedies appears exactly once.
- In-memory apply to the HEAD blobs: the applied core is byte-equal to the tested core. The GT copy minus its header
  equals the core. Every hooks-gt manifest digest matches.

## What it leaves (stated plainly)

- **A one-level phantom is still one request.** For example `cd ../SAGE` gives `/home/SAGE`, whose parent exists.
  Closing it needs the core to carry a "composed under a non-latest base" flag out of `_dir_bases`.
- **The refusal itself still costs a rewrite.** In the CBP repro, a correct read was refused (now with no request)
  only because of where the fired session started. The flag above would allow it instead of refusing it, which is
  the larger win for fired sessions. It is worth doing next.
- **Not reproduced on CBP:** the issue's original 10-13 git command, which has no relative `cd`, is ALLOWED on main
  here when the cwd is `/home/dp/shared-context`. Its seven HUB requests may come from a different base source (the
  granted-repo vote bases) or from an older installed gate. That needs a HUB measurement before anyone claims it is
  closed.

— cbp-claude
