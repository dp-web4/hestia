# Recursive workspace grants disagree with repository named MCP calls

Historical first candidate, superseded after independent HOLD. The current issue is
[Hestia 1281](https://github.com/dp-web4/hestia/issues/1281); use the
[origin-bound revision](issue-1281-origin-bound-repair.md) for current evidence and patch.
The original patch is retained under `held/lineage/`, not offered for application.

Originally reported by Codex at main
`68447776f288fa6263f0de7a6217be7599c39fb0`, following the operator's instruction to
repair the mismatch rather than require duplicate grants. Publication was initially
blocked; the operator subsequently authorized the normal gated shell reporting route.
Fleet report notice: 20627.

## Failure and impact

A recursive workspace grant covers a local checkout and its files, but a GitHub MCP
call naming that repository receives `mrh.repo`. This has blocked publication of
review evidence even though the operator already granted the containing workspace.
The current UI permits creating another recursive grant on the repository root, but
that is a workaround for inconsistent interpretation of the existing grant.

The mismatch has two concrete sites:

- `plugins/_shared/hestia_gate_mechanism.py::_scope_entry_for_grant` converts a
  recursive direct-child repository-root grant to a bare repository name. A recursive
  grant on the workspace itself remains a `path:<workspace>/**` entry.
- `plugins/_shared/hestia_gate_core.py::evaluate` accepts repository events only when
  the bare name is literally present in `scopes`. Unlike file checks, it does not
  consult recursive path containment.

## Held repair

The proposed `repo_in_scope` helper retains explicit repository grants and adds one
fallback for recursive path grants. The requested name must be a single repository
segment identifying an existing direct-child checkout in the configured workspace.
The checkout must have a `.git` directory or file marker, must not be a symlink alias,
and its root must be covered by an explicitly recursive path grant.

This does not enumerate the workspace, mint new grants, import the temporary-directory
or home exceptions, or convert an exact grant into recursive reach. Existing egress
restrictions continue to run before scope checks. Missing checkouts, ordinary
directories, file grants, subtree-only grants, malformed names and symlink aliases
remain denied. An expired policy still supplies no reach.

Historical patch: `held/lineage/9b236b54a92757e3ee3d36a3a08fe8f5f4a3aefa8bd58851852fdf54268b8fd8.patch`.
It changes only `plugins/_shared/hestia_gate_core.py`, and remains **unapplied**.
The patch is a zero-context unified diff; the offline probe verifies its digest and
every changed preimage line before compiling the candidate in memory. A dry-run
`git apply --check --unidiff-zero` succeeds against the stated base.

## Evidence

Run from this checkout:

```sh
python3 docs/reviews/recursive_repo_scope_probe.py
python3 docs/reviews/recursive_repo_scope_probe.py --held
python3 docs/reviews/recursive_repo_scope_probe.py --held --core-suite
```

The baseline passes 25 of 28 checks. Its three expected failures are recursive
workspace reach, recursive repository path reach, and a checkout with a worktree-style
`.git` file. The held candidate passes **28 of 28**, including all denial controls.
The existing offline core suite also passes against the in-memory candidate; its live
tool-inventory check is explicitly skipped. No live enforcement or end-to-end MCP
success is claimed. The core suite's fixture cache alone is relocated into a disposable
writable checkout directory; HOME and policy are not widened.

The probe is under `docs/reviews`, not the automatic CI test glob, because its baseline
mode intentionally fails before repair. The approved implementation should promote
these cases into the permanent core battery and exercise the full connector adapter.

## Review questions and limits

The existing connector `_mcp_repo` drops the owner from `owner/repo`. The repair keeps
that established basename model; a local `.git` marker is not proof that a remote
repository belongs to a particular owner. This limitation matters for authority and
must be explicitly accepted for this bounded repair or resolved with a qualified
repository identity before rollout. A local user can manufacture directories and
markers under the current A1 same-principal assurance model.

The conservative fallback refuses symlink aliases even when their targets are inside
the workspace, because local alias names are not remote repository identities. Review
whether any supported layout legitimately requires a different explicit binding.

Before application, independent review must confirm the scope semantics, attack the
negative cases, and check interaction with other pending gate changes. Application to
the governed source requires the usual approval process. Ground-truth publication,
installed-copy deployment, digest verification and an actual gated connector probe
remain separate steps. This branch does not alter those copies or any grants.

## Accountability review

```text
surface: repository scope interpretation   act: authorize repository-named connector calls
S: high/reversible [construct: repo_in_scope authorizes dispatch; downstream acts may be irreversible]
R: pass [construct: repo_in_scope requires existing explicit recursive authority, not mere presence]
W: escalate [construct: resolve_agent_policy supplies authority; remote owner identity remains basename-only]
O: pass [construct: evaluate checks egress then repo_in_scope before dispatch]
A: n/a [construct: this branch holds bytes and offline evidence; existing runtime witnessing unchanged]
V: present [construct: governed-source approval and independent review precede application]
verdict: ESCALATE(human gate)
```

Closure means the authorized, independently reviewed implementation is deployed and
the original repository operation succeeds through its normal gate. A passing offline
candidate alone does not close this issue.
