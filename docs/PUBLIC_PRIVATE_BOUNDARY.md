# Public source and installation-local context

Hestia is a public product repository. Its source, examples, tests, policy vocabulary and
installers must be usable without knowledge of any maintainer's machines, repository names,
relationships or current grants.

## What belongs here

- generic product code, schemas, protocol documents and design decisions;
- reproducible tests with synthetic identities and paths;
- install templates whose machine-specific values are rendered at install time;
- public issues and durable conclusions that external users can verify.

## What does not

- witness stores, signing material, actor state or generated bundles;
- operator/fleet discussion, session transcripts and deployment reports;
- worktrees, local symlinks and machine-specific service configuration;
- one-off probes tied to a seat, host, private corpus or incident;
- identity relationships, local repository grants or private inventory-derived scope;
- absolute paths captured from a real installation.

Those artifacts belong in runtime state or an operator-controlled private context. Moving an
artifact there is preservation, not authority: secrets and signing keys still belong in Hestia's
vault or an equivalent runtime secret store, never in Git of either visibility.

## Authority boundary

Public identity seeds contain no relationships and no scope. Continuity hooks may update bounded
session history, but must not infer or write authorization. Grants and society-floor state come
from the daemon's vault-backed, witnessed policy projection. A missing policy surface fails narrow;
repository contents never become an alternate authority merely because they are readable.

Installers accept explicit paths or render them from verified installation state. Runtime code does
not search for a maintainer's private repositories, enumerate familiar workspace layouts, or treat
a public example as a live configuration.

Diagnostics and support exports redact resolved absolute paths by default. Revealing a resolved
path requires an explicit local operator action; adding an exporter does not silently weaken this
boundary.

## Enforcement

`python3 tools/public_boundary.py` checks the tracked working tree. Before committing,
`python3 tools/public_boundary.py --cached` checks the exact staged snapshot; it is deliberately a
composable command rather than a hook installer, because replacing an operator's existing Git hook
chain can remove controls. CI runs the sabotage-tested companion, `tools/public_boundary_test.py`,
and fails if installation-local roots, seat-prefixed probes, credential-shaped values, real host
paths, non-generic identity seeds, or scope-writing continuity hooks return.

The check covers the current tree. Release review separately scans reachable Git history for actual
credentials because ordinary deletion does not erase old blobs. A history rewrite is warranted only
when the audit finds an exploitable secret or capability, not merely local context that has been
cleaned up and retained privately.

Cleaning the default branch also does not clean other public refs. Before release, maintainers
inventory branch ownership, preserve unique work, and delete only inactive refs whose local context
has already been retained. Preservation precedes branch deletion; branch deletion precedes any
separate decision about rewriting history.
