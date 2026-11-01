# Hook certification: read-only preflight

2026-10-22. Slice 3a of [the ground-truth design](PRD_HOOK_GROUND_TRUTH.md),
following published artifacts (#1160) and the inert local store (#1161).

**This does not fix #1157 yet.** There is still no certified per-member vault
record and no startup projection from it. Detecting a swapped registration is not
repairing it. A successful candidate inspection does not certify or install hooks.

## What an operator would be certifying

`tools/hooks_gt_candidate.py` takes an explicit store root, unit, member identity
and full version digest. It resolves that exact stored closure, never `current`,
latest, live installed bytes or an ambient default directory. It checks:

- the manifest's content address and member identity;
- a bound registration artifact, its JSON hook-event map and every direct command
  target's membership in the closure;
- the exact pinned shared-engine manifest and file digests;
- declared cross-unit file digests, with no overlapping destinations or additions
  to the member's own or `_shared` namespace;
- each blob's canonical digest and published header, and its full byte digest.

The deterministic output is `hook-certification-candidate/v1`, explicitly
`uncertified`. It lists logical artifact paths, versions, byte counts and digests,
not hook contents or installation locations. Its candidate digest binds the whole
review payload. This is evidence for later authorization, not authorization itself.

`command_targets` lists the resolved script paths. Commands use the current
published direct-command grammar: optional known environment assignments, optional
`python3`, then one `@HESTIA_PLUGIN_ROOT@/unit/path` target (optionally quoted).
The accepted assignments are `HESTIA_HOME=@HESTIA_HOME@`,
`HESTIA_WORKSPACE=@HESTIA_WORKSPACE@`,
`HESTIA_ROLE="${HESTIA_ROLE:-@HESTIA_DEFAULT_ROLE@}"`, and
`CODEX_PLUGIN_ROOT=@HESTIA_PLUGIN_SOURCE@`. Other syntax, extra arguments, shell
operators, wrappers, unknown placeholders and absolute script paths refuse.
Unknown or missing targets appear in the refusal's `unresolved_targets` field
on stderr, with no candidate on stdout. Successful candidates carry an empty
`unresolved_targets`. The external `python3` interpreter, shell and substituted
environment values are not pinned artifacts.

`unverified_dependency_labels` lists **every** cross-unit dependency's declared
unit, path and digest. The bytes match the digest, but the current `requires`
schema has no dependency closure version: it cannot prove that those bytes were
ever published by that unit under that path, or even that the unit exists.
Consequently a dependency target in `command_targets` proves membership in the
declared file set only. Dependencies are file-level, not transitive; their own
imports and invoked programs are not automatically included. The member and
engine inventories likewise do not establish runtime import completeness.

For an already ingested store, run:

```sh
python3 tools/hooks_gt_candidate.py \
  --store /explicit/test-state/hooks-gt.store \
  --unit MEMBER_UNIT --member MEMBER_ID --version FULL_VERSION_SHA256
```

It writes JSON to stdout only. A refusal returns exit 2 and no partial candidate.
It does not ingest artifacts, contact a daemon, execute a hook, edit registrations,
write the vault, or modify the store. Store population remains the separate,
existing inert ingest operation.

## Bounded reads and evidence limits

Command entries accept only `command`, optional `type: command`, an optional
positive integer `timeout`, and optional string `statusMessage`. Unknown fields
(including `args`, `env` or `commands`) refuse the candidate even if its target is
otherwise known. These are the metadata shapes in the published templates, not
a claim to support every harness extension. Timeout units and runtime enforcement
remain harness-specific; the preflight does not interpret them. Noncanonical
target paths are reported in `unresolved_targets` like other unsupported commands.

Reads are descriptor-relative to the explicit store root and reject symlinks at
or below it, special files and path traversal. Files are opened nonblocking and
checked as regular files before reading. Limits are 1 MiB per closure JSON,
8 MiB per blob, 64 MiB aggregate and 256 resolved files. Size/metadata changes
during a read refuse the candidate. Duplicate JSON keys, duplicate manifest paths,
ambiguous dependency overlays and malformed schemas also refuse it.

This is a POSIX preflight, not hostile-same-UID containment. It does not authenticate
the store root's ancestors, guarantee a transactional snapshot across files, prove
the publication's origin, or prove the hook programs are safe. A same-UID actor can
manufacture a different internally consistent publication. The operator must
review the exact version and its independently established publication provenance.
The later certification path must revalidate the reviewed candidate at commit;
the projection path must revalidate against the certified record again on use.

Registration parsing and direct-target checks are structural evidence only. They do not render commands,
prove ownership of installed entries, prove that a registered command reaches the
gate, or account for a harness's cached configuration. Those are projection and
live-verification responsibilities, not properties of this candidate digest.

## Remaining slices

**3b — Authority-bearing per-member certification.** Add an operator-gated action
following the proposed [commit and recovery contract](HOOK_CERTIFICATION_COMMIT_CONTRACT.md)
(executable design model only; the runtime path is not implemented). The action
names the reviewed candidate digest and expected prior certification. Reuse
the witnessed operator identity boundary; neither filesystem presence nor a
caller-supplied member string is authority. Revalidate the candidate, reject stale
review/concurrent replacement, and commit the member's version, file digests,
registration digest, actor, reason and evidence basis with the signed witness.
Crash consistency between vault and witness is a design/review prerequisite, not
something to hide behind two sequential successful writes. A failure must preserve
the previous certified selection or expose a recoverable incomplete transaction.
Certification alone must not activate projection or silently replace legacy gate
expectations. Old and new evidence must remain distinguishable.
Before claiming dependency provenance, extend `requires` to bind a dependency's
closure version and validate its path/digest against that closure. Any certification
using the current schema must preserve the unverified-label and nontransitive
dependency limitations in the evidence shown to the operator.

**4 — Projection from certification, not from this tool.** Startup, restore and
repair must use the same path: resolve only the member's last certified closure,
revalidate its bytes, stage files, replace only provably Hestia-owned registration
entries, preserve other providers, witness the change, and verify the result.
Ambiguous ownership is a finding, not permission to delete or append another gate.
Preserve trust-sensitive command strings; surface any required operator re-trust.
Handle cached sessions and session-scoped bypass state explicitly. Tests must cover
restart after a swapped gate, registration-only bypass, duplicate entries,
corrupted local GT, missing certification, interrupted projection, mixed providers
and pinned-engine independence before claiming that restart restores the gate.

Neither slice should implement silent self-ratification: drift is not evidence
that the new bytes deserve certification. No live certification, hook change,
startup repair or third-party guard installation is part of this preflight PR.

## Checks

```sh
python3 -B tools/hooks_gt_candidate_test.py
python3 -B tools/hooks_gt_store_test.py
python3 -B tools/hooks_gt.py check
```

Fixtures are disposable. One test ingests the public repository artifacts into a
throwaway store and resolves each published member with a registration. No test
uses a live vault, installed hook directory, daemon or harness session.
