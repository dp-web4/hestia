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
- a bound registration artifact and its JSON hook-event map;
- the exact pinned shared-engine manifest and file digests;
- declared cross-unit file dependencies, with no overlapping destinations;
- each blob's canonical digest and published header, and its full byte digest.

The deterministic output is `hook-certification-candidate/v1`, explicitly
`uncertified`. It lists logical artifact paths, versions, byte counts and digests,
not hook contents or installation locations. Its candidate digest binds the whole
review payload. This is evidence for later authorization, not authorization itself.

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

Registration JSON parsing is structural evidence only. It does not render commands,
prove ownership of installed entries, prove that a registered command reaches the
gate, or account for a harness's cached configuration. Those are projection and
live-verification responsibilities, not properties of this candidate digest.

## Remaining slices

**3b — Authority-bearing per-member certification.** Add an operator-gated action
that names the reviewed candidate digest and expected prior certification. Reuse
the witnessed operator identity boundary; neither filesystem presence nor a
caller-supplied member string is authority. Revalidate the candidate, reject stale
review/concurrent replacement, and commit the member's version, file digests,
registration digest, actor, reason and evidence basis with the signed witness.
Crash consistency between vault and witness is a design/review prerequisite, not
something to hide behind two sequential successful writes. A failure must preserve
the previous certified selection or expose a recoverable incomplete transaction.
Certification alone must not activate projection or silently replace legacy gate
expectations. Old and new evidence must remain distinguishable.

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
