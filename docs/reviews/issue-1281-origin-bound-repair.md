# Origin bound repository scope repair

Revision for [Hestia 1281](https://github.com/dp-web4/hestia/issues/1281), answering
Claude's independent HOLD on `34cbe07e`. **Held, not applied or deployed.** This
revision retains the requested `owner/repo` and requires it to match the granted
checkout's configured GitHub `origin`, including under explicit repository-name grants.

## Authority binding

`hestia_single_gate._mcp_repo` now preserves qualified identity, combines an explicit
`owner` with a bare `repo`, and refuses malformed or conflicting repository fields.
It no longer chooses a basename or silently prefers one conflicting argument.

`hestia_gate_core.repo_in_scope` requires a direct-child local checkout, without
symlink aliases, and either a repository grant or explicit recursive path containment.
Exact directory/file grants and grants on only a deeper subtree remain insufficient.
All scoped calls must additionally match the checkout's origin. Basename-only connector
events now fail closed, including under explicit repository-name grants. The existing
deliberate unscoped policy remains unscoped; ordinary scoped grants cannot acquire it.

Origin inspection uses Git without contacting a remote. It excludes global/system
configuration, includes and inherited `GIT_*` overrides. Common and linked-worktree
configuration both participate; missing or multiple origin URLs deny. A one-second
subprocess timeout and command/decoding errors also deny. Supported origins are explicit
GitHub HTTPS, SCP-style SSH, and `ssh://git@github.com` URLs, optionally using SSH port 22.
Other hosts, host aliases, credentials in HTTPS URLs, query strings and local URLs deny.
Origin comparison is case-insensitive; checkout lookup retains the requested repository
spelling and does not enumerate workspace contents to infer aliases.

This is A1 configuration evidence, not proof of remote ownership. A local user able to
edit Git metadata can rebind it. The repair closes the accidental foreign-owner match;
it does not claim adversarial same-principal containment. It covers the existing named
repository argument surface, not repository IDs or every URL-only connector method.

## Held bytes and integration order

Current patch:
`held/c02198170e13611cbe91706d1fcdab60b0156de1c699f1cd3440856f74774480.patch`.
It has normal three-line context and changes only these source files:

- `plugins/_shared/hestia_gate_core.py`
- `plugins/_shared/hestia_single_gate.py`

`git apply --check` succeeds against main `68447776`. The candidate builder emits
the unified diff as data; the probe verifies that those exact bytes match the
digest-named held artifact before compiling both proposed modules in memory.
No production source, ground-truth or installed file is changed by the probe.
The old basename-only patch remains in `held/lineage/` for historical reproduction.

The reviewed #1232 head is `8fe48fea`, whose held `d10129c2` patch changes both the
core and orchestrator too. No combined-tree clearance is claimed. Agree landing order
with its author; whichever lands second must rebase, rebuild the held bytes and rerun
the combined tests. After approval, publish/install the core and orchestrator together
through the normal governed process and attest both deployed digests.

## Evidence

```sh
python3 docs/reviews/recursive_repo_origin_probe.py
python3 docs/reviews/recursive_repo_origin_probe.py --held
python3 docs/reviews/recursive_repo_origin_probe.py --held --core-suite
python3 docs/reviews/recursive_repo_origin_probe.py --held --contract-suite
```

Baseline: **22/54**. Held candidate: **54/54**. These execute the production connector
normalization and core evaluator with synthetic granted policy and real disposable
Git checkouts, including a real linked worktree. Negative cases cover foreign owners
under recursive and explicit grants, missing/ambiguous origins, worktree overrides,
conflicting arguments, Git environment overrides, included configuration, symlinks,
malformed names, exact/deep/file grants, egress and expired snapshots.

The existing offline core suite passes against the candidate. Its live tool-inventory
check is skipped explicitly. Only its fixture cache is redirected to the writable
checkout; HOME and policy are not widened. All **19 common decide() contract tests**
also pass against the candidate modules; the real-daemon arm is explicitly skipped.
Full native-harness parity and live
connector validation remain rollout checks, not claims of this offline evidence.

## Required disposition

Independent re-review must confirm the owner/origin binding and conservative refusal
semantics. Governed application still needs approval; the user's authorization to
report via `gh` is not permission to change the gate outside that process. Close the
issue only after authorized deployment and a normally gated connector operation prove
the original failure is repaired.

```text
surface: origin-bound connector scope   act: authorize repository-named connector calls
S: high/reversible [construct: repo_in_scope is revertible; downstream effects may not be]
R: pass [construct: explicit grant plus checkout origin binding, not reachability alone]
W: escalate [construct: resolve_agent_policy authority plus A1 Git configuration evidence]
O: pass [construct: evaluate egress then repo_in_scope before connector dispatch]
A: n/a [construct: held candidate only; existing runtime decision witnessing unchanged]
V: present [construct: independent review and governed approval before application]
verdict: ESCALATE(human gate)
```
