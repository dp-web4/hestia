# PRD: hook ground truth — the repo publishes, the vault certifies, the daemon projects

**Status:** DRAFT. This records dp's design (2026-09-28) against the measured gaps. Nothing here is
built yet.
**Closes, when built:**
- the deploy half of dp's vault requirement (findings/ratified-hooks-are-compared-not-deployed-2026-09-28.md);
- #1156 (a de-registered gate reads VERIFIED);
- #1157 (a restart re-projects nothing);
- the definition gap in #481.

## 0. Directive (dp, 2026-09-28, verbatim)

> the hestia repo needs to have a directory with tested and maintained hooks for supported
> harnesses. those are the ground truth. install should create a local directory. when hook is
> published to the repo its sha should be in the comment and metadata. on restart, daemon populates
> live hooks from ground-truth directory. sha updated in vault on certified releases. repair/restore
> copies from gt. if gt doesn't match published sha it's flagged as miswired.

Earlier the same day: *"the vault MUST contain location and sha of each ratified hook, against
which the live hooks are compared and from which they are deployed on restart and restore."*

## 1. Why: measured

The findings doc and the Discover bypass instrument (#1158, isolated daemon) measured this:

- **The vault holds path and sha, and compares against them. It deploys nothing.** There is
  nothing to deploy from: the vault holds digests, not bytes.
- **Nothing holds the registration.** Re-pointing a member's PreToolUse at a stub, with the
  ratified file left on disk, read `VERIFIED` on verify and on the live tick. Only the
  inventory's MISWIRED verdict saw it.
- **A restart re-projects nothing.** `hestia-deploy` installs only when main moves, and installs
  main, not the ratification.
- **The registration writer is additive.** For codex it added a second gate beside the stub.

## 2. The model

```
repo: hooks-gt/<harness>/            tested, maintained, PUBLISHED   (the ground truth)
        ├── manifest.json            files + registration + sha per file + release id
        ├── <hook files>             each carries its published sha in a header comment
        └── registration.json        what the harness must run, per event (the edge)
             │  install / certified release
             ▼
local: $HESTIA_HOME/hooks-gt/<release>/   content-addressed copy (like shared.builds)
             │  vault: certified release id + per-file sha + registration digest
             ▼
live:  the harness's hook dir + the harness's hook config
             ▲
             └─ the daemon POPULATES the live set from local GT on every start, and on restore/repair
```

Four authorities, each doing one job:
- **Repo GT** is what is published.
- **Local GT** is what this machine holds.
- **The vault** is what the operator certified.
- **Live** is what runs.

A mismatch at any edge is a named finding.

## 3. Requirements

- **G1. One GT directory in the repo, per supported harness.** Its contents are:
  - the hook entrypoints: gate, witness shim, observe/hydrate;
  - the **registration** (event → command template);
  - a `manifest.json`.
  
  The shared engine (`plugins/_shared` + `RUNTIME_MANIFEST.txt`) is part of the same published
  artifact, per #481's invariant: *every byte and configuration edge that decides admission
  belongs to one content-addressed artifact*. One mechanism, not a second one beside
  `shared.builds`.
- **G2. The published sha is in metadata, and in a header comment for humans.** A file cannot
  contain its own hash. The canonical digest is therefore sha256 over the file with its
  `hestia-gt-sha256:` header line normalised to a fixed placeholder. The manifest carries the
  same digest. The manifest is what is checked; the header is a readable copy, and a header that
  disagrees with the manifest is itself a finding. CI recomputes both and fails on drift, so a
  hook cannot be edited without re-publishing.
- **G3. Install creates the local GT directory.** Install copies a GT release into
  `$HESTIA_HOME/hooks-gt/<release>/`, verifies every digest there, and flips a `current` link
  atomically. This is `shared.builds`' existing discipline, extended. Install writes nothing live.
- **G4. On every daemon start, the daemon populates the live hooks from local GT:** files, then
  registration. It does this through one witnessed act per member (`hooks_projected`: member,
  release, per-file sha, registration digest) and verifies the result with the existing
  `gate_watch` pass. The projection replaces whatever is registered on the declared events. It is
  not additive, which is the opposite of today's `register-members.py`.
- **G5. The vault's shas change only on a certified release.** Certifying a release is the
  operator act: today's ratify, re-aimed from "the bytes that happen to be installed" to "this GT
  release". Its record is the release id, the per-file shas, and the registration digest. A
  deploy that brings a new GT release is a PROPOSAL until certified. Live hooks keep projecting
  the last certified release, never the newest uncertified one.
- **G6. Repair and restore copy from local GT.** Restore after a Discover bypass (#1158), repair
  of a MODIFIED gate, and repair of a de-registered one: each is "project the certified GT for
  this member", the same code path as G4.
- **G7. A local GT that doesn't match the published or certified sha is MISWIRED.** The edges
  checked are:
  - local GT against its own manifest;
  - local GT against the vault's certified release;
  - live against local GT, for both bytes and registration.

  Each mismatch is a named finding on the chain and in the inventory. A de-registered gate (the
  #1156 shape) is a finding, and Forget is not offered while the member declares a gate role
  (the #1150 fix).
- **G8. Discover bypass stays a session-scoped override.** G4 undoes it on the next start by
  construction, so a bypass cannot outlive the daemon session unless someone re-applies it.
  Today it survives a restart (#1157).

## 4. What exists to build on

| need | existing piece | gap |
|---|---|---|
| content-addressed local copy | `$HESTIA_HOME/shared.builds` + atomic `shared` link (#481 stage 1) | covers only `_shared`; extend it to hook files + registration |
| per-file digests in a manifest | `RUNTIME_MANIFEST.txt`, `current-build.json` `shared_engine[]` | a declaration without digests; hooks are listed per member in `expects.json` |
| registration templates | `plugins/<member>/hooks/hooks.json` (codex, gemini; kimi in #1149; claude in #1142) | rendered additively; not in any digest |
| live comparison | `gate_watch` (#1085), `/api/gates/verify` | reads paths, not registration (#1156) |
| operator certification | ratify per gate (#1150) | certifies installed bytes, not a release |
| one witness per harness | `hestia_witness_core` + identical shims (#1149) | would be published as GT files like the gate |

## 5. Open questions for dp

1. **Directory:** a new top-level `hooks-gt/<harness>/`, or promote `plugins/<member>/` to be the
   GT, with its manifest? The latter avoids a second copy of every hook in the repo.
2. **Certification granularity:** per release (the whole GT set at once) or per member? Per
   release matches "certified releases". Per member lets one harness move without re-certifying
   the others.
3. **Seats that run hooks from a checkout** (HUB, which runs the working tree in place): does G4
   project onto them too, ending that layout? It must, for "live populated from GT" to hold
   everywhere.
4. **Harness hook caching:** Claude Code and others may read hook config only at session start.
   G4 fixes the files and config on disk, but a running session may still execute the old
   registration until it restarts. Should the projection record per-session staleness, or accept
   that restart boundary as the model?

## 6. Slices (proposed order)

1. **GT manifest + header digest + CI check (G1, G2).** Pure repo work; nothing is deployed.
2. **Local GT store (G3).** Extend `shared.builds` to the hook files and registration.
3. **Startup projection + restore/repair from GT (G4, G6, G8).** Replaces the Discover restore's
   token swap with the GT projection.
4. **Certification by release (G5).** Re-aim ratify at a release; the vault record grows a
   registration digest.
5. **The mismatch findings (G7).** Includes #1156's de-registered-gate finding.
